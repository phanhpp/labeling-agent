"""Small helpers shared by the API and queue tests."""

from app import auth
from app import queue as jobs

POSTING = {
    "job_id": "p1",
    "title": "Assembler",
    "company_profile": "Craftline Kits, makers of furniture kits since 2015.",
    "description": "Before your first shift, pay the registration fee for your starter kit.",
}
CLEAN = {
    "job_id": "p2",
    "title": "Office Clerk",
    "company_profile": "Acme Supplies, a stationery wholesaler since 1990.",
    "description": "Answer phones and file records. Salary paid monthly, training provided.",
}


def as_(user: str) -> dict:
    """Headers for one of the demo users in app/auth.py."""
    return {"Authorization": f"Bearer {auth.demo_token(user)}"}


async def submit(api, *postings, user="marketplace"):
    for posting in postings:
        response = await api.post("/v1/postings", json=posting, headers=as_(user))
        assert response.status_code == 202, response.text


async def drain(worker) -> int:
    """Claim and run every job that is ready now. Returns how many ran."""
    ran = 0
    while True:
        async with worker.pool.connection() as conn:
            job = await jobs.claim(conn, worker.thread_for)
        if job is None:
            return ran
        await worker.handle(job)
        ran += 1


async def sql(api, query: str, params=()) -> list[dict]:
    async with api.app.state.pool.connection() as conn:
        cursor = await conn.execute(query, params)
        return await cursor.fetchall() if cursor.description else []
