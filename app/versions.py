"""Policy versions: drafts, Test (a shadow run and its flip report), Publish with re-label, rollback.

    draft --edit--> draft --Test--> flip report --Publish--> live --(next publish)--> retired
      |                                                        ^---------- rollback ----------'
      '--discard--> gone (with its Test). Published versions are never deleted.

Test labels a sample of recent postings under the draft, without changing what anyone reads:
  - full mode: shadow jobs, run by the worker (lowest priority), with the draft's content hash in
    the job and the thread id, so an edited draft never reuses an older run;
  - re-decide mode (the draft's model_hash equals the live version's: only effects changed): the
    stored model answers are checked and decided again under the draft, in code, at $0.
The flip report compares those labels with the live ones, and checks the invariants Publish needs.

Publish needs a publisher who never edited the draft (four eyes), a Test of the draft's current
content, and a passing invariant gate. Metric thresholds are not part of it: a version meant to
change labels must be able to publish (metrics gate code changes in CI). Publishing makes the draft
live, retires the old version and re-labels the last 30 days, in the cheapest mode that is valid.
Postings already labeled by the Test keep those labels.

A draft is compared with its parent, the version that was live when it was created. Test and Publish
need that parent to be live still; otherwise the draft must be created again from the live version.

Rollback makes a retired version live again. Its labels are still stored, so they are current again
at once.
"""

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app import policy as policies
from app import store
from app.agent import checkpoints
from app.agent.clean import Cleaned
from app.agent.decide import FAILURES, redecide

RELABEL_DAYS = 30
TEST_SAMPLE = 200


class Refused(Exception):
    """A request the lifecycle doesn't allow. status is the HTTP status; code says why."""

    def __init__(self, status: int, code: str, detail=None):
        super().__init__(code)
        self.status, self.code, self.detail = status, code, detail


# ---------------------------------------------------------------- drafts


async def create_draft(conn: AsyncConnection, name: str, body: dict, author: str) -> dict:
    """A new draft, a child of the live version. Its body's version field is set to its name."""
    if await store.policy_version(conn, name) is not None:
        raise Refused(409, "name_taken")
    body = _valid({**body, "version": name})
    live = await store.live_policy(conn)
    return await (
        await conn.execute(
            "INSERT INTO policy_versions (name, status, parent, body, content_hash, model_hash, author,"
            " edited_by) VALUES (%s, 'draft', %s, %s, %s, %s, %s, %s) RETURNING *",
            (
                name,
                live["name"],
                Jsonb(body),
                policies.content_hash(body),
                policies.model_hash(body),
                author,
                [author],
            ),
        )
    ).fetchone()


async def update_draft(conn: AsyncConnection, name: str, body: dict, editor: str) -> dict:
    """Replace a draft's body. The editor joins edited_by, so they can't publish it."""
    row = await _draft(conn, name)
    body = _valid({**body, "version": name})
    edited_by = row["edited_by"] if editor in row["edited_by"] else [*row["edited_by"], editor]
    # Shadow jobs for the old content would label something that no longer exists.
    await conn.execute(
        "UPDATE jobs SET status = 'failed', last_error = 'draft changed before this job ran',"
        " finished_at = now() WHERE policy_version = %s AND status = 'queued'",
        (name,),
    )
    # An edit takes the draft back to "not submitted": a publisher approves what they see.
    return await (
        await conn.execute(
            "UPDATE policy_versions SET body = %s, content_hash = %s, model_hash = %s, edited_by = %s,"
            " submitted_by = NULL, submitted_at = NULL WHERE name = %s RETURNING *",
            (Jsonb(body), policies.content_hash(body), policies.model_hash(body), edited_by, name),
        )
    ).fetchone()


