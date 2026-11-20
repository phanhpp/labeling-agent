"""The live demo, only with DEMO_MODE=true: send real dataset postings in from the UI.

The UI plays the marketplace here (client "acme", the same intake path as POST /v1/postings/batch),
so the postings are labeled by the running worker exactly like any other. Analysts never submit
postings in production; this exists to watch the system work on real data during a demo.
"""

import random
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from app import demo, store
from app.api.intake import PostingIn
from app.auth import DEMO_USERS, EDIT, User, require

router = APIRouter(prefix="/demo", tags=["demo"])

CLIENT = DEMO_USERS["marketplace"].client_id


class LiveRunIn(BaseModel):
    n: int = Field(30, ge=demo.MIN_POSTINGS, le=demo.MAX_POSTINGS)
    mix: Literal["real", "more_fraud"] = "more_fraud"
    seed: int | None = None  # the same seed sends the same sample (minus postings already sent)


def _conn(request: Request):
    return request.app.state.pool.connection()


@router.post("/live-run", status_code=202)
async def live_run(run: LiveRunIn, request: Request, user: User = Depends(require(*EDIT))):
    """Send n random real postings (never the eval 400 or their copies, never one already sent) and
    record the dataset's label for each. Returns the batch to follow with GET /ui/batches/{id}."""
    if not demo.enabled():
        raise HTTPException(404, "not_found")
    if not demo.dataset_ready():
        raise HTTPException(409, "dataset_missing")
    seed = run.seed if run.seed is not None else random.randrange(1_000_000)
    async with _conn(request) as conn:
        await _record_dataset_labels(conn)  # postings sent before (make demo) get theirs too
        sent = await (
            await conn.execute("SELECT job_id, raw FROM postings WHERE client_id = %s", (CLIENT,))
        ).fetchall()
        sent_texts = frozenset(demo.ad_text(r["raw"]) for r in sent)
        # Twice as many as needed: a row the intake would refuse is skipped, not sent.
        candidates = demo.sample(
            demo.pool(), run.n * 2, demo.MIXES[run.mix], seed, {r["job_id"] for r in sent}, sent_texts
        )
        batch_id = await store.new_batch(conn, CLIENT)
        picked = fraud = 0
        for row in _keep_mix(candidates, run.n, demo.MIXES[run.mix], seed):
            try:
                posting = PostingIn.model_validate({k: v for k, v in row.items() if k != "fraudulent"})
            except ValidationError:
                continue
            result = await store.submit_posting(conn, CLIENT, posting.model_dump(), batch_id)
            if result["status"] != "queued":
                continue
            await store.save_dataset_label(conn, result["posting_id"], row["fraudulent"] == "1")
            picked += 1
            fraud += row["fraudulent"] == "1"
            if picked == run.n:
                break
    return {"batch_id": batch_id, "postings": picked, "fraud": fraud, "seed": seed, "mix": run.mix}


@router.post("/dataset-labels")
async def record_dataset_labels(request: Request, user: User = Depends(require(*EDIT))):
    """Save the dataset's answer for every posting the app holds that is a dataset row (make demo calls
    this after sending its 100). Costs nothing, calls no model, changes no label."""
    if not demo.enabled():
        raise HTTPException(404, "not_found")
    if not demo.dataset_ready():
        raise HTTPException(409, "dataset_missing")
    async with _conn(request) as conn:
        return {"recorded": await _record_dataset_labels(conn)}


async def _record_dataset_labels(conn) -> int:
    rows = await (
        await conn.execute(
            "SELECT p.id, p.raw FROM postings p LEFT JOIN dataset_labels d ON d.posting_id = p.id"
            " WHERE d.posting_id IS NULL"
        )
    ).fetchall()
    recorded = 0
    for row in rows:
        fraudulent = demo.dataset_label_for(row["raw"])
        if fraudulent is not None:
            await store.save_dataset_label(conn, row["id"], fraudulent)
            recorded += 1
    return recorded


def _keep_mix(candidates: list[dict], n: int, share: float | None, seed: int) -> list[dict]:
    """Order the doubled sample so its first n keep the asked-for share of fraud (shuffled, so fraud
    isn't sent first); the rest are spares for rows the intake refuses."""
    if share is None:
        return candidates
    fraud = [c for c in candidates if c["fraudulent"] == "1"]
    legit = [c for c in candidates if c["fraudulent"] != "1"]
    k = round(n * share)
    head = fraud[:k] + legit[: n - k]
    random.Random(seed).shuffle(head)
    return head + fraud[k:] + legit[n - k :]
