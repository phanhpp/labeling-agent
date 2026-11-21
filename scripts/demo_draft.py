"""Load a policy file into the running app as a draft, through the API like the UI does.

uv run python -m scripts.demo_draft --publish   # v2 (adds §6): Test, Submit as Eddie, Publish as Sam
uv run python -m scripts.demo_draft --name v3 --file policies/v3.yaml   # an untested draft, for the UI

`make demo` runs the first: the app starts with v1 previous and v2 live, so "How labels changed"
has something to show.
"""

import argparse
import sys
from pathlib import Path

import httpx

from app import policy as policies
from app.auth import demo_token
from scripts.seed_fixtures import wait_for_queue


def client(user: str, url: str) -> httpx.Client:
    return httpx.Client(base_url=url, headers={"Authorization": f"Bearer {demo_token(user)}"}, timeout=60)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--name", default="v2")
    parser.add_argument("--file", default=str(policies.POLICIES_DIR / "v2.yaml"))
    parser.add_argument(
        "--publish", action="store_true", help="also Test it on every posting, Submit and Publish it"
    )
    args = parser.parse_args()

    body = policies.load_file(Path(args.file))
    editor = client("editor", args.url)
    if any(v["name"] == args.name for v in editor.get("/policies").json()):
        sys.exit(f"{args.name} already exists: discard it on its page in the UI, or choose another --name")
    editor.post("/policies/drafts", json={"name": args.name, "body": body}).raise_for_status()
    if not args.publish:
        print(f"draft {args.name} created from {args.file}: Test it at {args.url}/versions/{args.name}")
        return

    # wait for the postings already sent, then Test on every one of them, so Publish keeps all the
    # Test's labels and runs nothing more
    wait_for_queue(editor, timeout=900)
    editor.post(f"/policies/drafts/{args.name}/test", params={"limit": 1000}).raise_for_status()
    wait_for_queue(editor, timeout=900)
    report = editor.get(f"/policies/drafts/{args.name}/test").json()
    print(f"{args.name} tested: {report['labeled']} postings, {len(report['flips'])} labels flip")
    if not report["passed"]:
        sys.exit(f"the Test did not pass, so {args.name} stays a draft: open {args.url}/versions/{args.name}")
    editor.post(f"/policies/drafts/{args.name}/submit").raise_for_status()
    client("publisher_b", args.url).post(f"/policies/drafts/{args.name}/publish").raise_for_status()
    wait_for_queue(editor, timeout=900)
    print(f"{args.name} published by Sam and live; the previous version's labels are kept")


if __name__ == "__main__":
    main()
