"""The live demo: sending real postings from the UI, following the run, comparing with the dataset."""

import random
import re
from pathlib import Path

import pytest

from app import demo
from tests.helpers import POSTING, as_, drain, sql, submit

ROOT = Path(__file__).resolve().parents[2]


def rows(n_fraud: int, n_legit: int) -> list[dict]:
    """Dataset-shaped rows: fraud ones ask for a starter-kit fee, so the fake model flags them (§1)."""
    out = []
    for i in range(n_fraud):
        out.append(
            {
                "job_id": f"f{i}",
                "title": "Home assembler",
                "company_profile": "Kits Ltd makes kits.",
                "description": f"Pay the registration fee for your starter kit ({i}).",
                "fraudulent": "1",
            }
        )
    for i in range(n_legit):
        out.append(
            {
                "job_id": f"l{i}",
                "title": "Office clerk",
                "company_profile": "Acme Supplies, since 1990.",
                "description": f"File records and answer phones ({i}). Salary paid monthly.",
                "fraudulent": "0",
            }
        )
    return out


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setattr(demo, "dataset_ready", lambda: True)
    monkeypatch.setattr(demo, "pool", lambda: tuple(rows(40, 160)))
    demo._by_job_id.cache_clear()  # it caches the pool by job id
    yield
    demo._by_job_id.cache_clear()


async def send(api, n=10, mix="more_fraud", user="editor", **extra):
    return await api.post("/demo/live-run", json={"n": n, "mix": mix, **extra}, headers=as_(user))


# ---------------------------------------------------------------- the sample


def test_the_pool_never_holds_an_eval_posting_or_a_copy():
    splits = {"eval": {"ids": ["1", "2"]}, "excluded_copies": ["3"]}
    pool = demo.outside_eval([{"job_id": str(i)} for i in range(1, 6)], splits)
    assert [r["job_id"] for r in pool] == ["4", "5"]


def test_a_sample_has_the_fraud_share_skips_sent_postings_and_repeats_with_its_seed():
    pool = rows(40, 160)
    picked = demo.sample(pool, 20, 0.25, seed=3, skip={"f0", "l0"})
    assert len(picked) == 20 and sum(r["fraudulent"] == "1" for r in picked) == 5
    assert not {"f0", "l0"} & {r["job_id"] for r in picked}
    assert picked == demo.sample(pool, 20, 0.25, seed=3, skip={"f0", "l0"})
    real = demo.sample(pool, 50, None, seed=3, skip=set())
    assert len(real) == 50 and real == random.Random(3).sample(pool, 50)  # a plain random sample


def test_a_sample_never_repeats_an_ad_already_sent_or_twice():
    """The dataset has reposts: the same ad under different job ids."""
    pool = rows(0, 10)
    repost = {**pool[3], "job_id": "l3-again"}
    picked = demo.sample([*pool, repost], 20, None, seed=1, skip=set(), skip_texts=frozenset())
    assert len(picked) == 10 and "l3-again" not in {r["job_id"] for r in picked}
    sent = frozenset({demo.ad_text(pool[0])})
    assert pool[0] not in demo.sample(pool, 20, None, seed=1, skip=set(), skip_texts=sent)


# ---------------------------------------------------------------- the endpoint


