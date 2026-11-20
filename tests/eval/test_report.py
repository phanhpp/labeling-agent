"""The arithmetic RESULTS.md rests on (eval/report.py)."""

from eval.report import confusion_table, cost_reweighted


def test_cost_is_reweighted_to_the_real_fraud_rate():
    rows = [{"gold": 1, "cost_usd": 0.01}] * 25 + [{"gold": 0, "cost_usd": 0.002}] * 75
    # 4.8% at $0.01 and 95.2% at $0.002, per 1,000 postings
    assert round(cost_reweighted(rows), 3) == round(1000 * (0.048 * 0.01 + 0.952 * 0.002), 3)


def test_the_confusion_table_has_a_row_per_class_and_review_as_its_own_column():
    summary = {
        "confusion": {
            "fraud": {"VIOLATING": 13, "NEEDS_REVIEW": 46, "ALLOWED": 41},
            "legit": {"VIOLATING": 0, "NEEDS_REVIEW": 45, "ALLOWED": 255},
        }
    }
    table = confusion_table(summary)
    assert table[2] == "| 100 fraud | 13 | 46 | 41 |"
    assert table[3] == "| 300 legitimate | 0 | 45 | 255 |"
