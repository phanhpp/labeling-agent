"""The analyst API: browse, one decision, the step timeline, analyst decisions and the read rule."""

import asyncio

from psycopg.types.json import Jsonb

from app import policy as policies
from app import queue as jobs
from app import store
from tests.helpers import CLEAN, POSTING, as_, drain, sql, submit

V1 = policies.load_file(policies.POLICIES_DIR / "v1.yaml")


async def _labeled(api, worker):
    await submit(api, POSTING, CLEAN)
    await drain(worker)
    rows = await sql(api, "SELECT l.id, p.job_id FROM labels l JOIN postings p ON p.id = l.posting_id")
    return {r["job_id"]: r["id"] for r in rows}


async def test_browse_lists_one_row_per_posting_with_counts_for_the_chips(api, worker):
    await _labeled(api, worker)
    out = (await api.get("/ui/labels", headers=as_("viewer"))).json()
    assert out["version"] == "v1" and out["total"] == 2
    assert out["counts"] == {"label": {"VIOLATING": 1, "ALLOWED": 1}, "section": {"§1": 1}}
    assert {i["job_id"] for i in out["items"]} == {"p1", "p2"}


async def test_browse_filters_by_label_section_and_job_id(api, worker):
    await _labeled(api, worker)

    async def job_ids(**params):
        out = (await api.get("/ui/labels", params=params, headers=as_("viewer"))).json()
        return [i["job_id"] for i in out["items"]]

    assert await job_ids(label="VIOLATING") == ["p1"]
    assert await job_ids(section="§1") == ["p1"]
    assert await job_ids(job_id="p2") == ["p2"]
    assert await job_ids(label="NEEDS_REVIEW") == []
    assert (await api.get("/ui/labels", params={"label": "MAYBE"}, headers=as_("viewer"))).status_code == 422


async def test_one_decision_has_what_the_page_shows(api, worker):
    ids = await _labeled(api, worker)
    out = (await api.get(f"/ui/labels/{ids['p1']}", headers=as_("viewer"))).json()
    assert out["label"] == "VIOLATING" and out["job_id"] == "p1"
    assert out["cleaned"]["description"] == POSTING["description"]  # quote positions point into this
    assert [f["section"] for f in out["findings"]] == [s["code"] for s in V1["sections"]]
    assert out["facts"]["empty_fields"]
    assert [h["policy_version"] for h in out["history"]] == ["v1"]
    assert out["job"]["status"] == "done"
    assert (await api.get("/ui/labels/999", headers=as_("viewer"))).status_code == 404


async def test_the_steps_of_a_finished_run_come_from_its_checkpoints(api, worker):
    await _labeled(api, worker)
    [posting] = await sql(api, "SELECT id FROM postings WHERE job_id = 'p1'")
    out = (await api.get(f"/ui/postings/{posting['id']}/steps", headers=as_("viewer"))).json()
    assert [(s["node"], s["status"]) for s in out["steps"]] == [
        (node, "done") for node in ("clean", "cache", "screen", "escalate", "check", "decide")
    ]
    clean, *_, decide = out["steps"]
    assert "cleaned" not in clean["output"] and "facts" in clean["output"]  # the text isn't repeated
    assert decide["output"]["decision"]["label"] == "VIOLATING"


async def test_the_steps_show_a_run_in_progress(api, worker, monkeypatch):
    release = asyncio.Event()

    class SlowChat:
        async def ainvoke(self, messages):
            await release.wait()
            raise ConnectionError("stopped for the test")

    monkeypatch.setattr("app.agent.llm.chat", lambda profile: SlowChat())
    await submit(api, POSTING)
    async with worker.pool.connection() as conn:
        job = await jobs.claim(conn, worker.thread_for)
    run = asyncio.create_task(worker.handle(job))
    try:
        for _ in range(300):  # the UI polls like this; up to 15 s, as a CI runner can be slow
            steps = (await api.get(f"/ui/postings/{job['posting_id']}/steps", headers=as_("viewer"))).json()
            if steps["steps"] and steps["steps"][-1]["node"] == "escalate":
                break
            await asyncio.sleep(0.05)
        assert steps["job"]["status"] == "running"
        assert [(s["node"], s["status"]) for s in steps["steps"]][-2:] == [
            ("screen", "done"),
            ("escalate", "running"),
        ]
    finally:
        release.set()
        await run


async def test_an_analyst_decision_is_final_for_reads(api, worker):
    ids = await _labeled(api, worker)
    decision = {"label": "ALLOWED"}
    response = await api.post(f"/ui/labels/{ids['p1']}/decision", json=decision, headers=as_("editor"))
    assert response.status_code == 201
    assert response.json()["analyst"] == "eddie"  # who and when are kept
    out = (await api.get("/v1/postings/p1/label", headers=as_("marketplace"))).json()
    assert out["label"] == "ALLOWED" and out["decided_by"] == "analyst"
    assert out["model_label"] == "VIOLATING" and "analyst_note" not in out  # a label only, no free text


