"""Every database read and write the API and the worker make, in one place. Parameterised SQL only.

Functions take an open connection (rows come back as dicts), so a caller can group several of them
in one transaction.
"""

import json

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app import policy as policies

# ---------------------------------------------------------------- policy versions


async def bootstrap_policy(conn: AsyncConnection) -> None:
    """Insert v1 from policies/v1.yaml if the database has no policy yet.

    If v1 is already stored with different content, refuse to start: a published version is frozen,
    so an edited v1.yaml would silently disagree with the labels made under it.
    """
    body = policies.load_file(policies.POLICIES_DIR / "v1.yaml")
    row = await (await conn.execute("SELECT content_hash FROM policy_versions WHERE name = 'v1'")).fetchone()
    if row is None:
        await conn.execute(
            "INSERT INTO policy_versions (name, status, body, content_hash, model_hash, author, published_by,"
            " published_at, tested_hash)"
            " VALUES ('v1', 'live', %s, %s, %s, 'bootstrap', 'bootstrap', now(), %s)",
            (
                Jsonb(body),
                policies.content_hash(body),
                policies.model_hash(body),
                policies.content_hash(body),
            ),
        )
    elif row["content_hash"] != policies.content_hash(body):
        raise RuntimeError(
            "policies/v1.yaml differs from the v1 stored in the database. Published versions are frozen: "
            "restore the file, or reset the database (docker compose down -v) to start again."
        )


async def live_policy(conn: AsyncConnection) -> dict:
    row = await (await conn.execute("SELECT * FROM policy_versions WHERE status = 'live'")).fetchone()
    if row is None:
        raise RuntimeError("no live policy version")
    return row


async def policy_version(conn: AsyncConnection, name: str) -> dict | None:
    return await (await conn.execute("SELECT * FROM policy_versions WHERE name = %s", (name,))).fetchone()


# ---------------------------------------------------------------- postings and jobs


async def posting(conn: AsyncConnection, posting_id: int) -> dict | None:
    return await (await conn.execute("SELECT * FROM postings WHERE id = %s", (posting_id,))).fetchone()


async def submit_posting(
    conn: AsyncConnection, client_id: str, posting: dict, batch_id: int | None = None
) -> dict:
    """Save a posting and queue it under the live version.

    Returns {"status": "queued" | "duplicate" | "conflict", "posting_id", "job_id"}. The same job id
    with the same content is a duplicate (nothing new is queued); with different content, a conflict.
    """
    raw_hash = policies.stable_hash(posting)
    row = await (
        await conn.execute(
            "INSERT INTO postings (client_id, job_id, raw, raw_hash) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (client_id, job_id) DO NOTHING RETURNING id",
            (client_id, posting["job_id"], Jsonb(posting), raw_hash),
        )
    ).fetchone()
    if row is None:
        existing = await (
            await conn.execute(
                "SELECT id, raw_hash FROM postings WHERE client_id = %s AND job_id = %s",
                (client_id, posting["job_id"]),
            )
        ).fetchone()
        status = "duplicate" if existing["raw_hash"] == raw_hash else "conflict"
        return {"status": status, "posting_id": existing["id"], "job_id": posting["job_id"]}
    live = await live_policy(conn)
    await enqueue(conn, row["id"], live["name"], live["content_hash"], "live", batch_id)
    return {"status": "queued", "posting_id": row["id"], "job_id": posting["job_id"]}


async def enqueue(conn, posting_id: int, version: str, policy_hash: str, queue: str, batch_id=None) -> None:
    """Queue a posting for labeling, unless a job for it under this version is already open."""
    await conn.execute(
        "INSERT INTO jobs (posting_id, policy_version, policy_hash, queue, batch_id)"
        " VALUES (%s, %s, %s, %s, %s)"
        " ON CONFLICT (posting_id, policy_version) WHERE status IN ('queued', 'running') DO NOTHING",
        (posting_id, version, policy_hash, queue, batch_id),
    )


async def new_batch(conn: AsyncConnection, client_id: str) -> int:
    row = await (
        await conn.execute("INSERT INTO batches (client_id) VALUES (%s) RETURNING id", (client_id,))
    ).fetchone()
    return row["id"]


async def save_dataset_label(conn: AsyncConnection, posting_id: int, fraudulent: bool) -> None:
    """Demo only: the dataset's label for a posting the live demo sent (see app/demo.py)."""
    await conn.execute(
        "INSERT INTO dataset_labels (posting_id, fraudulent) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (posting_id, fraudulent),
    )


