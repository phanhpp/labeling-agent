"""Save the app's database as the demo snapshot, or load it into a fresh app.

    uv run python -m scripts.snapshot save --database-url postgresql://...   # from an app labeled by Claude
    uv run python -m scripts.snapshot load                                   # make demo: into the running app

The snapshot is a real run, kept in the repo so `make demo` opens with Claude's labels at once, with no
key and no cost: the postings, their labels under v1 and v2 (v2 published), the dataset's answers for
them and each run's saved steps. Nothing is labeled when it loads; a Test or a live run only happens
when someone clicks it (and needs a key). Times are moved forward to now on load, so the postings
count as recent for a Test and a re-label.
"""

import argparse
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from app.config import database_url
from app.dataset import download

SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "demo-snapshot.zip"
# parents before children, so the copy back in never breaks a foreign key
TABLES = [
    "policy_versions",
    "batches",
    "postings",
    "jobs",
    "labels",
    "decisions",
    "dataset_labels",
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
]


def save(url: str, path: Path) -> None:
    with psycopg.connect(url) as conn, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        counts = {}
        for table in TABLES:
            buf = io.BytesIO()
            with conn.cursor().copy(f"COPY {table} TO STDOUT") as copy:
                for data in copy:
                    buf.write(data)
            zf.writestr(f"{table}.copy", buf.getvalue())
            counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        versions = conn.execute("SELECT name, status FROM policy_versions ORDER BY name").fetchall()
        job_ids = sorted(r[0] for r in conn.execute("SELECT job_id FROM postings").fetchall())
        meta = {
            "saved_at": datetime.now(UTC).isoformat(),
            "rows": counts,
            "versions": dict(versions),
            "job_ids": job_ids,  # tests/data checks none is an eval posting or a copy of one
        }
        zf.writestr("meta.json", json.dumps(meta, indent=1))
    print(f"saved {path.name}: {counts['postings']} postings, {counts['labels']} labels, {dict(versions)}")


def load(url: str, path: Path) -> None:
    with psycopg.connect(url) as conn, zipfile.ZipFile(path) as zf:
        conn.execute(f"TRUNCATE {', '.join(TABLES)} CASCADE")
        for table in TABLES:
            with conn.cursor().copy(f"COPY {table} FROM STDIN") as copy:
                copy.write(zf.read(f"{table}.copy"))
        # ids carry on after the snapshot's
        for table, column in conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns"
            " WHERE table_schema = 'public' AND column_default LIKE 'nextval%%' AND table_name = ANY(%s)",
            (TABLES,),
        ).fetchall():
            conn.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'),"
                f" (SELECT coalesce(max({column}), 0) + 1 FROM {table}), false)"
            )
        # move every time forward by the same amount, so the newest posting arrived just now
        (shift,) = conn.execute("SELECT now() - max(created_at) FROM postings").fetchone()
        for table, column in conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'"
            " AND data_type = 'timestamp with time zone' AND table_name = ANY(%s)",
            (TABLES,),
        ).fetchall():
            conn.execute(f"UPDATE {table} SET {column} = {column} + %s", (shift,))
        meta = json.loads(zf.read("meta.json"))
    print(f"loaded the saved run: {meta['rows']['postings']} postings labeled by Claude, {meta['versions']}")
    download()  # the dataset, for the live demo and the dataset comparison


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["save", "load"])
    parser.add_argument("--database-url", default=database_url())
    parser.add_argument("--file", type=Path, default=SNAPSHOT)
    args = parser.parse_args()
    (save if args.action == "save" else load)(args.database_url, args.file)


if __name__ == "__main__":
    main()
