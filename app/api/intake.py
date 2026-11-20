"""The marketplace API: submit postings, read labels. A client sees only its own postings."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from app import store
from app.auth import MARKETPLACE, User, require

router = APIRouter(prefix="/v1", tags=["intake"])

MAX_BATCH = 500


def _flag(value):
    """Accept 0/1 and true/false as well as the dataset's "0"/"1"; store "0"/"1"."""
    if isinstance(value, bool | int):
        return "1" if value else "0"
    return value


Flag = Annotated[Literal["0", "1"], BeforeValidator(_flag)]
Short = Annotated[str, Field(max_length=500)]
Long = Annotated[str, Field(max_length=20_000)]  # the longest dataset field is about 15,000 characters


class PostingIn(BaseModel):
    """A posting as the marketplace sends it: the dataset's columns, nothing else."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    title: str = Field(min_length=1, max_length=500)
    location: Short = ""
    department: Short = ""
    salary_range: Short = ""
    company_profile: Long = ""
    description: Long = ""
    requirements: Long = ""
    benefits: Long = ""
    telecommuting: Flag = "0"
    has_company_logo: Flag = "0"
    has_questions: Flag = "0"
    employment_type: Literal["", "Full-time", "Part-time", "Contract", "Temporary", "Other"] = ""
    required_experience: Literal[
        "",
        "Internship",
        "Entry level",
        "Associate",
        "Mid-Senior level",
        "Director",
        "Executive",
        "Not Applicable",
    ] = ""
    required_education: Short = ""
    industry: Short = ""
    function: Short = ""


class BatchIn(BaseModel):
    # Items are checked one by one in the endpoint, so one bad item doesn't reject the batch.
    postings: list[dict] = Field(min_length=1, max_length=MAX_BATCH)


def _conn(request: Request):
    return request.app.state.pool.connection()


@router.post("/postings", status_code=202)
async def submit(posting: PostingIn, request: Request, user: User = Depends(require(*MARKETPLACE))):
    """Queue one posting. The same job id with the same content returns the existing job
    (status "duplicate"); with different content, 409."""
    async with _conn(request) as conn:
        result = await store.submit_posting(conn, user.client_id, posting.model_dump())
    if result["status"] == "conflict":
        raise HTTPException(409, "job_id_conflict")
    return {"job_id": result["job_id"], "status": result["status"]}


@router.post("/postings/batch", status_code=202)
async def submit_batch(batch: BatchIn, request: Request, user: User = Depends(require(*MARKETPLACE))):
    """Queue up to 500 postings. Each item is accepted or rejected with a reason on its own."""
    items = []
    async with _conn(request) as conn:
        batch_id = await store.new_batch(conn, user.client_id)
        for index, raw in enumerate(batch.postings):
            try:
                posting = PostingIn.model_validate(raw)
            except ValidationError as error:
                reasons = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in error.errors()]
                items.append({"index": index, "status": "rejected", "reason": "invalid", "details": reasons})
                continue
            result = await store.submit_posting(conn, user.client_id, posting.model_dump(), batch_id)
            if result["status"] == "conflict":
                items.append(
                    {"index": index, "job_id": posting.job_id, "status": "rejected", "reason": "conflict"}
                )
            else:
                items.append({"index": index, "job_id": posting.job_id, "status": result["status"]})
    accepted = sum(item["status"] != "rejected" for item in items)
    return {"batch_id": batch_id, "accepted": accepted, "rejected": len(items) - accepted, "items": items}


@router.get("/postings/{job_id}/label")
async def label(job_id: str, request: Request, user: User = Depends(require(*MARKETPLACE))):
    """The posting's current label (analyst decision, else the live version's, else an older one
    marked stale), or 202 {"status": "queued"} until the first label exists."""
    async with _conn(request) as conn:
        out = await store.read_label(conn, user.client_id, job_id)
    if out is None:
        raise HTTPException(404, "not_found")
    if out["status"] == "queued":
        return JSONResponse(out, 202)
    return out


@router.get("/batches/{batch_id}")
async def batch(batch_id: int, request: Request, user: User = Depends(require(*MARKETPLACE))):
    async with _conn(request) as conn:
        progress = await store.batch_progress(conn, batch_id, user.client_id)
    if progress is None:
        raise HTTPException(404, "not_found")
    return progress
