"""Check the running system end to end: submit one posting, wait for its label, print it.

uv run python -m scripts.smoke            # fails if no label arrives within 60 s
"""

import argparse
import json
import sys
import time

import httpx

# Hand-written: an advance fee (§1) from an employer that can be identified.
POSTING = {
    "title": "Assembly Technician",
    "company_profile": "Craftline Kits builds DIY furniture kits in Portland, Oregon, since 2015.",
    "description": (
        "Assemble furniture kits at home. Before your first shift you must buy the $149 starter kit "
        "from us; the cost is refunded after 90 days."
    ),
    "requirements": "Basic tools.",
    "employment_type": "Part-time",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--token", default="demo-marketplace")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()

    job_id = f"smoke-{int(time.time())}"
    headers = {"Authorization": f"Bearer {args.token}"}
    with httpx.Client(base_url=args.url, headers=headers, timeout=10) as client:
        health = client.get("/health").json()
        print(f"health: live_labeling={health['live_labeling']} config={health['agent_config']}")
        if not health["live_labeling"]:
            sys.exit(f"not labeling: missing {', '.join(health['missing_keys'])}")
        client.post("/v1/postings", json={"job_id": job_id, **POSTING}).raise_for_status()
        started = time.monotonic()
        while time.monotonic() - started < args.timeout:
            response = client.get(f"/v1/postings/{job_id}/label")
            if response.status_code == 200:
                print(f"labeled in {time.monotonic() - started:.1f} s:")
                print(json.dumps(response.json(), indent=2, ensure_ascii=False))
                return
            time.sleep(0.5)
    sys.exit(f"no label for {job_id} within {args.timeout:.0f} s")


if __name__ == "__main__":
    main()
