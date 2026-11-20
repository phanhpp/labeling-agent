"""The EMSCAD dataset: download it once, check it is the expected file, read it."""

import csv
import hashlib
import sys
import urllib.request
from pathlib import Path

# Pinned to one revision of the Hugging Face dataset, so every run reads the same file.
CSV_URL = (
    "https://huggingface.co/datasets/victor/real-or-fake-fake-jobposting-prediction/resolve/"
    "a751f55136a26da3c36e26aa207a9e187ca24b45/fake_job_postings.csv"
)
CSV_SHA256 = "59253295129d8b6a27607f9904f7d4ddf4dbb0ee35e079c7eb51b58b5e62bf60"
CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "fake_job_postings.csv"

TEXT_FIELDS = ("title", "company_profile", "description", "requirements", "benefits")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(path: Path = CSV_PATH) -> Path:
    """Fetch the CSV if it isn't there yet, and refuse a file that isn't the pinned one."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
        urllib.request.urlretrieve(CSV_URL, partial)
        partial.rename(path)
    actual = sha256_of(path)
    if actual != CSV_SHA256:
        raise ValueError(f"{path} has sha256 {actual}, expected {CSV_SHA256}. Delete it and run again.")
    return path


def read_rows(path: Path = CSV_PATH) -> list[dict[str, str]]:
    """Every row as a dict of strings. Fields contain newlines; the csv module handles them."""
    csv.field_size_limit(sys.maxsize)  # a few fields are longer than the default limit
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def text_key(row: dict[str, str]) -> str:
    """The five text fields joined: two rows with the same key are exact copies of one posting."""
    return "\x1f".join(row[field] for field in TEXT_FIELDS)
