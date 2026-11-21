"""The demo snapshot in the repo: never an eval posting, and it opens with v2 live and v3 a draft."""

import json
import zipfile

from scripts.load_data import SPLITS
from scripts.snapshot import SNAPSHOT, TABLES


def meta() -> dict:
    with zipfile.ZipFile(SNAPSHOT) as zf:
        assert {f"{t}.copy" for t in TABLES} <= set(zf.namelist())
        return json.loads(zf.read("meta.json"))


def test_no_eval_posting_or_copy_in_the_snapshot():
    splits = json.loads(SPLITS.read_text())
    kept_out = set(map(str, splits["eval"]["ids"])) | set(map(str, splits["excluded_copies"]))
    ids = set(meta()["job_ids"])
    assert ids and not ids & kept_out


def test_snapshot_opens_with_v2_live_and_v3_a_draft():
    m = meta()
    assert m["versions"] == {"v1": "retired", "v2": "live", "v3": "draft"}
    assert m["rows"]["postings"] == len(m["job_ids"])
