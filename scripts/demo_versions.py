"""The policy-change demo, through the running API only: no code changes at any step.

For each of v2, v3 and v4 (policies/*.yaml): an editor creates the draft, runs Test and reads the
flip report, another person publishes it, and the re-label runs. It prints what flipped, how many
model calls it took and what it cost. v4 changes only an effect, so it re-labels in code at $0.

Needs the stack running with model keys (docker compose up) and a fresh database: it labels a dev
sample under v1 first. To run it again: make reset up (or docker compose down -v, then up).

    uv run python -m scripts.demo_versions --limit 100
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

from app import policy as policies
from app.auth import demo_token
from scripts.submit_postings import postings

OUT = Path(__file__).resolve().parents[1] / "eval" / "runs" / "policy-demo"
VERSIONS = ("v2", "v3", "v4")


def client(user: str, url: str) -> httpx.Client:
    return httpx.Client(base_url=url, headers={"Authorization": f"Bearer {demo_token(user)}"}, timeout=120)


def wait_for_queue(api: httpx.Client, what: str) -> None:
    """Until the worker has no queued or running job."""
    started = time.monotonic()
    while True:
        queue = api.get("/health").json()["jobs"]
        waiting = queue.get("queued", 0) + queue.get("running", 0)
        if not waiting:
            print(f"  {what}: done in {time.monotonic() - started:.0f} s")
            return
        print(f"  {what}: {waiting} jobs left", end="\r", flush=True)
        time.sleep(2)


def show_report(report: dict) -> None:
    print(
        f"  Test ({report['mode']}): {report['labeled']} postings, {len(report['flips'])} changed, "
        f"{report['flips_from_the_change']} of them involving a changed section"
    )
    for change, count in sorted(report["changed"].items()):
        print(f"    {change:28} {count}")
    for flip in report["flips"][:6]:
        before, after = flip["before"], flip["after"]
        why = "the change" if flip["from_the_change"] else "model variation"
        print(
            f"    job {flip['job_id']:>6}: {before['label']} {before['sections']} -> "
            f"{after['label']} {after['sections']}  ({why})"
        )
    print(f"  model calls {report['model_calls']}, cost ${report['cost_usd']:.4f}, passed {report['passed']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--limit", type=int, default=100, help="dev postings to label and test on")
    args = parser.parse_args()

    marketplace, editor, publisher = (client(u, args.url) for u in ("marketplace", "editor", "publisher_b"))
    health = editor.get("/health").json()
    if not health["live_labeling"]:
        sys.exit(f"not labeling: missing {', '.join(health['missing_keys'])}")
    names = {v["name"] for v in editor.get("/policies").json()}
    if names & set(VERSIONS):
        sys.exit("the demo has run on this database already: make reset up")

    print(f"v1: labeling {args.limit} dev postings ({health['agent_config']})")
    marketplace.post("/v1/postings/batch", json={"postings": postings("dev", args.limit)}).raise_for_status()
    wait_for_queue(editor, "v1 labels")

    results = []
    for name in VERSIONS:
        body = policies.load_file(policies.POLICIES_DIR / f"{name}.yaml")
        live = next(v["name"] for v in editor.get("/policies").json() if v["status"] == "live")
        print(f"\n{name}: draft from {live}")
        editor.post("/policies/drafts", json={"name": name, "body": body}).raise_for_status()
        diff = editor.get(f"/policies/{name}", params={"diff": live}).json()["diff"]["changes"]
        print("  changes:", ", ".join(f"{c['where']} {c['change']}" for c in diff))
        editor.post(f"/policies/drafts/{name}/test", params={"limit": args.limit}).raise_for_status()
        wait_for_queue(editor, "Test")
        report = editor.get(f"/policies/drafts/{name}/test").json()
        show_report(report)

        published = publisher.post(f"/policies/drafts/{name}/publish")
        published.raise_for_status()
        relabel = published.json()
        print(
            f"  published by sam: re-label {relabel['mode']}, {relabel['labeled_by_test']} kept from Test, "
            f"{relabel['redecided']} decided again in code, {relabel['queued']} queued"
        )
        wait_for_queue(editor, "re-label")
        progress = editor.get(f"/policies/{name}/relabel").json()
        model_calls = progress["labels"] - progress["labels_without_a_model_call"]
        print(
            f"  {name} live: {progress['labels']} labels, {model_calls} model runs,"
            f" ${progress['cost_usd']:.4f}"
        )
        results.append(
            {
                "version": name,
                "from": live,
                "changes": [c["where"] for c in diff],
                "mode": report["mode"],
                "tested": report["labeled"],
                "flips": len(report["flips"]),
                "flips_from_the_change": report["flips_from_the_change"],
                "changed": report["changed"],
                "flip_list": report["flips"],
                "model_runs": model_calls,
                "cost_usd": progress["cost_usd"],
            }
        )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(results, indent=1) + "\n")
    print("\nversion  mode      flips  from the change  model runs  cost")
    for r in results:
        print(
            f"{r['version']:8} {r['mode']:9} {r['flips']:5}  {r['flips_from_the_change']:15}  "
            f"{r['model_runs']:10}  ${r['cost_usd']:.4f}"
        )
    print(f"\nwritten to {OUT / 'summary.json'}")


if __name__ == "__main__":
    main()
