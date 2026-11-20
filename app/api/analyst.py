"""The analyst API behind the UI: browse labels, read one decision and its steps, record a decision."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import store
from app.auth import EDIT, VIEW, User, require

router = APIRouter(prefix="/ui", tags=["analyst"])

# Node outputs left out of the steps view: the posting text, which the page already shows.
_BULKY = {"raw", "cleaned", "model_input"}


def _conn(request: Request):
    return request.app.state.pool.connection()


@router.get("/labels")
async def browse(
    request: Request,
    label: Literal["VIOLATING", "ALLOWED", "NEEDS_REVIEW"] | None = None,
    section: str | None = None,
    reason: str | None = None,
    job_id: str | None = None,
    version: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(require(*VIEW)),
):
    """Labels under one policy version (the live one by default), newest first, one per posting."""
    async with _conn(request) as conn:
        version = version or (await store.live_policy(conn))["name"]
        filters = {"version": version, "label": label, "section": section, "reason": reason, "job_id": job_id}
        result = await store.browse_labels(conn, filters, limit, offset)
    return {"version": version, **result}


@router.get("/labels/{label_id}")
async def detail(label_id: int, request: Request, user: User = Depends(require(*VIEW))):
    async with _conn(request) as conn:
        out = await store.label_detail(conn, label_id)
    if out is None:
        raise HTTPException(404, "not_found")
    return out


@router.get("/postings/{posting_id}/steps")
async def steps(posting_id: int, request: Request, user: User = Depends(require(*VIEW))):
    """What each node of the posting's latest run produced, read from its LangGraph checkpoints.
    Works while the run is in progress (the UI polls) and for past runs, until pruned after 7 days."""
    async with _conn(request) as conn:
        job = await store.latest_job(conn, posting_id)
    if job is None:
        raise HTTPException(404, "not_found")
    out = {"posting_id": posting_id, "job": job, "steps": []}
    if job["thread_id"] is None or job["checkpoints_pruned"]:
        return out
    config = {"configurable": {"thread_id": job["thread_id"]}}
    history = [snapshot async for snapshot in request.app.state.graph.aget_state_history(config)]
    for snapshot in reversed(history):  # oldest first
        for task in snapshot.tasks:
            if task.name == "__start__":
                continue
            if task.result is not None:
                status = "done"
            elif task.error is not None:
                status = "error"
            else:
                status = "running" if job["status"] == "running" else "stopped"
            output = {k: v for k, v in (task.result or {}).items() if k not in _BULKY}
            out["steps"].append(
                {"node": task.name, "status": status, "started_at": snapshot.created_at, "output": output}
            )
    return out


class DecisionIn(BaseModel):
    label: Literal["VIOLATING", "ALLOWED", "NEEDS_REVIEW"]
    note: str = Field("", max_length=2000)


@router.post("/labels/{label_id}/decision", status_code=201)
async def decide(label_id: int, decision: DecisionIn, request: Request, user: User = Depends(require(*EDIT))):
    """The analyst's decision on a posting. It is final: reads return it over any model label."""
    async with _conn(request) as conn:
        label = await (
            await conn.execute("SELECT posting_id FROM labels WHERE id = %s", (label_id,))
        ).fetchone()
        if label is None:
            raise HTTPException(404, "not_found")
        return await store.record_decision(
            conn, label["posting_id"], decision.label, decision.note, user.name
        )
