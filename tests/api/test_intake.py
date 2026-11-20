"""The marketplace API: submit, idempotency, batches, and reading a label."""

from tests.helpers import CLEAN, POSTING, as_, drain, sql, submit


async def test_a_posting_is_saved_and_queued_under_the_live_version(api):
    response = await api.post("/v1/postings", json=POSTING, headers=as_("marketplace"))
    assert response.status_code == 202
    assert response.json() == {"job_id": "p1", "status": "queued"}
    [job] = await sql(api, "SELECT policy_version, queue, status FROM jobs")
    assert job == {"policy_version": "v1", "queue": "live", "status": "queued"}


async def test_the_same_posting_twice_is_a_duplicate_and_queues_nothing_new(api):
    await submit(api, POSTING)
    again = await api.post("/v1/postings", json=POSTING, headers=as_("marketplace"))
    assert again.status_code == 202 and again.json()["status"] == "duplicate"
    assert len(await sql(api, "SELECT id FROM jobs")) == 1


async def test_the_same_job_id_with_different_content_is_a_conflict(api):
    await submit(api, POSTING)
    changed = await api.post("/v1/postings", json={**POSTING, "title": "Other"}, headers=as_("marketplace"))
    assert changed.status_code == 409
    assert changed.json()["error"] == "job_id_conflict"


async def test_two_clients_may_use_the_same_job_id(api):
    await submit(api, POSTING)
    await submit(api, {**POSTING, "title": "Theirs"}, user="marketplace_b")
    assert len(await sql(api, "SELECT id FROM postings")) == 2


async def test_flags_are_stored_as_the_dataset_writes_them(api):
    await submit(api, {**POSTING, "has_company_logo": 0, "telecommuting": True})
    [row] = await sql(api, "SELECT raw FROM postings")
    assert row["raw"]["has_company_logo"] == "0" and row["raw"]["telecommuting"] == "1"


async def test_invalid_postings_are_refused_and_never_queued(api):
    cases = [
        {k: v for k, v in POSTING.items() if k != "title"},  # required field missing
        {**POSTING, "fraudulent": "1"},  # a field that isn't in the schema
        {**POSTING, "description": "x" * 20_001},  # too long
        {**POSTING, "employment_type": "Gig"},  # not an allowed value
        {**POSTING, "job_id": "has spaces"},  # job ids are plain tokens
    ]
    for case in cases:
        response = await api.post("/v1/postings", json=case, headers=as_("marketplace"))
        assert response.status_code == 422, case
        assert response.json()["error"] == "invalid_request"
    assert await sql(api, "SELECT id FROM postings") == []


async def test_a_batch_takes_each_item_on_its_own(api):
    await submit(api, POSTING)
    items = [
        CLEAN,  # accepted
        {"job_id": "bad"},  # no title: rejected
        {**POSTING, "title": "Changed"},  # conflict with p1: rejected
        POSTING,  # duplicate of p1: accepted, nothing new queued
    ]
    response = await api.post("/v1/postings/batch", json={"postings": items}, headers=as_("marketplace"))
    assert response.status_code == 202
    out = response.json()
    assert (out["accepted"], out["rejected"]) == (2, 2)
    assert [i["status"] for i in out["items"]] == ["queued", "rejected", "rejected", "duplicate"]
    assert out["items"][1]["details"] == [{"loc": ["title"], "msg": "Field required"}]
    assert out["items"][2]["reason"] == "conflict"

    progress = await api.get(f"/v1/batches/{out['batch_id']}", headers=as_("marketplace"))
    assert progress.json() == {"batch_id": out["batch_id"], "total": 1, "queued": 1}


async def test_a_batch_over_500_is_refused(api):
    many = [{**CLEAN, "job_id": f"j{i}"} for i in range(501)]
    response = await api.post("/v1/postings/batch", json={"postings": many}, headers=as_("marketplace"))
    assert response.status_code == 422
    assert await sql(api, "SELECT id FROM postings") == []


async def test_another_clients_batch_is_not_found(api):
    response = await api.post("/v1/postings/batch", json={"postings": [CLEAN]}, headers=as_("marketplace"))
    batch_id = response.json()["batch_id"]
    assert (await api.get(f"/v1/batches/{batch_id}", headers=as_("marketplace_b"))).status_code == 404


async def test_the_label_is_202_queued_until_it_exists(api):
    await submit(api, POSTING)
    response = await api.get("/v1/postings/p1/label", headers=as_("marketplace"))
    assert response.status_code == 202
    assert response.json() == {"job_id": "p1", "status": "queued"}


async def test_the_label_is_the_briefs_output_once_labeled(api, worker):
    await submit(api, POSTING)
    await drain(worker)
    response = await api.get("/v1/postings/p1/label", headers=as_("marketplace"))
    assert response.status_code == 200
    out = response.json()
    # The brief's seven fields first, then what explains them.
    assert out["label"] == "VIOLATING" and out["policy_sections"] == ["§1"]
    assert out["evidence"] and all(isinstance(q, str) for q in out["evidence"])
    assert out["rationale"] and 0 <= out["confidence"] <= 1 and out["policy_version"] == "v1"
    assert out["job_id"] == "p1"
    assert out["decided_by"] == "model" and out["stale"] is False
    span = out["evidence_spans"][0]
    assert POSTING[span["field"]][span["start"] : span["end"]] == span["text"]
    assert out["model_version"].startswith("fake;")


async def test_an_unknown_or_other_clients_posting_is_not_found(api):
    await submit(api, POSTING)
    assert (await api.get("/v1/postings/nope/label", headers=as_("marketplace"))).status_code == 404
    other = await api.get("/v1/postings/p1/label", headers=as_("marketplace_b"))
    assert other.status_code == 404  # 404, not 403: it doesn't reveal that the id exists
