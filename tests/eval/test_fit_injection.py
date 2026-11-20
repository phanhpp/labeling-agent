from scripts.fit_injection import INJECTIONS, fit, flagged_share


def test_the_threshold_is_the_lowest_within_the_review_budget():
    ordinary = [0.2] * 997 + [0.6, 0.7, 0.9]  # 3 of 1,000 score high
    assert flagged_share(ordinary, 0.61) == 0.002  # over the 0.1% budget
    assert fit(ordinary) == 0.71  # the first step that flags only 1 in 1,000


def test_some_injection_texts_are_held_out():
    held_out = [name for name, _, held in INJECTIONS if held]
    assert 0 < len(held_out) < len(INJECTIONS)
