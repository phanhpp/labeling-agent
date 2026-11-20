"""Policy versions through the API: drafts, Test and its flip report, Publish, re-label, rollback."""

import copy

from app import policy as policies
from app import queue as jobs
from tests.helpers import CLEAN, POSTING, as_, drain, sql, submit

V1 = policies.load_file(policies.POLICIES_DIR / "v1.yaml")
V2 = policies.load_file(policies.POLICIES_DIR / "v2.yaml")

IMPERSONATION = {
    "job_id": "p3",
    "title": "Pipeline Engineer",
    "has_company_logo": "0",
    "description": "Corporate overview: Tavistock Offshore is a global provider of subsea systems.",
}
HIGH_PAY = {
    "job_id": "p4",
    "title": "Typist",
    "company_profile": "Quillfeather Media publishes cooking magazines in Leeds.",
    "description": "Earn $4,000 a week from home. No experience needed.",
}


def effects_only(effect_of_s4: str = "NEEDS_REVIEW") -> dict:
    body = copy.deepcopy(V1)
    body["sections"][3]["effect"] = effect_of_s4
    return body


async def labeled(api, worker, *postings):
    await submit(api, *postings)
    await drain(worker)


async def draft(api, name, body, user="editor"):
    return await api.post("/policies/drafts", json={"name": name, "body": body}, headers=as_(user))


async def run_draft_test(api, worker, name, **params):
    started = await api.post(f"/policies/drafts/{name}/test", params=params, headers=as_("editor"))
    assert started.status_code == 202, started.text
    await drain(worker)
    return (await api.get(f"/policies/drafts/{name}/test", headers=as_("viewer"))).json()


async def label_of(api, job_id):
    return (await api.get(f"/v1/postings/{job_id}/label", headers=as_("marketplace"))).json()


# ---------------------------------------------------------------- drafts


async def test_an_editor_creates_a_draft_and_a_viewer_cannot(api):
    created = await draft(api, "v2", V2)
    assert created.status_code == 201
    out = created.json()
    assert (out["status"], out["parent"], out["author"], out["edited_by"]) == (
        "draft",
        "v1",
        "eddie",
        ["eddie"],
    )
    assert (await draft(api, "v9", V2, user="viewer")).status_code == 403
    assert (await draft(api, "v2", V2)).json()["error"] == "name_taken"


async def test_a_draft_without_a_body_copies_the_live_version(api):
    await api.post("/policies/drafts", json={"name": "v2"}, headers=as_("editor"))
    body = (await api.get("/policies/v2", headers=as_("viewer"))).json()["body"]
    assert body["sections"] == V1["sections"] and body["version"] == "v2"


async def test_an_invalid_policy_is_refused_with_the_reason(api):
    broken = copy.deepcopy(V2)
    broken["sections"][0]["effect"] = "BANNED"
    response = await draft(api, "v2", broken)
    assert response.status_code == 422
    assert "effect must be one of" in response.json()["error"]["detail"]


async def test_editing_adds_the_editor_and_a_published_version_is_frozen(api):
    await draft(api, "v2", V2)
    edited = await api.put("/policies/drafts/v2", json={"body": V2}, headers=as_("publisher_a"))
    assert edited.json()["edited_by"] == ["eddie", "pat"]
    frozen = await api.put("/policies/drafts/v1", json={"body": V1}, headers=as_("editor"))
    assert frozen.status_code == 409 and frozen.json()["error"]["code"] == "not_a_draft"


async def test_the_diff_says_what_changed_and_whether_models_see_it(api):
    await draft(api, "v2", V2)
    await draft(api, "v1b", effects_only())
    v2 = (await api.get("/policies/v2", params={"diff": "v1"}, headers=as_("viewer"))).json()
    assert {"where": "§6", "change": "added", "models_see_it": True} in v2["diff"]["changes"]
    v1b = (await api.get("/policies/v1b", params={"diff": "v1"}, headers=as_("viewer"))).json()
    assert [(c["where"], c["models_see_it"]) for c in v1b["diff"]["changes"]] == [("§4.effect", False)]


# ---------------------------------------------------------------- Test


