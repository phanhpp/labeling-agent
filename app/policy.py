"""The policy as data: load it, validate it, hash it, and render what the models see.

A policy body is a dict, from a YAML file (policies/v1.yaml) or from policy_versions.body. Nothing
here calls a model.

Two hashes:
  content_hash  everything in the body. A new content_hash is a new policy.
  model_hash    only what the models see or what routes a posting to them (model_view). If two
                versions share it, stored model answers stay valid, and a re-label only re-runs the
                code rules (check and decide): no model calls, $0.
"""

import hashlib
import json
import re
from pathlib import Path

import yaml

EFFECTS = ("VIOLATING", "NEEDS_REVIEW")
_CODE = re.compile(r"^§\d+$")


class PolicyError(ValueError):
    """The policy body is not valid. The message says which field and why."""


def load_file(path: str | Path) -> dict:
    return validate(yaml.safe_load(Path(path).read_text()))


def validate(body: dict) -> dict:
    """Return the body unchanged if it is valid; raise PolicyError otherwise."""

    def need(ok: bool, message: str) -> None:
        if not ok:
            raise PolicyError(message)

    def text(value) -> bool:
        return isinstance(value, str) and value.strip() != ""

    need(isinstance(body, dict), "the policy must be a mapping")
    need(text(body.get("version")), "version: required")
    header = body.get("header")
    need(isinstance(header, dict), "header: required")
    need(text(header.get("decision_rule")), "header.decision_rule: required")
    edge_cases = header.get("edge_cases")
    need(
        isinstance(edge_cases, list) and all(text(e) for e in edge_cases), "header.edge_cases: a list of text"
    )

    sections = body.get("sections")
    need(isinstance(sections, list) and sections, "sections: at least one section")
    seen = set()
    for i, section in enumerate(sections):
        where = f"sections[{i}]"
        need(isinstance(section, dict), f"{where}: must be a mapping")
        code = section.get("code")
        need(isinstance(code, str) and _CODE.match(code) is not None, f"{where}.code: like §1, got {code!r}")
        need(code not in seen, f"{where}.code: {code} appears twice")
        seen.add(code)
        where = f"section {code}"
        need(text(section.get("title")), f"{where}: title required")
        need(text(section.get("text")), f"{where}: text required")
        need(section.get("effect") in EFFECTS, f"{where}: effect must be one of {EFFECTS}")
        screen = section.get("screen")
        need(isinstance(screen, dict), f"{where}: screen required")
        for key in ("instructions", "true", "false"):
            need(text(screen.get(key)), f"{where}: screen.{key} required")
        red_flags = section.get("red_flags", [])
        need(
            isinstance(red_flags, list) and all(text(f) for f in red_flags),
            f"{where}: red_flags is a list of text",
        )
        examples = section.get("examples")
        need(isinstance(examples, list) and examples, f"{where}: at least one example")
        for example in examples:
            need(isinstance(example, dict) and text(example.get("text")), f"{where}: each example needs text")
            need(
                isinstance(example.get("matches"), bool),
                f"{where}: each example needs matches: true or false",
            )

    cut_off = body.get("screen_cut_off")
    need(
        cut_off is None or (isinstance(cut_off, int | float) and 0 < cut_off < 1),
        "screen_cut_off: empty, or a number between 0 and 1",
    )
    return body


def _sha256(value) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def content_hash(body: dict) -> str:
    return _sha256(body)


def jev_key(code: str) -> str:
    """The question key Jev answers under, for a section: "§2" -> "s2"."""
    return "s" + code.removeprefix("§")


def jev_questions(body: dict) -> dict[str, dict]:
    """One yes/no question per section, as plain data (app/agent/screen.py builds Jev's Nouls)."""
    return {
        jev_key(section["code"]): {
            "instructions": section["screen"]["instructions"],
            "criteria": {"true": section["screen"]["true"], "false": section["screen"]["false"]},
        }
        for section in body["sections"]
    }


def model_view(body: dict) -> dict:
    """What the models see, plus what decides whether a posting reaches them.

    Left out on purpose: effects, labels and the decision rule. Code applies those (decide), so
    changing them never changes a model's answer.
    """
    return {
        "edge_cases": body["header"]["edge_cases"],
        "sections": [
            {key: section[key] for key in ("code", "title", "text", "examples")}
            for section in body["sections"]
        ],
        "jev_questions": jev_questions(body),
        "red_flags": {section["code"]: section.get("red_flags", []) for section in body["sections"]},
        "screen_cut_off": body.get("screen_cut_off"),
    }


def model_hash(body: dict) -> str:
    return _sha256(model_view(body))


def render_sections(body: dict) -> str:
    """The sections as Sonnet reads them: code, title, text and examples. No effects."""
    blocks = []
    for section in body["sections"]:
        lines = [f"{section['code']} {section['title']}", section["text"]]
        for example in section["examples"]:
            verdict = "matches" if example["matches"] else "does not match"
            lines.append(f"Example that {verdict}: {example['text']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_edge_cases(body: dict) -> str:
    return "\n".join(f"- {case}" for case in body["header"]["edge_cases"])