async def test_the_live_run_is_off_unless_demo_mode(api, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert (await send(api)).status_code == 404
    health = (await api.get("/health")).json()
    assert health["demo"]["enabled"] is False


async def test_the_live_run_needs_the_dataset_and_an_editor(api, demo_on, monkeypatch):
    assert (await send(api, user="viewer")).status_code == 403
    assert (await send(api, user="marketplace")).status_code == 403
    assert (await send(api, n=9)).status_code == 422 and (await send(api, n=101)).status_code == 422
    monkeypatch.setattr(demo, "dataset_ready", lambda: False)
    assert (await send(api)).json()["error"] == "dataset_missing"


async def test_a_live_run_sends_postings_like_a_marketplace_and_records_the_dataset_label(
    api, worker, demo_on
):
    out = await send(api, n=20, seed=11)
    assert out.status_code == 202, out.text
    run = out.json()
    assert (run["postings"], run["fraud"], run["seed"]) == (20, 5, 11)
    posted = await sql(api, "SELECT p.client_id, j.queue FROM postings p JOIN jobs j ON j.posting_id = p.id")
    assert len(posted) == 20 and {(p["client_id"], p["queue"]) for p in posted} == {("acme", "live")}
    assert len(await sql(api, "SELECT 1 FROM dataset_labels")) == 20

    waiting = (await api.get(f"/ui/batches/{run['batch_id']}", headers=as_("viewer"))).json()
    assert (waiting["postings"], waiting["labeled"], waiting["waiting"]) == (20, 0, 20)

    await drain(worker)
    done = (await api.get(f"/ui/batches/{run['batch_id']}", headers=as_("viewer"))).json()
    assert (done["labeled"], done["waiting"]) == (20, 0)
    assert sum(done["labels"].values()) == 20
    assert done["dataset"] == {"fraud": 5, "caught": 5, "false_alarms": 0}  # the fake model flags the fee

    # a second run never sends the same posting twice
    again = (await send(api, n=20, seed=11)).json()
    assert again["postings"] == 20
    assert len(await sql(api, "SELECT DISTINCT job_id FROM postings")) == 40


async def test_the_list_scopes_to_a_run_and_compares_with_the_dataset(api, worker, demo_on):
    first = (await send(api, n=10, seed=1)).json()
    await send(api, n=10, seed=2)
    await drain(worker)

    scoped = (await api.get(f"/ui/labels?batch={first['batch_id']}", headers=as_("viewer"))).json()
    assert scoped["total"] == 10 and sum(scoped["counts"]["label"].values()) == 10
    assert "dataset" not in scoped["items"][0]  # off by default: the list looks like production

    compared = (await api.get("/ui/labels?compare=true&limit=200", headers=as_("viewer"))).json()
    assert {row["dataset"] for row in compared["items"]} == {"fraud", "legitimate"}
    assert compared["dataset"]["with_dataset"] == 20 and compared["dataset"]["false_alarms"] == 0
    assert compared["dataset"]["caught"] == compared["dataset"]["fraud"]

    # an analyst can't see which ones disagree until one does: flip a legitimate one's label
    await sql(
        api,
        "UPDATE labels SET label = 'VIOLATING' WHERE posting_id = (SELECT p.id FROM postings p"
        " JOIN dataset_labels d ON d.posting_id = p.id WHERE NOT d.fraudulent LIMIT 1)",
    )
    disagree = (await api.get("/ui/labels?disagree=true", headers=as_("viewer"))).json()
    assert disagree["total"] == 1 and disagree["items"][0]["dataset"] == "legitimate"

    label_id = disagree["items"][0]["id"]
    assert (await api.get(f"/ui/labels/{label_id}", headers=as_("viewer"))).json()["dataset"] == "legitimate"


def test_the_agent_and_the_worker_never_read_the_dataset_label():
    """The label must come from the policy, never from the dataset's answer."""
    code = [
        *sorted((ROOT / "app" / "agent").glob("*.py")),
        ROOT / "app" / "worker.py",
        ROOT / "app" / "queue.py",
    ]
    readers = [p.name for p in code if re.search(r"dataset_labels|fraudulent", p.read_text())]
    assert readers == []


async def test_postings_sent_before_get_their_dataset_label_too(api, worker, demo_on):
    """make demo sends through the marketplace path, which saves no dataset label; this fills them in,
    but only for a real dataset row: same job id and the same text."""
    dataset_row = {k: v for k, v in rows(1, 0)[0].items() if k != "fraudulent"}
    changed = {**{k: v for k, v in rows(0, 1)[0].items() if k != "fraudulent"}, "description": "Edited text."}
    await submit(api, dataset_row, changed, POSTING)  # POSTING (p1) isn't in the dataset at all
    assert (await api.post("/demo/dataset-labels", headers=as_("viewer"))).status_code == 403
    out = await api.post("/demo/dataset-labels", headers=as_("editor"))
    assert out.json() == {"recorded": 1}
    saved = await sql(
        api, "SELECT p.job_id, d.fraudulent FROM dataset_labels d JOIN postings p ON p.id = d.posting_id"
    )
    assert saved == [{"job_id": "f0", "fraudulent": True}]
    assert (await api.post("/demo/dataset-labels", headers=as_("editor"))).json() == {"recorded": 0}