async def test_a_full_test_runs_in_shadow_and_reports_the_flips(api, worker):
    await labeled(api, worker, POSTING, CLEAN, IMPERSONATION)
    assert (await label_of(api, "p3"))["label"] == "NEEDS_REVIEW"  # §5 only, under v1
    await draft(api, "v2", V2)
    started = await api.post("/policies/drafts/v2/test", headers=as_("editor"))
    assert started.json() == {"version": "v2", "mode": "full", "postings": 3, "queued": 3, "redecided": 0}
    assert {r["queue"] for r in await sql(api, "SELECT queue FROM jobs WHERE policy_version = 'v2'")} == {
        "shadow"
    }

    await drain(worker)
    report = (await api.get("/policies/drafts/v2/test", headers=as_("viewer"))).json()
    assert report["passed"] and report["labeled"] == 3 and report["model_calls"] == 3
    [flip] = report["flips"]
    assert flip["job_id"] == "p3"
    assert flip["before"]["sections"] == ["§5"] and flip["after"]["sections"] == ["§5", "§6"]
    assert flip["from_the_change"] is True and report["flips_from_the_change"] == 1
    assert {i["name"] for i in report["invariants"]} >= {
        "finished",
        "evidence_is_verbatim",
        "nothing_errored",
    }
    # Nothing anyone reads changed: v1 is still live.
    out = await label_of(api, "p3")
    assert out["policy_version"] == "v1" and out["stale"] is False


async def test_an_unfinished_test_does_not_pass(api, worker):
    await labeled(api, worker, POSTING)
    await draft(api, "v2", V2)
    await api.post("/policies/drafts/v2/test", headers=as_("editor"))
    report = (await api.get("/policies/drafts/v2/test", headers=as_("viewer"))).json()
    assert not report["passed"]
    assert {i["name"]: i["passed"] for i in report["invariants"]}["finished"] is False


async def test_an_effects_only_draft_is_tested_in_code_with_no_model_call(api, worker, monkeypatch):
    await labeled(api, worker, POSTING, HIGH_PAY)
    calls = []
    monkeypatch.setattr("app.agent.llm.chat", lambda profile: calls.append(profile))
    await draft(api, "v1b", effects_only())
    started = await api.post("/policies/drafts/v1b/test", headers=as_("editor"))
    assert started.json()["mode"] == "redecide" and started.json()["queued"] == 0
    report = (await api.get("/policies/drafts/v1b/test", headers=as_("viewer"))).json()
    assert report["passed"] and report["model_calls"] == 0 and report["cost_usd"] == 0
    [flip] = report["flips"]
    assert flip["job_id"] == "p4"
    assert (flip["before"]["label"], flip["after"]["label"]) == ("VIOLATING", "NEEDS_REVIEW")
    assert flip["from_the_change"] is True  # §4's effect changed and the label rests on §4
    assert calls == [] and await sql(api, "SELECT id FROM jobs WHERE policy_version = 'v1b'") == []
    [row] = await sql(
        api, "SELECT findings FROM labels WHERE policy_version = 'v1b' AND label = 'NEEDS_REVIEW'"
    )
    assert any(f["section"] == "§4" and f["status"] == "matched" for f in row["findings"])


async def test_a_shadow_job_for_an_edited_draft_is_skipped(api, worker):
    await labeled(api, worker, POSTING, CLEAN)
    await draft(api, "v2", V2)
    await api.post("/policies/drafts/v2/test", headers=as_("editor"))
    async with worker.pool.connection() as conn:
        running = await jobs.claim(conn, worker.thread_for)  # one job is running, one still queued
    await api.put("/policies/drafts/v2", json={"body": {**V2, "title": "Edited"}}, headers=as_("editor"))
    await worker.handle(running)
    rows = await sql(api, "SELECT status, last_error FROM jobs WHERE policy_version = 'v2'")
    assert [r["status"] for r in rows] == ["failed", "failed"]
    assert all("draft changed" in r["last_error"] for r in rows)
    assert await sql(api, "SELECT id FROM labels WHERE policy_version = 'v2'") == []


# ---------------------------------------------------------------- Publish


async def test_publish_needs_the_role_four_eyes_and_a_current_passing_test(api, worker):
    await labeled(api, worker, POSTING)
    await draft(api, "v2", V2)

    async def publish(user):
        return await api.post("/policies/drafts/v2/publish", headers=as_(user))

    assert (await publish("editor")).status_code == 403  # the role check
    assert (await publish("publisher_b")).json()["error"]["code"] == "test_outdated"  # never tested
    await api.post("/policies/drafts/v2/test", headers=as_("editor"))
    assert (await publish("publisher_b")).json()["error"]["code"] == "test_not_passed"  # not finished
    await drain(worker)
    edited = {**V2, "title": "Recruitment fraud policy (edited)"}
    await api.put("/policies/drafts/v2", json={"body": edited}, headers=as_("publisher_a"))  # pat edits
    assert (await publish("publisher_a")).json()["error"]["code"] == "four_eyes"
    assert (await publish("publisher_b")).json()["error"]["code"] == "test_outdated"  # edited after Test
    await run_draft_test(api, worker, "v2")
    published = await publish("publisher_b")
    assert published.status_code == 200, published.text
    versions = {v["name"]: v for v in (await api.get("/policies", headers=as_("viewer"))).json()}
    assert versions["v2"]["status"] == "live" and versions["v2"]["published_by"] == "sam"
    assert versions["v1"]["status"] == "retired"


