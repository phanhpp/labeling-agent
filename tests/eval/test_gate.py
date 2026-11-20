from eval.run_eval import gate, passes


def dev50(recall=0.6, precision=0.7, share=0.9, errored=()):
    return {
        "main": {"recall": recall, "precision": precision},
        "quotes": {"verified_share": share},
        "errored": list(errored),
    }


def test_a_run_at_the_marks_passes():
    assert gate(dev50(), "dev50") == []


def test_each_mark_can_fail_the_gate():
    assert gate(dev50(recall=0.4), "dev50") == ["main recall 0.4 is under 0.43"]
    assert gate(dev50(precision=0.5), "dev50") == ["main precision 0.5 is under 0.55"]
    assert gate(dev50(share=0.7), "dev50") == ["verified quote share 0.7 is under 0.8"]


def test_an_errored_run_asks_for_a_rerun_instead_of_failing_quality():
    [failure] = gate(dev50(recall=0.0, errored=[{"job_id": "1", "error": "TimeoutError"}]), "dev50")
    assert "rerun" in failure


def test_suites_have_zero_slack():
    assert gate({"passed": 8, "total": 8, "failed": [], "errored": []}, "edge_cases") == []
    assert gate({"passed": 4, "total": 5, "failed": ["adv-x"], "errored": []}, "adversarial") == [
        "suite passed 4/5: ['adv-x']"
    ]


def test_a_suite_row_passes_on_label_sections_and_reason_codes():
    record = {"label": "NEEDS_REVIEW", "sections": ["§5"], "reason_codes": ["injection"]}
    assert passes(
        record,
        {"labels": ["NEEDS_REVIEW"], "sections_include": ["§5"], "reason_codes_include": ["injection"]},
    )
    assert not passes(record, {"labels": ["ALLOWED"]})
    assert not passes(record, {"sections_exclude": ["§5"]})
