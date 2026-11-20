"""What the graph carries.

State is per run and is saved in every checkpoint, so it holds plain JSON-able data only.
Context is what a run needs but never changes: the policy, the config and the cache lookup. It is
passed again on every invoke (including a resume), so it isn't written into each checkpoint.
"""

import operator
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, TypedDict

from app.agent.configs import AgentConfig


class State(TypedDict, total=False):
    raw: dict  # the posting as submitted
    cleaned: dict  # every field, cleaned (what the models see and quotes point into)
    facts: dict  # from clean: empty fields, contact tokens, hidden text removed
    model_input: str  # the rendered posting the models read
    cache_key: str
    screen: dict  # used, cleared, scores, injection, regex_hits
    raw_output: dict | None  # the model's answer before check, stored with the label
    checked: dict  # check's result as plain data
    decision: dict  # the label and what it rests on
    cached_from: int | None  # the label this run reused, on a cache hit
    failure: str | None  # a code from decide.FAILURES when a step failed
    usage: Annotated[list[dict], operator.add]  # one entry per model call; nodes append


@dataclass
class Context:
    policy: dict
    policy_version: str
    config: AgentConfig
    # Given a cache key, the stored decision to reuse (with its label id) or None. Off when None.
    cache_lookup: Callable[[str], Awaitable[dict | None]] | None = None