async def test_publish_keeps_the_test_labels_and_relabels_the_rest(api, worker):
    await labeled(api, worker, POSTING, CLEAN, IMPERSONATION)
    await draft(api, "v2", V2)
    await run_draft_test(api, worker, "v2", limit=1)  # the newest posting only (p3)
    out = (await api.post("/policies/drafts/v2/publish", headers=as_("publisher_b"))).json()
    assert (out["mode"], out["labeled_by_test"], out["queued"], out["redecided"]) == ("full", 1, 2, 0)

    stale = await label_of(api, "p1")  # its v2 label isn't there yet
    assert stale["stale"] is True and stale["policy_version"] == "v1" and stale["relabel_status"] == "queued"
    assert (await label_of(api, "p3"))["policy_version"] == "v2"  # labeled by the Test

    w = (await api.get("/policies/v2/relabel", headers=as_("viewer"))).json()["relabel"]
    assert (w["kept_from_test"], w["relabeled"], w["waiting"], w["total"]) == (1, 0, 2, 3)

    await drain(worker)
    fresh = await label_of(api, "p1")
    assert fresh["stale"] is False and fresh["policy_version"] == "v2"
    progress = (await api.get("/policies/v2/relabel", headers=as_("viewer"))).json()
    assert progress["labels"] == 3 and progress["jobs"] == {"done": 2}
    assert progress["relabel"] == {
        "kept_from_test": 1,
        "relabeled": 2,
        "in_code": 0,
        "waiting": 0,
        "total": 3,
        "cost_usd": 0.0,
    }
    # a posting that arrives after Publish is new, not re-labeled
    await labeled(api, worker, HIGH_PAY)
    after = (await api.get("/policies/v2/relabel", headers=as_("viewer"))).json()
    assert after["new_postings"] == 1 and after["relabel"]["total"] == 3


async def test_a_test_of_the_whole_scope_leaves_publish_nothing_to_run(api, worker):
    await labeled(api, worker, POSTING, CLEAN, IMPERSONATION)
    await draft(api, "v2", V2)
    scope = (await api.get("/policies/v2", headers=as_("viewer"))).json()["relabel_scope"]
    assert scope == 3
    await run_draft_test(api, worker, "v2", limit=scope)
    out = (await api.post("/policies/drafts/v2/publish", headers=as_("publisher_b"))).json()
    assert (out["labeled_by_test"], out["queued"], out["redecided"]) == (3, 0, 0)
    assert "relabel_scope" not in (await api.get("/policies/v2", headers=as_("viewer"))).json()


async def test_an_effects_only_version_relabels_at_no_cost(api, worker, monkeypatch):
    await labeled(api, worker, POSTING, HIGH_PAY, CLEAN)
    monkeypatch.setattr("app.agent.llm.chat", lambda profile: 1 / 0)  # any model call would fail
    await draft(api, "v1b", effects_only())
    await run_draft_test(api, worker, "v1b", limit=1)
    out = (await api.post("/policies/drafts/v1b/publish", headers=as_("publisher_b"))).json()
    assert (out["mode"], out["queued"], out["redecided"], out["labeled_by_test"]) == ("redecide", 0, 2, 1)
    assert (await label_of(api, "p4"))["label"] == "NEEDS_REVIEW"
    progress = (await api.get("/policies/v1b/relabel", headers=as_("viewer"))).json()
    assert (
        progress["labels"] == 3 and progress["labels_without_a_model_call"] == 3 and progress["cost_usd"] == 0
    )


async def test_rollback_makes_the_old_labels_current_at_once(api, worker):
    await labeled(api, worker, POSTING)
    await draft(api, "v2", V2)
    await run_draft_test(api, worker, "v2")
    await api.post("/policies/drafts/v2/publish", headers=as_("publisher_b"))
    assert (await api.put("/policies/live", json={"name": "v1"}, headers=as_("editor"))).status_code == 403
    rolled = await api.put("/policies/live", json={"name": "v1"}, headers=as_("publisher_a"))
    assert rolled.json() == {"live": "v1", "retired": "v2"}
    out = await label_of(api, "p1")
    assert out["policy_version"] == "v1" and out["stale"] is False
    again = await api.put("/policies/live", json={"name": "v1"}, headers=as_("publisher_a"))
    assert again.json()["error"]["code"] == "not_retired"