async def discard_draft(conn: AsyncConnection, name: str) -> dict:
    """Delete a draft and its Test: the Test's jobs, labels and checkpoints never reached anyone.
    Published versions can't be discarded: every label must trace to the policy it used."""
    await _draft(conn, name)
    running = await (
        await conn.execute(
            "SELECT count(*) AS n FROM jobs WHERE policy_version = %s AND status = 'running'", (name,)
        )
    ).fetchone()
    if running["n"]:
        raise Refused(409, "test_running", "stop the Test, then wait a few seconds for it to finish")
    copied = await (
        await conn.execute(
            "SELECT count(*) AS n FROM labels c JOIN labels d ON c.derived_from = d.id"
            " WHERE d.policy_version = %s AND c.policy_version <> %s",
            (name, name),
        )
    ).fetchone()
    if copied["n"]:
        raise Refused(409, "draft_in_use", "labels under other versions were copied from this draft's Test")
    async with conn.transaction():
        threads = await (
            await conn.execute(
                "SELECT thread_id FROM jobs WHERE policy_version = %s AND thread_id IS NOT NULL", (name,)
            )
        ).fetchall()
        await checkpoints.delete_threads(conn, [t["thread_id"] for t in threads])
        labels = (await conn.execute("DELETE FROM labels WHERE policy_version = %s", (name,))).rowcount
        await conn.execute("DELETE FROM jobs WHERE policy_version = %s", (name,))
        await conn.execute("DELETE FROM policy_versions WHERE name = %s", (name,))
    return {"discarded": name, "labels_deleted": labels}


async def test_labels(conn: AsyncConnection, name: str) -> int:
    """Labels made under a draft by any of its Tests, including Tests of content it no longer has."""
    query = "SELECT count(*) AS n FROM labels WHERE policy_version = %s"
    return (await (await conn.execute(query, (name,))).fetchone())["n"]


def relabel_mode(new: dict, old: dict) -> str:
    """re-decide when the models would see exactly the same thing (only effects changed), else full."""
    return "redecide" if new["model_hash"] == old["model_hash"] else "full"


# ---------------------------------------------------------------- Test


async def relabel_scope(conn: AsyncConnection, version: str) -> int:
    """How many postings a publish would label again: those labeled under the version in the last
    RELABEL_DAYS. A Test of that many covers all of them, so the publish itself runs nothing."""
    row = await (
        await conn.execute(
            "SELECT count(DISTINCT l.posting_id) AS n FROM labels l JOIN postings p ON p.id = l.posting_id"
            " WHERE l.policy_version = %s AND p.created_at > now() - make_interval(days => %s)",
            (version, RELABEL_DAYS),
        )
    ).fetchone()
    return row["n"]


async def start_test(conn: AsyncConnection, name: str, limit: int = TEST_SAMPLE) -> dict:
    """Label the most recent postings (up to limit) under the draft, in shadow."""
    draft = await _draft(conn, name)
    live = await _parent_is_live(conn, draft)
    await conn.execute("UPDATE policy_versions SET tested_hash = content_hash WHERE name = %s", (name,))
    labels = await _recent_labels(conn, live["name"], limit)
    mode = relabel_mode(draft, live)
    queued = redecided = 0
    for label in labels:
        if mode == "redecide" and await _save_redecided(conn, label, draft):
            redecided += 1
        else:
            await store.enqueue(conn, label["posting_id"], name, draft["content_hash"], "shadow")
            queued += 1
    return {"version": name, "mode": mode, "postings": len(labels), "queued": queued, "redecided": redecided}


