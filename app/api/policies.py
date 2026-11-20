"""The policy API: versions, drafts, Test, Publish, rollback and re-label progress.

Every step goes through here, so a new policy version needs no code change.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import policy as policies
from app import store, versions
from app.auth import EDIT, PUBLISH, VIEW, User, require

router = APIRouter(prefix="/policies", tags=["policies"])

NAME = r"^[a-z0-9][a-z0-9._-]{0,31}$"


class DraftIn(BaseModel):
    name: str = Field(pattern=NAME)
    body: dict | None = None  # the policy; omitted, a copy of the live version


class DraftEdit(BaseModel):
    body: dict


class LiveIn(BaseModel):
    name: str = Field(pattern=NAME)


def _conn(request: Request):
    return request.app.state.pool.connection()


def _summary(row: dict) -> dict:
    return {
        "name": row["name"],
        "status": row["status"],
        "parent": row["parent"],
        "author": row["author"],
        "edited_by": row["edited_by"],
        "published_by": row["published_by"],
        "published_at": row["published_at"],
        "content_hash": row["content_hash"],
        "model_hash": row["model_hash"],
        "tested": row["tested_hash"] == row["content_hash"],
        "submitted_by": row.get("submitted_by"),
        "submitted_at": row.get("submitted_at"),
        "created_at": row["created_at"],
    }


async def _run(call):
    """Turn a lifecycle refusal into the HTTP answer."""
    try:
        return await call
    except versions.Refused as refused:
        detail = refused.code if refused.detail is None else {"code": refused.code, "detail": refused.detail}
        raise HTTPException(refused.status, detail) from refused


@router.get("")
async def list_versions(request: Request, user: User = Depends(require(*VIEW))):
    async with _conn(request) as conn:
        rows = await (await conn.execute("SELECT * FROM policy_versions ORDER BY created_at")).fetchall()
    return [_summary(r) for r in rows]


@router.get("/{name}")
async def read_version(
    name: str, request: Request, diff: str | None = Query(None), user: User = Depends(require(*VIEW))
):
    """One version, its body, and (with ?diff=v1) what changed against another version."""
    async with _conn(request) as conn:
        row = await store.policy_version(conn, name)
        other = await store.policy_version(conn, diff) if diff else None
        if row is None or (diff and other is None):
            raise HTTPException(404, "not_found")
        out = {**_summary(row), "body": row["body"]}
        if row["status"] == "draft" and row["parent"]:
            # how many postings Publish would label again: a Test of that many leaves Publish nothing to run
            out["relabel_scope"] = await versions.relabel_scope(conn, row["parent"])
            # every label its Tests made, also for content it no longer has: discarding deletes them all
            out["test_labels"] = await versions.test_labels(conn, name)
    if other is not None:
        out["diff"] = {"against": diff, "changes": policies.diff(other["body"], row["body"])}
    return out


@router.post("/drafts", status_code=201)
async def create_draft(draft: DraftIn, request: Request, user: User = Depends(require(*EDIT))):
    async with _conn(request) as conn:
        body = draft.body or (await store.live_policy(conn))["body"]
        row = await _run(versions.create_draft(conn, draft.name, body, user.name))
    return _summary(row)


@router.put("/drafts/{name}")
async def edit_draft(name: str, edit: DraftEdit, request: Request, user: User = Depends(require(*EDIT))):
    async with _conn(request) as conn:
        row = await _run(versions.update_draft(conn, name, edit.body, user.name))
    return _summary(row)


@router.delete("/drafts/{name}")
async def discard_draft(name: str, request: Request, user: User = Depends(require(*EDIT))):
    """Delete a draft and its Test. Published versions can't be deleted."""
    async with _conn(request) as conn:
        return await _run(versions.discard_draft(conn, name))


@router.post("/drafts/{name}/test", status_code=202)
async def start_test(
    name: str,
    request: Request,
    limit: int = Query(versions.TEST_SAMPLE, ge=1, le=1000),
    user: User = Depends(require(*EDIT)),
):
    """Label recent postings under the draft in shadow. Read the flip report with GET."""
    async with _conn(request) as conn:
        return await _run(versions.start_test(conn, name, limit))


@router.get("/drafts/{name}/test")
async def test_report(name: str, request: Request, user: User = Depends(require(*VIEW))):
    async with _conn(request) as conn:
        return await _run(versions.test_report(conn, name))


@router.post("/drafts/{name}/test/stop")
async def stop_test(name: str, request: Request, user: User = Depends(require(*EDIT))):
    """Stop a running Test: postings not yet labeled are dropped."""
    async with _conn(request) as conn:
        return await _run(versions.stop_test(conn, name))


@router.post("/drafts/{name}/submit")
async def submit(name: str, request: Request, user: User = Depends(require(*EDIT))):
    """Mark the draft ready for a publisher (needs a passing Test of its current content)."""
    async with _conn(request) as conn:
        return _summary(await _run(versions.submit(conn, name, user.name)))


@router.post("/drafts/{name}/publish")
async def publish(name: str, request: Request, user: User = Depends(require(*PUBLISH))):
    async with _conn(request) as conn:
        return await _run(versions.publish(conn, name, user.name))


@router.put("/live")
async def rollback(live: LiveIn, request: Request, user: User = Depends(require(*PUBLISH))):
    """Make an older version live again."""
    async with _conn(request) as conn:
        return await _run(versions.rollback(conn, live.name))


@router.get("/{name}/relabel")
async def relabel_progress(name: str, request: Request, user: User = Depends(require(*VIEW))):
    async with _conn(request) as conn:
        return await _run(versions.relabel_progress(conn, name))