async def test_a_new_version_that_disagrees_with_an_analyst_is_flagged(api, worker):
    await labeled(api, worker, POSTING)
    [label] = await sql(api, "SELECT id FROM labels")
    decision = {"label": "ALLOWED", "note": "Fee is refunded on day one."}
    await api.post(f"/ui/labels/{label['id']}/decision", json=decision, headers=as_("editor"))
    assert (await label_of(api, "p1"))["new_policy_disagrees"] is False  # decided under the live version

    await draft(api, "v2", V2)
    await run_draft_test(api, worker, "v2")
    await api.post("/policies/drafts/v2/publish", headers=as_("publisher_b"))
    out = await label_of(api, "p1")
    assert out["label"] == "ALLOWED" and out["decided_by"] == "analyst"  # the decision stays final
    assert out["model_label"] == "VIOLATING" and out["new_policy_disagrees"] is True


# ---------------------------------------------------------------- the version files


def test_the_version_files_change_what_they_say():
    v3 = policies.load_file(policies.POLICIES_DIR / "v3.yaml")
    v4 = policies.load_file(policies.POLICIES_DIR / "v4.yaml")
    assert [s["code"] for s in V2["sections"]] == ["§1", "§2", "§3", "§4", "§5", "§6"]
    assert {s["code"]: s["effect"] for s in V2["sections"]}["§6"] == "NEEDS_REVIEW"
    assert [c["where"] for c in policies.diff(V2, v3)] == ["§5.examples", "§5.screen", "§5.text"]
    assert [c["where"] for c in policies.diff(v3, v4)] == ["header.labels", "§4.effect"]
    assert policies.model_hash(v3) == policies.model_hash(v4)  # v4 re-labels at $0
    assert V2["screen_cut_off"] == v3["screen_cut_off"] == v4["screen_cut_off"] == V1["screen_cut_off"]


async def test_the_report_compares_with_the_parent_even_after_later_versions(api, worker):
    await labeled(api, worker, POSTING, HIGH_PAY)
    await draft(api, "v1b", effects_only())
    before = await run_draft_test(api, worker, "v1b")
    await api.post("/policies/drafts/v1b/publish", headers=as_("publisher_b"))
    await draft(api, "v1c", effects_only("VIOLATING"))  # back again: a later version
    await run_draft_test(api, worker, "v1c")
    await api.post("/policies/drafts/v1c/publish", headers=as_("publisher_b"))
    after = (await api.get("/policies/drafts/v1b/test", headers=as_("viewer"))).json()
    assert after["compared_with"] == "v1" and after["flips"] == before["flips"]


async def test_a_draft_whose_parent_is_no_longer_live_must_be_recreated(api, worker):
    await labeled(api, worker, POSTING)
    await draft(api, "v2", V2)
    await draft(api, "v1b", effects_only())
    await run_draft_test(api, worker, "v1b")
    await api.post("/policies/drafts/v1b/publish", headers=as_("publisher_b"))  # v1 is retired now
    response = await api.post("/policies/drafts/v2/test", headers=as_("editor"))
    assert response.status_code == 409 and response.json()["error"]["code"] == "parent_not_live"


def test_a_flip_is_from_the_change_only_if_it_involves_a_changed_section():
    from app.versions import _from_the_change

    def row(before, after, labels=("NEEDS_REVIEW", "NEEDS_REVIEW")):
        return {"live_sections": before, "sections": after, "live_label": labels[0], "label": labels[1]}

    assert _from_the_change(row(["§5"], ["§5", "§6"]), {"§6"})  # §6 appeared
    assert not _from_the_change(row([], ["§5"], ("ALLOWED", "NEEDS_REVIEW")), {"§6"})  # model variation
    assert _from_the_change(row(["§4"], ["§4"], ("VIOLATING", "NEEDS_REVIEW")), {"§4"})  # an effect change


async def test_submit_needs_a_passing_test_and_an_edit_clears_it(api, worker):
    await labeled(api, worker, POSTING)
    await draft(api, "v2", V2)

    async def submit(user="editor"):
        return await api.post("/policies/drafts/v2/submit", headers=as_(user))

    assert (await submit("viewer")).status_code == 403
    assert (await submit()).json()["error"]["code"] == "test_outdated"
    await run_draft_test(api, worker, "v2")
    done = (await submit()).json()
    assert done["submitted_by"] == "eddie" and done["submitted_at"]
    edited = {**V2, "title": "Recruitment fraud policy (edited)"}
    after_edit = (await api.put("/policies/drafts/v2", json={"body": edited}, headers=as_("editor"))).json()
    assert after_edit["submitted_by"] is None  # a publisher approves what they see