async def test_report(conn: AsyncConnection, name: str) -> dict:
    """The flip report for the draft's current content against its parent, and the invariant gate
    Publish needs. It still reads the same after the draft is published."""
    draft = await store.policy_version(conn, name)
    if draft is None:
        raise Refused(404, "not_found")
    parent = await store.policy_version(conn, draft["parent"])
    jobs = await _job_counts(conn, name, draft["content_hash"], "shadow")
    rows = await (
        await conn.execute(
            """
            SELECT n.id, n.posting_id, p.job_id, n.label, n.sections, n.evidence, n.cleaned, n.reason_codes,
                   n.cost_usd, n.derived_from, o.id AS live_label_id, o.label AS live_label,
                   o.sections AS live_sections
            FROM labels n
            JOIN postings p ON p.id = n.posting_id
            LEFT JOIN LATERAL (
                SELECT id, label, sections FROM labels
                WHERE posting_id = n.posting_id AND policy_version = %s ORDER BY created_at DESC LIMIT 1
            ) o ON true
            WHERE n.policy_version = %s AND n.policy_hash = %s
            ORDER BY n.id
            """,
            (parent["name"], name, draft["content_hash"]),
        )
    ).fetchall()
    changed_codes = {c["where"].split(".")[0] for c in policies.diff(parent["body"], draft["body"])}
    flips, matrix = [], {}
    for row in rows:
        key = f"{row['live_label']} -> {row['label']}"
        matrix[key] = matrix.get(key, 0) + 1
        if row["live_label"] != row["label"] or row["live_sections"] != row["sections"]:
            flips.append(
                {
                    "posting_id": row["posting_id"],
                    "job_id": row["job_id"],
                    "label_id": row["id"],  # the draft's label
                    "live_label_id": row["live_label_id"],  # what anyone sees now: the report links here
                    "before": {"label": row["live_label"], "sections": row["live_sections"]},
                    "after": {"label": row["label"], "sections": row["sections"]},
                    "from_the_change": _from_the_change(row, changed_codes),
                }
            )
    invariants = _invariants(draft, jobs, rows)
    return {
        "version": name,
        "compared_with": parent["name"],
        "mode": relabel_mode(draft, parent),
        "tested_current_content": draft["tested_hash"] == draft["content_hash"],
        "jobs": jobs,
        "labeled": len(rows),
        "changed": matrix,
        "flips": flips,
        "flips_from_the_change": sum(f["from_the_change"] for f in flips),
        "model_calls": sum(r["derived_from"] is None for r in rows),
        "cost_usd": round(sum(float(r["cost_usd"]) for r in rows), 4),
        "invariants": invariants,
        "passed": bool(rows) and all(i["passed"] for i in invariants),
    }


def _from_the_change(row: dict, changed_codes: set[str]) -> bool:
    """Whether a flip involves a section the draft changed. A full re-label asks the model again,
    and the model doesn't answer identically every time, so some flips are its variation, not the
    policy's doing. Involved: a section that appeared or went away, or, when the label itself
    changed, any section the label rests on."""
    before, after = set(row["live_sections"] or []), set(row["sections"])
    involved = before ^ after
    if row["live_label"] != row["label"]:
        involved |= before | after
    return bool(involved & changed_codes)


def _invariants(draft: dict, jobs: dict, rows: list[dict]) -> list[dict]:
    """What must hold for any version, whatever labels it is meant to change."""
    unverbatim = [
        r["posting_id"]
        for r in rows
        for q in r["evidence"]
        if r["cleaned"].get(q["field"], "")[q["start"] : q["end"]] != q["text"]
    ]
    return [
        {"name": "test_of_current_content", "passed": draft["tested_hash"] == draft["content_hash"]},
        {"name": "finished", "passed": not (jobs.get("queued") or jobs.get("running"))},
        {
            "name": "nothing_errored",
            "passed": not jobs.get("failed") and not any("dlq" in r["reason_codes"] for r in rows),
        },
        {"name": "evidence_is_verbatim", "passed": not unverbatim, "postings": unverbatim},
        {
            "name": "violating_has_evidence",
            "passed": all(r["evidence"] for r in rows if r["label"] == "VIOLATING"),
        },
    ]


