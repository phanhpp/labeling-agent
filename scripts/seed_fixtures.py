"""Seed a running stack with the UI fixtures, through the API like any client.

    tests/fixtures/postings.jsonl  14 postings: 6 hand-written cases (a fee, unrealistic pay,
                                   impersonation, an injection, an empty profile with a logo, literal
                                   <script> text) and 8 dev postings (the dataset is CC0)

It submits them, waits for their labels, records one analyst decision, and creates draft v2 with a
finished Test, left unpublished so the role demo can try to publish it. With LLM_BACKEND=fake it
costs nothing (Playwright and CI use it that way); with real models, about $0.10.

    uv run python -m scripts.seed_fixtures
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

from app import policy as policies
from app.auth import demo_token

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "postings.jsonl"


def client(user: str, url: str) -> httpx.Client:
    return httpx.Client(base_url=url, headers={"Authorization": f"Bearer {demo_token(user)}"}, timeout=60)


def wait_for_queue(api: httpx.Client, timeout: float = 180) -> None:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        jobs = api.get("/health").json()["jobs"]
        if not jobs.get("queued") and not jobs.get("running"):
            return
        time.sleep(0.5)
    sys.exit("the worker did not finish in time: is it running?")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()

    marketplace, editor = client("marketplace", args.url), client("editor", args.url)
    health = editor.get("/health").json()
    if not health["live_labeling"]:
        sys.exit(f"not labeling: missing {', '.join(health['missing_keys'])}")
    if any(v["name"] == "v2" for v in editor.get("/policies").json()):
        sys.exit("already seeded (v2 exists): docker compose down -v, then up again")

    postings = [json.loads(line) for line in FIXTURES.read_text().splitlines() if line]
    out = marketplace.post("/v1/postings/batch", json={"postings": postings})
    out.raise_for_status()
    print(f"submitted {out.json()['accepted']} postings ({health['llm_backend']} backend)")
    wait_for_queue(editor)

    labels = {
        item["job_id"]: item["id"] for item in editor.get("/ui/labels", params={"limit": 200}).json()["items"]
    }
    decision = {"label": "NEEDS_REVIEW", "note": "Asked the employer to confirm the tool fee is refunded."}
    editor.post(f"/ui/labels/{labels['fx-fee']}/decision", json=decision).raise_for_status()

    body = policies.load_file(policies.POLICIES_DIR / "v2.yaml")
    editor.post("/policies/drafts", json={"name": "v2", "body": body}).raise_for_status()
    editor.post("/policies/drafts/v2/test").raise_for_status()
    wait_for_queue(editor)
    report = editor.get("/policies/drafts/v2/test").json()
    flips = len(report["flips"])
    print(f"draft v2 tested: {report['labeled']} postings, {flips} flips, passed {report['passed']}")
    print(f"seeded: {len(labels)} labels, 1 decision, draft v2 ready to publish")


if __name__ == "__main__":
    main()