async def test_a_test_can_be_stopped(api, worker):
    await labeled(api, worker, POSTING, CLEAN, IMPERSONATION)
    await draft(api, "v2", V2)
    await api.post("/policies/drafts/v2/test", headers=as_("editor"))
    stopped = (await api.post("/policies/drafts/v2/test/stop", headers=as_("editor"))).json()
    assert stopped == {"version": "v2", "dropped": 3}
    assert await sql(api, "SELECT id FROM jobs WHERE policy_version = 'v2'") == []
    report = (await api.get("/policies/drafts/v2/test", headers=as_("viewer"))).json()
    assert report["labeled"] == 0 and not report["passed"]  # nothing labeled: nothing to publish on
    assert (await api.post("/policies/drafts/v2/test/stop", headers=as_("viewer"))).status_code == 403


async def test_two_versions_compared_side_by_side(api, worker):
    await labeled(api, worker, POSTING, CLEAN, IMPERSONATION)
    await draft(api, "v2", V2)
    await run_draft_test(api, worker, "v2")
    await api.post("/policies/drafts/v2/publish", headers=as_("publisher_b"))
    out = (await api.get("/ui/compare", params={"from": "v1", "to": "v2"}, headers=as_("viewer"))).json()
    assert (out["postings"], out["changed"], out["from_the_change"]) == (3, 1, 1)
    [changed] = [r for r in out["rows"] if r["changed"]]
    assert changed["job_id"] == "p3"
    assert changed["old"]["sections"] == ["§5"] and changed["new"]["sections"] == ["§5", "§6"]
    missing = await api.get("/ui/compare", params={"from": "v1", "to": "v9"}, headers=as_("viewer"))
    assert missing.status_code == 404


# ---------------------------------------------------------------- discarding a draft


async def test_a_draft_is_discarded_with_its_test_and_its_name_is_free_again(api, worker):
    await labeled(api, worker, POSTING, CLEAN)
    await draft(api, "v2", V2)
    await run_draft_test(api, worker, "v2")
    assert len(await sql(api, "SELECT id FROM labels WHERE policy_version = 'v2'")) == 2
    jobs_of_v2 = await sql(api, "SELECT thread_id FROM jobs WHERE policy_version = 'v2'")
    threads = [t["thread_id"] for t in jobs_of_v2]
    count = "SELECT count(*) AS n FROM checkpoints WHERE thread_id = ANY(%s)"
    assert (await sql(api, count, (threads,)))[0]["n"] > 0

    # an edit makes the Test's labels outdated, but they still go with the draft: the page counts them
    await api.put("/policies/drafts/v2", json={"body": effects_only()}, headers=as_("editor"))
    assert (await api.get("/policies/v2", headers=as_("viewer"))).json()["test_labels"] == 2

    assert (await api.delete("/policies/drafts/v2", headers=as_("viewer"))).status_code == 403
    out = await api.delete("/policies/drafts/v2", headers=as_("editor"))
    assert out.status_code == 200 and out.json() == {"discarded": "v2", "labels_deleted": 2}
    assert await sql(api, "SELECT id FROM labels WHERE policy_version = 'v2'") == []
    assert await sql(api, "SELECT id FROM jobs WHERE policy_version = 'v2'") == []
    assert (await sql(api, count, (threads,)))[0]["n"] == 0
    assert (await api.get("/policies/v2", headers=as_("viewer"))).status_code == 404
    assert (await draft(api, "v2", V2)).status_code == 201  # the name can be used again
    assert (await label_of(api, "p1"))["policy_version"] == "v1"  # the live labels are untouched


async def test_a_published_version_or_a_running_test_cannot_be_discarded(api, worker):
    published = await api.delete("/policies/drafts/v1", headers=as_("editor"))
    assert published.json()["error"]["code"] == "not_a_draft"
    await labeled(api, worker, POSTING)
    await draft(api, "v2", V2)
    await api.post("/policies/drafts/v2/test", headers=as_("editor"))
    await sql(api, "UPDATE jobs SET status = 'running' WHERE policy_version = 'v2'")
    refused = await api.delete("/policies/drafts/v2", headers=as_("editor"))
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "test_running"