async def stop_test(conn: AsyncConnection, name: str) -> dict:
    """Stop a Test: its queued postings are dropped; any being labeled now finish. The Test then
    stands on the postings it labeled."""
    draft = await _draft(conn, name)
    dropped = await (
        await conn.execute(
            "DELETE FROM jobs WHERE policy_version = %s AND policy_hash = %s AND queue = 'shadow'"
            " AND status = 'queued' RETURNING id",
            (name, draft["content_hash"]),
        )
    ).fetchall()
    return {"version": name, "dropped": len(dropped)}


async def submit(conn: AsyncConnection, name: str, editor: str) -> dict:
    """Mark a draft ready for a publisher. It needs a finished, passing Test of its current content."""
    draft = await _draft(conn, name)
    if draft["tested_hash"] != draft["content_hash"]:
        raise Refused(409, "test_outdated", "Test this draft first")
    report = await test_report(conn, name)
    if not report["passed"]:
        raise Refused(409, "test_not_passed", [i for i in report["invariants"] if not i["passed"]])
    return await (
        await conn.execute(
            "UPDATE policy_versions SET submitted_by = %s, submitted_at = now() WHERE name = %s RETURNING *",
            (editor, name),
        )
    ).fetchone()


async def compare(conn: AsyncConnection, old: str, new: str) -> dict:
    """Every posting labeled under both versions, side by side: did its label or sections change, and
    does the change involve a section that differs between the two versions (or is it the model
    answering differently)?"""
    versions = {}
    for name in (old, new):
        versions[name] = await store.policy_version(conn, name)
        if versions[name] is None:
            raise Refused(404, "not_found")
    changed_codes = {
        c["where"].split(".")[0] for c in policies.diff(versions[old]["body"], versions[new]["body"])
    }
    rows = await (
        await conn.execute(
            """
            WITH a AS (SELECT DISTINCT ON (posting_id) * FROM labels WHERE policy_version = %(old)s
                       ORDER BY posting_id, created_at DESC),
                 b AS (SELECT DISTINCT ON (posting_id) * FROM labels WHERE policy_version = %(new)s
                       ORDER BY posting_id, created_at DESC)
            SELECT p.id AS posting_id, p.job_id, p.raw->>'title' AS title,
                   a.id AS old_id, a.label AS old_label, a.sections AS old_sections,
                   b.id AS new_id, b.label AS new_label, b.sections AS new_sections
            FROM a JOIN b ON b.posting_id = a.posting_id JOIN postings p ON p.id = a.posting_id
            ORDER BY b.created_at DESC, p.id DESC
            """,
            {"old": old, "new": new},
        )
    ).fetchall()
    out = []
    for r in rows:
        changed = r["old_label"] != r["new_label"] or r["old_sections"] != r["new_sections"]
        same_shape = {
            "live_sections": r["old_sections"],
            "sections": r["new_sections"],
            "live_label": r["old_label"],
            "label": r["new_label"],
        }
        out.append(
            {
                "posting_id": r["posting_id"],
                "job_id": r["job_id"],
                "title": r["title"],
                "old": {"label_id": r["old_id"], "label": r["old_label"], "sections": r["old_sections"]},
                "new": {"label_id": r["new_id"], "label": r["new_label"], "sections": r["new_sections"]},
                "changed": changed,
                "from_the_change": changed and _from_the_change(same_shape, changed_codes),
            }
        )
    return {
        "old": old,
        "new": new,
        "postings": len(out),
        "changed": sum(r["changed"] for r in out),
        "from_the_change": sum(r["from_the_change"] for r in out),
        "rows": out,
    }


# ---------------------------------------------------------------- Publish, re-label, rollback


