import pytest

from app.agent.cache import cache_key

BASE = {
    "model_input": "Title: Data Entry Clerk",
    "policy_content_hash": "abc",
    "agent_version": "1",
    "model_ids": {"screen": "jev", "escalate": "claude-sonnet-5-5"},
    "screen_config": {"cut_off": 0.3, "hints": False},
}


def test_the_same_parts_give_the_same_key():
    assert cache_key(**BASE) == cache_key(**BASE)


def test_key_order_in_the_dicts_does_not_matter():
    reordered = BASE | {"model_ids": {"escalate": "claude-sonnet-5-5", "screen": "jev"}}
    assert cache_key(**reordered) == cache_key(**BASE)


@pytest.mark.parametrize(
    ("part", "value"),
    [
        ("model_input", "Title: Data Entry Clerk (Remote)"),
        ("policy_content_hash", "abd"),
        ("agent_version", "2"),
        ("model_ids", {"screen": "haiku", "escalate": "claude-sonnet-5-5"}),
        ("screen_config", {"cut_off": 0.25, "hints": False}),
    ],
)
def test_changing_any_part_changes_the_key(part, value):
    assert cache_key(**(BASE | {part: value})) != cache_key(**BASE)
