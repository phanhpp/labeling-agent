import copy
from pathlib import Path

import pytest

from app import policy
from app.policy import PolicyError

V1 = Path(__file__).resolve().parents[1] / "policies" / "v1.yaml"


@pytest.fixture
def v1() -> dict:
    return policy.load_file(V1)


def test_v1_is_valid_and_has_the_briefs_five_sections(v1):
    assert [s["code"] for s in v1["sections"]] == ["§1", "§2", "§3", "§4", "§5"]
    assert [s["effect"] for s in v1["sections"]] == ["VIOLATING"] * 4 + ["NEEDS_REVIEW"]
    assert v1["screen_cut_off"] is None  # fitted later; until then nothing is cleared without Sonnet


def changed(body: dict, edit) -> dict:
    copied = copy.deepcopy(body)
    edit(copied)
    return copied


def test_changing_only_an_effect_keeps_the_model_hash(v1):
    """The models never see effects, so stored model answers stay valid: a $0 re-label."""
    v4 = changed(v1, lambda b: b["sections"][3].update(effect="NEEDS_REVIEW"))
    assert policy.model_hash(v4) == policy.model_hash(v1)
    assert policy.content_hash(v4) != policy.content_hash(v1)


def test_changing_labels_or_the_decision_rule_keeps_the_model_hash(v1):
    edited = changed(v1, lambda b: b["header"].update(decision_rule="Reworded for analysts."))
    assert policy.model_hash(edited) == policy.model_hash(v1)


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(
            lambda b: b["sections"][4].update(text="An empty company profile alone is not enough."), id="text"
        ),
        pytest.param(
            lambda b: b["sections"][0]["examples"].append({"text": "Pay $20 to apply.", "matches": True}),
            id="example",
        ),
        pytest.param(
            lambda b: b["sections"][0]["screen"].update(instructions="Reworded?"), id="screen question"
        ),
        pytest.param(lambda b: b["sections"][0].update(red_flags=["new phrase"]), id="red flags"),
        pytest.param(lambda b: b.update(screen_cut_off=0.25), id="cut-off"),
        pytest.param(lambda b: b["header"]["edge_cases"].append("A new edge case."), id="edge case"),
        pytest.param(lambda b: b["sections"].append({**b["sections"][0], "code": "§6"}), id="new section"),
    ],
)
def test_changing_what_the_models_see_changes_the_model_hash(v1, edit):
    assert policy.model_hash(changed(v1, edit)) != policy.model_hash(v1)


def test_effects_are_not_rendered_for_the_model(v1):
    v4 = changed(v1, lambda b: b["sections"][3].update(effect="NEEDS_REVIEW"))
    assert policy.render_sections(v4) == policy.render_sections(v1)


def test_jev_questions_come_from_the_policy(v1):
    questions = policy.jev_questions(v1)
    assert list(questions) == ["s1", "s2", "s3", "s4", "s5"]
    assert questions["s1"]["instructions"] == v1["sections"][0]["screen"]["instructions"]
    assert set(questions["s1"]["criteria"]) == {"true", "false"}


def test_render_sections_includes_every_section_text_and_example(v1):
    rendered = policy.render_sections(v1)
    for section in v1["sections"]:
        assert section["text"] in rendered
        for example in section["examples"]:
            assert example["text"] in rendered


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda b: b.pop("version"), "version"),
        (lambda b: b["sections"].clear(), "at least one section"),
        (lambda b: b["sections"][1].update(code="§1"), "appears twice"),
        (lambda b: b["sections"][0].update(code="1"), "like §1"),
        (lambda b: b["sections"][0].update(effect="BLOCK"), "effect must be one of"),
        (lambda b: b["sections"][0].update(text="  "), "text required"),
        (lambda b: b["sections"][0]["screen"].pop("false"), "screen.false required"),
        (lambda b: b["sections"][0]["examples"][0].pop("matches"), "matches: true or false"),
        (lambda b: b.update(screen_cut_off=1.5), "between 0 and 1"),
    ],
)
def test_invalid_policies_are_refused_with_a_clear_message(v1, edit, message):
    with pytest.raises(PolicyError, match=message):
        policy.validate(changed(v1, edit))