async def publish(conn: AsyncConnection, name: str, publisher: str) -> dict:
    draft = await _draft(conn, name)
    if publisher in draft["edited_by"]:
        raise Refused(403, "four_eyes", "a publisher who edited this draft can't publish it")
    if draft["tested_hash"] != draft["content_hash"]:
        raise Refused(409, "test_outdated", "the draft changed after its Test, or was never tested")
    old = await _parent_is_live(conn, draft)
    report = await test_report(conn, name)
    if not report["passed"]:
        raise Refused(409, "test_not_passed", [i for i in report["invariants"] if not i["passed"]])

    async with conn.transaction():
        await conn.execute("UPDATE policy_versions SET status = 'retired' WHERE name = %s", (old["name"],))
        await conn.execute(
            "UPDATE policy_versions SET status = 'live', published_by = %s, published_at = now()"
            " WHERE name = %s",
            (publisher, name),
        )
        relabel = await _relabel(conn, draft, old)
    return {"published": name, "retired": old["name"], **relabel}


async def _relabel(conn: AsyncConnection, new: dict, old: dict) -> dict:
    """Label the last RELABEL_DAYS of postings under the new version, unless the Test already did."""
    mode = relabel_mode(new, old)
    labels = await (
        await conn.execute(
            """
            SELECT DISTINCT ON (l.posting_id) l.* FROM labels l JOIN postings p ON p.id = l.posting_id
            WHERE l.policy_version = %s AND p.created_at > now() - make_interval(days => %s)
              AND NOT EXISTS (SELECT 1 FROM labels t WHERE t.posting_id = l.posting_id
                              AND t.policy_version = %s AND t.policy_hash = %s)
            ORDER BY l.posting_id, l.created_at DESC
            """,
            (old["name"], RELABEL_DAYS, new["name"], new["content_hash"]),
        )
    ).fetchall()
    redecided = queued = 0
    for label in labels:
        if mode == "redecide" and await _save_redecided(conn, label, new):
            redecided += 1
        else:
            await store.enqueue(conn, label["posting_id"], new["name"], new["content_hash"], "backfill")
            queued += 1
    tested = await (
        await conn.execute(
            "SELECT count(*) AS n FROM labels WHERE policy_version = %s AND policy_hash = %s",
            (new["name"], new["content_hash"]),
        )
    ).fetchone()
    return {
        "mode": mode,
        "redecided": redecided,
        "queued": queued,
        "labeled_by_test": tested["n"] - redecided,
    }


async def rollback(conn: AsyncConnection, name: str) -> dict:
    target = await store.policy_version(conn, name)
    if target is None:
        raise Refused(404, "not_found")
    if target["status"] != "retired":
        raise Refused(409, "not_retired", "only a version that was live before can be made live again")
    old = await store.live_policy(conn)
    async with conn.transaction():
        await conn.execute("UPDATE policy_versions SET status = 'retired' WHERE name = %s", (old["name"],))
        await conn.execute("UPDATE policy_versions SET status = 'live' WHERE name = %s", (name,))
    return {"live": name, "retired": old["name"]}


async def relabel_progress(conn: AsyncConnection, name: str) -> dict:
    """The labels under a version, and for a published one, where its re-label stands: postings kept
    from the Test, labeled again at or after Publish (in code at $0, or by the models), and waiting.
    Postings that arrived after Publish are counted apart: they are new, not re-labeled."""
    version = await store.policy_version(conn, name)
    if version is None:
        raise Refused(404, "not_found")
    counts = await (
        await conn.execute(
            """
            SELECT count(*) AS labels,
                   count(*) FILTER (WHERE l.derived_from IS NOT NULL AND l.cost_usd = 0) AS without_model,
                   coalesce(sum(l.cost_usd), 0) AS cost_usd,
                   count(*) FILTER (WHERE l.created_at < v.published_at) AS kept_from_test,
                   count(*) FILTER (WHERE l.created_at >= v.published_at AND p.created_at < v.published_at)
                       AS relabeled,
                   count(*) FILTER (WHERE l.created_at >= v.published_at AND p.created_at < v.published_at
                                    AND l.derived_from IS NOT NULL AND l.cost_usd = 0) AS relabeled_in_code,
                   coalesce(sum(l.cost_usd) FILTER (WHERE l.created_at >= v.published_at
                                                    AND p.created_at < v.published_at), 0) AS relabel_cost,
                   count(*) FILTER (WHERE p.created_at >= v.published_at) AS new_postings
            FROM labels l
            JOIN postings p ON p.id = l.posting_id
            JOIN policy_versions v ON v.name = l.policy_version
            WHERE l.policy_version = %s AND l.policy_hash = %s
            """,
            (name, version["content_hash"]),
        )
    ).fetchone()
    jobs = await _job_counts(conn, name, version["content_hash"], "backfill")
    waiting = jobs.get("queued", 0) + jobs.get("running", 0)
    return {
        "version": name,
        "status": version["status"],
        "jobs": jobs,
        "labels": counts["labels"],
        "labels_without_a_model_call": counts["without_model"],
        "cost_usd": round(float(counts["cost_usd"]), 4),
        "relabel": None
        if version["published_at"] is None
        else {
            "kept_from_test": counts["kept_from_test"],
            "relabeled": counts["relabeled"],
            "in_code": counts["relabeled_in_code"],
            "waiting": waiting,
            "total": counts["kept_from_test"] + counts["relabeled"] + waiting,
            "cost_usd": round(float(counts["relabel_cost"]), 4),
        },
        "new_postings": counts["new_postings"],
    }