async def test_after_a_new_version_goes_live_the_old_label_is_returned_as_stale(api, worker):
    await _labeled(api, worker)
    body = {**V1, "version": "v2"}
    await sql(api, "UPDATE policy_versions SET status = 'retired' WHERE name = 'v1'")
    await sql(
        api,
        "INSERT INTO policy_versions (name, status, parent, body, content_hash, model_hash, author)"
        " VALUES ('v2', 'live', 'v1', %s, 'h2', 'm2', 'test')",
        (Jsonb(body),),
    )
    out = (await api.get("/v1/postings/p1/label", headers=as_("marketplace"))).json()
    assert out["stale"] is True and out["policy_version"] == "v1" and out["live_policy_version"] == "v2"
    assert out["relabel_status"] == "not_planned"

    [posting] = await sql(api, "SELECT id FROM postings WHERE job_id = 'p1'")
    async with api.app.state.pool.connection() as conn:
        await store.enqueue(conn, posting["id"], "v2", "h2", "backfill")
    out = (await api.get("/v1/postings/p1/label", headers=as_("marketplace"))).json()
    assert out["relabel_status"] == "queued"


async def test_each_row_carries_its_policy_match_and_one_line_of_evidence(api, worker):
    await _labeled(api, worker)
    rows = {i["job_id"]: i for i in (await api.get("/ui/labels", headers=as_("viewer"))).json()["items"]}
    fee = rows["p1"]
    assert [m["section"] for m in fee["policy_match"]] == ["§1"]
    assert fee["policy_match"][0]["status"] == "matched" and fee["policy_match"][0]["quotes"]
    assert fee["evidence_preview"]["section"] == "§1"
    assert fee["evidence_preview"]["text"] in POSTING["description"]
    assert rows["p2"]["policy_match"] == [] and rows["p2"]["evidence_preview"] is None


def test_evidence_preview_falls_back_to_empty_fields():
    from app.store import evidence_preview, policy_match

    findings = [
        {"section": "§1", "status": "not_matched", "quotes": [], "missing_fields": [], "reasoning": ""},
        {
            "section": "§5",
            "status": "matched",
            "quotes": [],
            "missing_fields": ["company_profile"],
            "reasoning": "r",
        },
        {
            "section": "§4",
            "status": "unsure",
            "quotes": [{"text": "x"}],
            "missing_fields": [],
            "reasoning": "",
        },
    ]
    match = policy_match(findings)
    assert [m["section"] for m in match] == ["§5", "§4"]  # matched first, then unsure
    assert evidence_preview(match) == {"section": "§4", "text": "x"}  # a quote beats empty fields
    assert evidence_preview(match[:1]) == {"section": "§5", "missing": ["company_profile"]}


async def test_the_decision_page_gets_the_marketplace_answer(api, worker):
    ids = await _labeled(api, worker)
    out = (await api.get(f"/ui/labels/{ids['p1']}", headers=as_("viewer"))).json()
    marketplace = (await api.get("/v1/postings/p1/label", headers=as_("marketplace"))).json()
    assert out["api_answer"] == marketplace


async def test_the_list_keeps_the_same_order_under_every_policy_version(api, worker):
    """Newest postings first, by arrival, whatever order each version's labels were made in."""
    third = {"job_id": "p3", "title": "Courier", "description": "Deliver parcels around town. Paid hourly."}
    await submit(api, POSTING, CLEAN, third)
    await drain(worker)
    v2 = policies.load_file(policies.POLICIES_DIR / "v2.yaml")
    await api.post("/policies/drafts", json={"name": "v2", "body": v2}, headers=as_("editor"))
    # the Test labels only the oldest posting first, so v2's labels are made in another order than v1's
    await sql(api, "UPDATE postings SET created_at = created_at - interval '1 day' WHERE job_id = 'p1'")
    await api.post("/policies/drafts/v2/test", params={"limit": 3}, headers=as_("editor"))
    await drain(worker)
    await api.post("/policies/drafts/v2/publish", headers=as_("publisher_b"))
    await drain(worker)

    def order(out):
        return [row["job_id"] for row in out["items"]]

    under_v1 = (await api.get("/ui/labels?version=v1", headers=as_("viewer"))).json()
    under_v2 = (await api.get("/ui/labels?version=v2", headers=as_("viewer"))).json()
    assert order(under_v1) == order(under_v2) == ["p3", "p2", "p1"]
