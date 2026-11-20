"""Settings, read from the environment. For local runs, .env is loaded first."""

import os

from dotenv import load_dotenv

load_dotenv()  # never overrides a variable that is already set

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"
# Pinned, not "jev-latest": the cut-off is fitted on one Jev version, so a silent upgrade could change
# which postings are cleared without anyone noticing. (jev-latest resolved to this on 2026-11-20.)
JEV = "jev-1.14.0"

# Only these models may be called. An unknown id refuses to run instead of quietly costing money.
MODEL_ALLOWLIST = {SONNET, HAIKU, JEV}

# US dollars per million tokens (Anthropic list prices, Nov 2026). A cache write costs 1.25x input
# (5-minute cache); a cache read is $0.10 on Sonnet 5.5 and 0.1x input on Haiku 5.5.
PRICES = {
    SONNET: {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.10},
    HAIKU: {"input": 0.10, "output": 0.50, "cache_write": 0.125, "cache_read": 0.01},
    JEV: {"input": 0.042, "output": 0.0, "cache_write": 0.0, "cache_read": 0.0},  # output is free
}

MODEL_TIMEOUT_S = 25  # per call; with one retry the worst case stays inside the 90 s job limit
MODEL_MAX_RETRIES = 1
JEV_TIMEOUT_S = 5  # Jev usually answers in under a second; 3 tries stay under 20 s
INJECTION_THRESHOLD = 0.5  # a Jev injection score at or above this sets the injection flag


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://labeler:labeler@localhost:5432/labeler")


def llm_backend() -> str:
    """ "real" calls the models; "fake" uses app/agent/fake_models.py (CI, tests, demos without keys)."""
    backend = os.environ.get("LLM_BACKEND", "real")
    if backend not in ("real", "fake"):
        raise ValueError(f"LLM_BACKEND must be real or fake, got {backend!r}")
    return backend


def has_anthropic_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
