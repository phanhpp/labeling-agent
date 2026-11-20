"""Metrics, checked against numbers worked out by hand."""

import pytest

from eval.metrics import calibration, confusion, precision_at_rate, prf, review_causes, summarize


def rec(gold, label, reasons=(), confidence=0.9, cost=0.01, ms=1000):
    return {
        "job_id": "x",
        "gold": gold,
        "label": label,
        "reason_codes": list(reasons),
        "confidence": confidence,
        "cost_usd": cost,
        "latency_ms": ms,
        "quotes_verified": 1,
        "quotes_dropped": 0,
    }


# 4 fraud: 2 VIOLATING, 1 NEEDS_REVIEW, 1 ALLOWED. 6 legit: 1 VIOLATING, 2 NEEDS_REVIEW, 3 ALLOWED.
RECORDS = (
    [
        rec(1, "VIOLATING"),
        rec(1, "VIOLATING"),
        rec(1, "NEEDS_REVIEW", ["review_section_matched"]),
        rec(1, "ALLOWED"),
    ]
    + [
        rec(0, "VIOLATING"),
        rec(0, "NEEDS_REVIEW", ["review_section_matched"]),
        rec(0, "NEEDS_REVIEW", ["section_unsure"]),
    ]
    + [rec(0, "ALLOWED")] * 3
)


def test_main_counts_needs_review_as_caught():
    main = prf(RECORDS, "main")
    assert (main["tp"], main["fp"], main["fn"]) == (3, 3, 1)
    assert main["precision"] == 0.5
    assert main["recall"] == 0.75
    assert main["f1"] == 0.6


def test_strict_counts_only_violating():
    strict = prf(RECORDS, "strict")
    assert (strict["tp"], strict["fp"], strict["fn"]) == (2, 1, 2)
    assert strict["precision"] == round(2 / 3, 4)
    assert strict["recall"] == 0.5


def test_precision_at_the_real_fraud_rate():
    # recall 0.75, false positive rate 3/6: at 4.8% fraud, 0.036 caught vs 0.476 false alarms
    assert precision_at_rate(0.75, 0.5, 0.048) == pytest.approx(0.036 / (0.036 + 0.476))


def test_confusion_counts_all_three_labels():
    assert confusion(RECORDS) == {
        "fraud": {"VIOLATING": 2, "NEEDS_REVIEW": 1, "ALLOWED": 1},
        "legit": {"VIOLATING": 1, "NEEDS_REVIEW": 2, "ALLOWED": 3},
    }


def test_review_causes_count_reason_codes_of_needs_review_only():
    assert review_causes(RECORDS) == {"review_section_matched": 2, "section_unsure": 1}


def test_errored_runs_are_listed_and_not_scored():
    summary = summarize([*RECORDS, {"job_id": "9", "gold": 1, "error": "TimeoutError: slow"}])
    assert summary["scored"] == 10
    assert summary["errored"] == [{"job_id": "9", "error": "TimeoutError: slow"}]
    assert summary["main"]["recall"] == 0.75  # unchanged by the errored fraud row


def test_summary_has_cost_latency_and_intervals():
    summary = summarize(RECORDS)
    assert summary["cost_per_1000_usd"] == 10.0
    assert summary["latency_ms"] == {"p50": 1000, "p95": 1000}
    low, high = summary["main"]["ci95"]["recall"]
    assert 0 <= low <= 0.75 <= high <= 1
    assert summary["review_load"] == 0.3


def test_calibration_bins_by_stated_confidence():
    rows = calibration([rec(1, "VIOLATING", confidence=0.95), rec(0, "VIOLATING", confidence=0.95)])
    assert rows[-1] == {"confidence": "0.9-1.0", "n": 2, "correct": 0.5}
