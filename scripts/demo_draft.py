"""Load a policy file into the running app as a draft, untested, so the Test happens in the UI.

uv run python -m scripts.demo_draft            # v2 (adds §6), as Eddie the editor
uv run python -m scripts.demo_draft --name v3 --file policies/v3.yaml
"""

import argparse
import sys
from pathlib import Path

import httpx

from app import policy as policies
from app.auth import demo_token


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--name", default="v2")
    parser.add_argument("--file", default=str(policies.POLICIES_DIR / "v2.yaml"))
    args = parser.parse_args()

    body = policies.load_file(Path(args.file))
    editor = httpx.Client(
        base_url=args.url, headers={"Authorization": f"Bearer {demo_token('editor')}"}, timeout=30
    )
    if any(v["name"] == args.name for v in editor.get("/policies").json()):
        sys.exit(f"{args.name} already exists: make reset, then make demo, to start again")
    out = editor.post("/policies/drafts", json={"name": args.name, "body": body})
    out.raise_for_status()
    print(f"draft {args.name} created from {args.file}: open {args.url}/versions/{args.name}, then Test it")


if __name__ == "__main__":
    main()