# ---------------------------------------------------------------- helpers


async def _save_redecided(conn: AsyncConnection, label: dict, version: dict) -> bool:
    """Decide again in code from what the label stored. False if it can't be done that way: a failed
    run, or a label with no stored model answer (a cache hit); those are labeled in full instead."""
    if set(label["reason_codes"]) & {"dlq", *FAILURES}:
        return False
    screen = label["screen"] or {}
    if label["raw_output"] is None and not screen.get("cleared") and not screen.get("injection_flag"):
        return False
    decision, checked = redecide(
        version["body"],
        label["raw_output"],
        Cleaned(fields=label["cleaned"], facts=label["facts"]),
        cleared_scores=screen.get("scores") if screen.get("cleared") else None,
        injection=bool(screen.get("injection_flag")),
    )
    decision.reason_codes += screen.get("reason_codes", [])
    await store.save_derived_label(
        conn,
        label,
        version["name"],
        version["content_hash"],
        decision.model_dump(),
        [f.model_dump() for f in checked.findings] if checked else [],
    )
    return True


async def _recent_labels(conn: AsyncConnection, version: str, limit: int) -> list[dict]:
    return await (
        await conn.execute(
            """
            SELECT * FROM (
                SELECT DISTINCT ON (l.posting_id) l.* FROM labels l JOIN postings p ON p.id = l.posting_id
                WHERE l.policy_version = %s AND p.created_at > now() - make_interval(days => %s)
                ORDER BY l.posting_id, l.created_at DESC
            ) t ORDER BY created_at DESC LIMIT %s
            """,
            (version, RELABEL_DAYS, limit),
        )
    ).fetchall()


async def _job_counts(conn: AsyncConnection, name: str, content_hash: str, queue: str) -> dict:
    rows = await (
        await conn.execute(
            "SELECT status, count(*) AS n FROM jobs WHERE policy_version = %s AND policy_hash = %s"
            " AND queue = %s GROUP BY status",
            (name, content_hash, queue),
        )
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}


async def _parent_is_live(conn: AsyncConnection, draft: dict) -> dict:
    live = await store.live_policy(conn)
    if draft["parent"] != live["name"]:
        raise Refused(409, "parent_not_live", f"{draft['parent']} is no longer live; create the draft again")
    return live


async def _draft(conn: AsyncConnection, name: str) -> dict:
    row = await store.policy_version(conn, name)
    if row is None:
        raise Refused(404, "not_found")
    if row["status"] != "draft":
        raise Refused(409, "not_a_draft", "published versions are frozen")
    return row


def _valid(body: dict) -> dict:
    try:
        return policies.validate(body)
    except policies.PolicyError as error:
        raise Refused(422, "invalid_policy", str(error)) from error