async def batch_summary(conn: AsyncConnection, batch_id: int) -> dict | None:
    """A batch for the analysts: how far its labeling got, the labels, how many skipped Claude, cost
    and latency, and (for a live-demo run) how the labels compare with the dataset's."""
    batch = await (await conn.execute("SELECT * FROM batches WHERE id = %s", (batch_id,))).fetchone()
    if batch is None:
        return None
    rows = await (
        await conn.execute(
            """
            SELECT j.status, l.label, l.reason_codes, l.cost_usd, l.latency_ms, ds.fraudulent
            FROM jobs j
            LEFT JOIN LATERAL (
                SELECT * FROM labels WHERE posting_id = j.posting_id AND policy_version = j.policy_version
                ORDER BY created_at DESC LIMIT 1
            ) l ON true
            LEFT JOIN dataset_labels ds ON ds.posting_id = j.posting_id
            WHERE j.batch_id = %s
            """,
            (batch_id,),
        )
    ).fetchall()
    labeled = [r for r in rows if r["label"] is not None]
    latencies = sorted(r["latency_ms"] for r in labeled)
    flagged = {"VIOLATING", "NEEDS_REVIEW"}
    with_dataset = [r for r in labeled if r["fraudulent"] is not None]
    return {
        "batch_id": batch_id,
        "created_at": batch["created_at"],
        "postings": len(rows),
        "labeled": len(labeled),
        "waiting": sum(r["status"] in ("queued", "running") for r in rows),
        "labels": {
            k: sum(r["label"] == k for r in labeled) for k in ("VIOLATING", "NEEDS_REVIEW", "ALLOWED")
        },
        "without_claude": sum(
            bool({"cleared_by_screen", "injection", "cached"} & set(r["reason_codes"])) for r in labeled
        ),
        "cost_usd": round(float(sum(r["cost_usd"] for r in labeled)), 4),
        "latency_ms": {
            "p50": latencies[len(latencies) // 2] if latencies else None,
            "p95": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None,
        },
        "dataset": None
        if not any(r["fraudulent"] is not None for r in rows)
        else {
            "fraud": sum(bool(r["fraudulent"]) for r in rows),
            "caught": sum(bool(r["fraudulent"]) and r["label"] in flagged for r in with_dataset),
            "false_alarms": sum(r["fraudulent"] is False and r["label"] in flagged for r in with_dataset),
        },
    }


async def batch_progress(conn: AsyncConnection, batch_id: int, client_id: str) -> dict | None:
    owner = await (
        await conn.execute("SELECT id FROM batches WHERE id = %s AND client_id = %s", (batch_id, client_id))
    ).fetchone()
    if owner is None:
        return None
    rows = await (
        await conn.execute(
            "SELECT status, count(*) AS n FROM jobs WHERE batch_id = %s GROUP BY status", (batch_id,)
        )
    ).fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    return {"batch_id": batch_id, "total": sum(counts.values()), **counts}


# ---------------------------------------------------------------- labels


async def save_label(
    conn: AsyncConnection,
    job: dict,
    state: dict,
    model_version: str,
    latency_ms: int,
    trace_id: str | None = None,
) -> int:
    """Store the graph's result. One row per (posting, policy version, model version):
    a re-run replaces it."""
    decision = state["decision"]
    checked = state.get("checked") or {}
    row = await (
        await conn.execute(
            """
            INSERT INTO labels (posting_id, policy_version, policy_hash, model_version, label, sections,
                evidence, findings, raw_output, facts, screen, rationale, confidence, reason_codes,
                cleaned, cache_key, derived_from, cost_usd, latency_ms, trace_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (posting_id, policy_version, model_version) DO UPDATE SET
                policy_hash = EXCLUDED.policy_hash, label = EXCLUDED.label, sections = EXCLUDED.sections,
                evidence = EXCLUDED.evidence, findings = EXCLUDED.findings, raw_output = EXCLUDED.raw_output,
                facts = EXCLUDED.facts, screen = EXCLUDED.screen, rationale = EXCLUDED.rationale,
                confidence = EXCLUDED.confidence, reason_codes = EXCLUDED.reason_codes,
                cleaned = EXCLUDED.cleaned,
                cache_key = EXCLUDED.cache_key, derived_from = EXCLUDED.derived_from,
                cost_usd = EXCLUDED.cost_usd, latency_ms = EXCLUDED.latency_ms, trace_id = EXCLUDED.trace_id,
                created_at = now()
            RETURNING id
            """,
            (
                job["posting_id"],
                job["policy_version"],
                job["policy_hash"],
                model_version,
                decision["label"],
                decision["sections"],
                Jsonb(decision["evidence"]),
                Jsonb(checked.get("findings", [])),
                Jsonb(state.get("raw_output")),
                Jsonb(state.get("facts") or {}),
                Jsonb(state.get("screen")),
                decision["rationale"],
                decision["confidence"],
                decision["reason_codes"],
                Jsonb(state.get("cleaned") or {}),
                state.get("cache_key"),
                state.get("cached_from"),
                round(sum(u.get("cost_usd", 0) for u in state.get("usage", [])), 6),
                latency_ms,
                trace_id,
            ),
        )
    ).fetchone()
    return row["id"]


async def save_derived_label(
    conn: AsyncConnection, source: dict, version: str, policy_hash: str, decision: dict, findings: list
) -> None:
    """A label decided again in code from a stored one (re-decide): same model answer, same models,
    a new policy version. No model call, so it costs $0."""
    await conn.execute(
        """
        INSERT INTO labels (posting_id, policy_version, policy_hash, model_version, label, sections,
            evidence, findings, raw_output, facts, screen, rationale, confidence, reason_codes,
            cleaned, derived_from, cost_usd, latency_ms)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 0)
        ON CONFLICT (posting_id, policy_version, model_version) DO UPDATE SET
            policy_hash = EXCLUDED.policy_hash, label = EXCLUDED.label, sections = EXCLUDED.sections,
            evidence = EXCLUDED.evidence, findings = EXCLUDED.findings, rationale = EXCLUDED.rationale,
            confidence = EXCLUDED.confidence, reason_codes = EXCLUDED.reason_codes,
            derived_from = EXCLUDED.derived_from, created_at = now()
        """,
        (
            source["posting_id"],
            version,
            policy_hash,
            source["model_version"],
            decision["label"],
            decision["sections"],
            Jsonb(decision["evidence"]),
            Jsonb(findings),
            Jsonb(source["raw_output"]),
            Jsonb(source["facts"]),
            Jsonb(source["screen"]),
            decision["rationale"],
            decision["confidence"],
            decision["reason_codes"],
            Jsonb(source["cleaned"]),
            source["id"],
        ),
    )


async def cache_lookup(conn: AsyncConnection, key: str) -> dict | None:
    """The newest label made from exactly the same model input, policy and models, to reuse."""
    row = await (
        await conn.execute(
            "SELECT id, label, sections, evidence, rationale, confidence, reason_codes FROM labels"
            " WHERE cache_key = %s AND derived_from IS NULL ORDER BY id DESC LIMIT 1",
            (key,),
        )
    ).fetchone()
    if row is None:
        return None
    decision = {
        k: row[k] for k in ("label", "sections", "evidence", "rationale", "confidence", "reason_codes")
    }
    decision["reason_codes"] = [*decision["reason_codes"], "cached"]
    return {"decision": decision, "label_id": row["id"]}


async def read_label(conn: AsyncConnection, client_id: str, job_id: str) -> dict | None:
    """The label a client sees for one of its postings, by the read rule:
    1. the analyst's decision; 2. the model label under the live version; 3. the newest model label
    under an older version, marked stale with the re-label's status. None if the posting isn't theirs.
    """
    posting = await (
        await conn.execute(
            "SELECT id, job_id FROM postings WHERE client_id = %s AND job_id = %s", (client_id, job_id)
        )
    ).fetchone()
    if posting is None:
        return None
    live = await live_policy(conn)
    label = await (
        await conn.execute(
            "SELECT * FROM labels WHERE posting_id = %s"
            " ORDER BY (policy_version = %s) DESC, created_at DESC LIMIT 1",
            (posting["id"], live["name"]),
        )
    ).fetchone()
    decision = await (
        await conn.execute(
            "SELECT * FROM decisions WHERE posting_id = %s ORDER BY created_at DESC LIMIT 1", (posting["id"],)
        )
    ).fetchone()
    if label is None and decision is None:
        return {"job_id": job_id, "status": "queued"}
    out: dict = {"job_id": job_id, "status": "labeled", "live_policy_version": live["name"]}
    if label is not None:
        out |= output_of(label)
        out["stale"] = label["policy_version"] != live["name"]
        if out["stale"]:
            out["relabel_status"] = await relabel_status(conn, posting["id"], live["name"])
    if decision is not None:
        # The analyst's decision stays final, but if the live version's model now disagrees with a
        # decision made under an older version, say so: it goes back to an analyst to look at.
        out["new_policy_disagrees"] = bool(
            label is not None
            and not out.get("stale")
            and decision["policy_version"] != live["name"]
            and label["label"] != decision["label"]
        )
        out |= {
            "label": decision["label"],
            "decided_by": "analyst",
            "decided_at": decision["created_at"].isoformat(),
            "model_label": label["label"] if label else None,
        }
    else:
        out["decided_by"] = "model"
    return out


async def relabel_status(conn: AsyncConnection, posting_id: int, version: str) -> str:
    row = await (
        await conn.execute(
            "SELECT status FROM jobs WHERE posting_id = %s AND policy_version = %s ORDER BY id DESC LIMIT 1",
            (posting_id, version),
        )
    ).fetchone()
    return row["status"] if row else "not_planned"


def output_of(label: dict) -> dict:
    """A labels row as the brief's output, plus what explains it."""
    return {
        "label": label["label"],
        "policy_sections": label["sections"],
        "evidence": [q["text"] for q in label["evidence"]],
        "evidence_spans": label["evidence"],
        "rationale": label["rationale"],
        "confidence": label["confidence"],
        "policy_version": label["policy_version"],
        "reason_codes": label["reason_codes"],
        "findings": label["findings"],
        "screen": label["screen"],
        "model_version": label["model_version"],
        "trace_id": label["trace_id"],
        "labeled_at": label["created_at"].isoformat(),
    }


async def record_decision(conn, posting_id: int, label: str, analyst: str) -> dict:
    live = await live_policy(conn)
    row = await (
        await conn.execute(
            "INSERT INTO decisions (posting_id, label, analyst, policy_version)"
            " VALUES (%s, %s, %s, %s)"
            " RETURNING *",
            (posting_id, label, analyst, live["name"]),
        )
    ).fetchone()
    return row


# ---------------------------------------------------------------- analyst reads

# The newest label per posting under one version, with the latest analyst decision.
# The batch is a scope (a live-demo run), not a chip: the chip counts are counted within it.
_BROWSE = """
WITH current AS (
    SELECT DISTINCT ON (posting_id) * FROM labels WHERE policy_version = %(version)s
      AND (%(batch)s::bigint IS NULL
           OR posting_id IN (SELECT posting_id FROM jobs WHERE batch_id = %(batch)s))
    ORDER BY posting_id, created_at DESC
)
SELECT l.id, l.posting_id, p.job_id, p.client_id, p.raw->>'title' AS title, l.label, l.sections,
       l.confidence, l.rationale, l.reason_codes, l.policy_version, l.created_at, l.findings,
       d.label AS decision, ds.fraudulent AS dataset_fraud
FROM current l
JOIN postings p ON p.id = l.posting_id
LEFT JOIN LATERAL (
    SELECT label FROM decisions WHERE posting_id = l.posting_id ORDER BY created_at DESC LIMIT 1
) d ON true
LEFT JOIN dataset_labels ds ON ds.posting_id = l.posting_id
"""

# A label flags fraud when it is VIOLATING or NEEDS_REVIEW: the same rule as the eval.
_FLAGGED = "label IN ('VIOLATING', 'NEEDS_REVIEW')"


async def browse_labels(conn: AsyncConnection, filters: dict, limit: int, offset: int) -> dict:
    """One row per posting, newest first, plus counts per label and per section for the filter chips.
    The counts use the version only, so each chip shows what choosing it would give."""
    where = [
        "(%(label)s::text IS NULL OR l.label = %(label)s)",
        "(%(section)s::text IS NULL OR %(section)s = ANY(l.sections))",
        "(%(reason)s::text IS NULL OR %(reason)s = ANY(l.reason_codes))",
        "(%(job_id)s::text IS NULL OR p.job_id = %(job_id)s)",
        # only where the model and the dataset disagree (demo comparison)
        f"(NOT %(disagree)s OR (ds.fraudulent IS NOT NULL AND ds.fraudulent <> (l.{_FLAGGED})))",
    ]
    params = {"batch": None, "disagree": False, **filters, "limit": limit, "offset": offset}
    rows = await (
        await conn.execute(
            # newest postings first, by arrival: the same order under every policy version
            _BROWSE + " WHERE " + " AND ".join(where) + " ORDER BY p.created_at DESC, p.id DESC"
            " LIMIT %(limit)s OFFSET %(offset)s",
            params,
        )
    ).fetchall()
    total = await (
        await conn.execute(f"SELECT count(*) AS n FROM ({_BROWSE} WHERE {' AND '.join(where)}) t", params)
    ).fetchone()
    by_label = await (
        await conn.execute(f"SELECT label, count(*) AS n FROM ({_BROWSE}) t GROUP BY label", params)
    ).fetchall()
    by_section = await (
        await conn.execute(
            f"SELECT s AS section, count(*) AS n FROM ({_BROWSE}) t, unnest(t.sections) s"
            " GROUP BY s ORDER BY s",
            params,
        )
    ).fetchall()
    compare = filters.get("compare", False)
    for row in rows:
        row["policy_match"] = policy_match(row.pop("findings"))
        row["evidence_preview"] = evidence_preview(row["policy_match"])
        fraud = row.pop("dataset_fraud")
        if compare:
            row["dataset"] = None if fraud is None else ("fraud" if fraud else "legitimate")
    out = {
        "items": rows,
        "total": total["n"],
        "counts": {
            "label": {r["label"]: r["n"] for r in by_label},
            "section": {r["section"]: r["n"] for r in by_section},
        },
    }
    if compare:  # for the rows the filters select
        agreement = await (
            await conn.execute(
                f"""SELECT count(*) FILTER (WHERE dataset_fraud IS NOT NULL) AS with_dataset,
                       count(*) FILTER (WHERE dataset_fraud) AS fraud,
                       count(*) FILTER (WHERE dataset_fraud AND {_FLAGGED}) AS caught,
                       count(*) FILTER (WHERE dataset_fraud = false AND {_FLAGGED}) AS false_alarms
                FROM ({_BROWSE} WHERE {" AND ".join(where)}) t""",
                params,
            )
        ).fetchone()
        out["dataset"] = dict(agreement)
    return out


def policy_match(findings: list[dict]) -> list[dict]:
    """The sections a label rests on (matched first, then unsure), with their evidence, for the list."""
    keep = [f for f in findings if f["status"] == "matched"] + [
        f for f in findings if f["status"] == "unsure"
    ]
    return [
        {k: f.get(k, []) for k in ("section", "status", "quotes", "missing_fields", "reasoning")}
        for f in keep
    ]


def evidence_preview(match: list[dict]) -> dict | None:
    """One line of evidence for the list: the first quote of the first section the label rests on, or
    the empty fields it rests on when it has no quote."""
    for finding in match:
        if finding["quotes"]:
            return {"section": finding["section"], "text": finding["quotes"][0]["text"]}
    for finding in match:
        if finding["missing_fields"]:
            return {"section": finding["section"], "missing": finding["missing_fields"]}
    return None


async def label_detail(conn: AsyncConnection, label_id: int) -> dict | None:
    """One label with everything the decision page shows (and, for a posting the live demo sent, the
    dataset's label, which the page shows only with "Compare with dataset" on)."""
    label = await (await conn.execute("SELECT * FROM labels WHERE id = %s", (label_id,))).fetchone()
    if label is None:
        return None
    post = await posting(conn, label["posting_id"])
    history = await (
        await conn.execute(
            "SELECT id, policy_version, model_version, label, sections, confidence, created_at FROM labels"
            " WHERE posting_id = %s ORDER BY created_at",
            (label["posting_id"],),
        )
    ).fetchall()
    decisions = await (
        await conn.execute(
            "SELECT label, analyst, policy_version, created_at FROM decisions WHERE posting_id = %s"
            " ORDER BY created_at DESC",
            (label["posting_id"],),
        )
    ).fetchall()
    job = await latest_job(conn, label["posting_id"])
    # Exactly what the marketplace gets for this posting now (the read rule), shown on the page.
    api_answer = await read_label(conn, post["client_id"], post["job_id"])
    dataset = await (
        await conn.execute(
            "SELECT fraudulent FROM dataset_labels WHERE posting_id = %s", (label["posting_id"],)
        )
    ).fetchone()
    return {
        **output_of(label),
        "dataset": None if dataset is None else ("fraud" if dataset["fraudulent"] else "legitimate"),
        "api_answer": as_json_safe(api_answer),
        "id": label["id"],
        "posting_id": label["posting_id"],
        "job_id": post["job_id"],
        "client_id": post["client_id"],
        "cleaned": label["cleaned"],
        "facts": label["facts"],
        "cost_usd": float(label["cost_usd"]),
        "latency_ms": label["latency_ms"],
        "derived_from": label["derived_from"],
        "history": history,
        "decisions": decisions,
        "job": job,
    }


async def latest_job(conn: AsyncConnection, posting_id: int) -> dict | None:
    return await (
        await conn.execute(
            "SELECT id, policy_version, queue, status, attempts, thread_id, checkpoints_pruned, created_at,"
            " finished_at FROM jobs WHERE posting_id = %s ORDER BY id DESC LIMIT 1",
            (posting_id,),
        )
    ).fetchone()


def as_json(value) -> str:
    return json.dumps(value, default=str)


def as_json_safe(value):
    """The value as plain JSON types (dates become text), as the API would send it."""
    return json.loads(as_json(value))
