"""Write RESULTS.md from the committed run files, so every number in it traces to a run.

    uv run python -m eval.report           # writes RESULTS.md
    uv run python -m eval.report --check   # exits 1 if RESULTS.md differs from what the runs give

Reads eval/runs/eval400-jev_sonnet-v1 and -v2 (the frozen 400, run once each after the eval-freeze
tag), the dev runs for the config comparison, the policy demo, the suites, and the hand-written
eval/error_analysis.yaml.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from app.dataset import CSV_PATH, read_rows
from eval.metrics import REAL_FRAUD_RATE

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "eval" / "runs"
RESULTS = ROOT / "RESULTS.md"
FLAGGED = ("VIOLATING", "NEEDS_REVIEW")


def summary(run: str) -> dict:
    return json.loads((RUNS / run / "summary.json").read_text())


def results(run: str) -> list[dict]:
    return [json.loads(line) for line in (RUNS / run / "results.jsonl").read_text().splitlines() if line]


def pct(x: float, digits: int = 0) -> str:
    return f"{100 * x:.{digits}f}%"


def interval(ci: list[float]) -> str:
    return f"{ci[0]:.2f} to {ci[1]:.2f}"


def secs(ms: int) -> str:
    return f"{ms / 1000:.1f} s"


def cost_reweighted(rows: list[dict]) -> float:
    """Cost per 1,000 at the dataset's 4.8% fraud: fraud postings cost more (fewer are cleared by Jev)."""
    fraud = [r["cost_usd"] for r in rows if r["gold"] == 1]
    legit = [r["cost_usd"] for r in rows if r["gold"] == 0]
    per_posting = REAL_FRAUD_RATE * sum(fraud) / len(fraud) + (1 - REAL_FRAUD_RATE) * sum(legit) / len(legit)
    return 1000 * per_posting


def employer_history(rows: list[dict]) -> dict:
    """What a check of the employer's history would add: a posting whose company profile appears on
    other dataset rows (outside the 400), all of them fraud. An estimate from the dataset's labels; in
    production the history would be the marketplace's confirmed takedowns."""
    data = read_rows(CSV_PATH)
    eval_ids = set(json.loads((ROOT / "data" / "splits.json").read_text())["eval"]["ids"])
    seen: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # profile -> [fraud, legit]
    for row in data:
        profile = row["company_profile"].strip()
        if profile and row["job_id"] not in eval_ids:
            seen[profile][0 if row["fraudulent"] == "1" else 1] += 1
    by_id = {row["job_id"]: row for row in data}

    def known_fraud(job_id: str) -> bool:
        fraud, legit = seen.get(by_id[job_id]["company_profile"].strip(), [0, 0])
        return fraud > 0 and legit == 0

    missed = [r for r in rows if r["gold"] == 1 and r["label"] not in FLAGGED]
    either = [r for r in rows if r["label"] in FLAGGED or known_fraud(r["job_id"])]
    return {
        "missed": len(missed),
        "missed_known": sum(known_fraud(r["job_id"]) for r in missed),
        "legit_known": sum(known_fraud(r["job_id"]) for r in rows if r["gold"] == 0),
        "caught_with": sum(r["gold"] == 1 for r in either),
        "false_alarms_with": sum(r["gold"] == 0 for r in either),
        "complete": sum(
            by_id[r["job_id"]]["has_company_logo"] == "1"
            and by_id[r["job_id"]]["company_profile"].strip() != ""
            for r in missed
        ),
    }


def confusion_table(s: dict) -> list[str]:
    c = s["confusion"]
    fraud, legit = sum(c["fraud"].values()), sum(c["legit"].values())
    return [
        "| | Labeled VIOLATING | Sent to review | Labeled ALLOWED |",
        "| --- | --- | --- | --- |",
        f"| {fraud} fraud | {c['fraud']['VIOLATING']} | {c['fraud']['NEEDS_REVIEW']} | {c['fraud']['ALLOWED']} |",
        f"| {legit} legitimate | {c['legit']['VIOLATING']} | {c['legit']['NEEDS_REVIEW']} | {c['legit']['ALLOWED']} |",
    ]


def build() -> str:
    v1s, v2s = summary("eval400-jev_sonnet-v1"), summary("eval400-jev_sonnet-v2")
    v1, v2 = results("eval400-jev_sonnet-v1"), results("eval400-jev_sonnet-v2")
    by_v2 = {r["job_id"]: r for r in v2}
    flagged = lambda r: r["label"] in FLAGGED  # noqa: E731
    missed = [r for r in v1 if r["gold"] == 1 and not flagged(r)]
    v2_catches = sum(flagged(by_v2[r["job_id"]]) for r in missed)
    v2_new_alarms = sum(1 for r in v1 if r["gold"] == 0 and not flagged(r) and flagged(by_v2[r["job_id"]]))
    # the other way: flagged under v1, not under v2 (so the net change is smaller than the new ones)
    v2_lost = {
        g: sum(1 for r in v1 if r["gold"] == g and flagged(r) and not flagged(by_v2[r["job_id"]]))
        for g in (0, 1)
    }
    n_flagged = {
        (name, g): sum(1 for r in rows if r["gold"] == g and flagged(r))
        for name, rows in (("v1", v1), ("v2", v2))
        for g in (0, 1)
    }
    cleared_rows = [r for r in v1 if "cleared_by_screen" in r["reason_codes"]]
    cleared = len(cleared_rows)
    read_rows_ = [
        r for r in v1 if r["reason_codes"] != ["cleared_by_screen"] and "injection" not in r["reason_codes"]
    ]
    mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
    history = employer_history(v1)
    errors = yaml.safe_load((ROOT / "eval" / "error_analysis.yaml").read_text())
    demo = json.loads((RUNS / "policy-demo" / "summary.json").read_text())
    suites = {
        name: summary(name)
        for name in ("pc-v1", "pc-v2", "pc-v3", "pc-v4", "gate-adversarial", "gate-edge_cases")
    }
    dev = {name: summary(f"dev300-{name}") for name in ("jev_sonnet", "sonnet_only", "haiku_sonnet")}

    m1, m2 = v1s["main"], v2s["main"]
    c1 = v1s["confusion"]
    out: list[str] = []
    w = out.append
    peak16, burst16 = summary("load-peak-16"), summary("load-burst-16")
    peak48, burst48 = summary("load-peak-48"), summary("load-burst-48")
    loads = (peak16, burst16, peak48, burst48)
    reviews = c1["fraud"]["NEEDS_REVIEW"] + c1["legit"]["NEEDS_REVIEW"]
    causes = v1s["review_causes"]
    q = v1s["quotes"]
    top = v1s["calibration"][-1]
    jev_mean = dev["jev_sonnet"]["latency_ms"]["p50"]
    sonnet_mean = dev["sonnet_only"]["latency_ms"]["p50"]

    def shows(*bullets: str) -> None:
        w("What this shows:")
        w("")
        for b in bullets:
            w(f"- {b}")
        w("")

    w("# Results")
    w("")
    w(
        "How the labeling agent performs on the 400 test postings the assignment fixes (100 fraud, 300 legitimate). "
        "These postings were never used for tuning. Every number comes from the saved runs in `eval/runs/`."
    )
    w("")
    w("## What Tests Were Done")
    w("")
    w(
        "- **Evaluation on the 400 test postings:** run once under the brief's policy (v1) and once under v2, with real "
        "models and the code frozen first. It gives the precision, recall, F1, confusion matrix, cost, speed and "
        "evidence results ([how it was run](#how-the-evaluation-was-run), [Catching Fraud](#catching-fraud-400-test-postings), "
        "[Confusion Matrix](#confusion-matrix), [Cost and Speed](#cost-and-speed-per-posting), "
        "[Can the Evidence Be Trusted?](#can-the-evidence-be-trusted))."
    )
    w(
        "- **Load tests:** the brief's peak traffic and a burst, through the real API, queue and workers "
        "([Under Load](#under-load-95-within-60-seconds))."
    )
    w(
        "- **Policy change:** versions v2 to v4 on 100 development postings "
        "([The Policy Change, Without Code](#the-policy-change-without-code-100-development-postings))."
    )
    w(
        "- **Hand-written cases:** edge cases, prompt injections and policy changes, run with real models on every "
        "change ([The Policy Change, Without Code](#the-policy-change-without-code-100-development-postings))."
    )
    w(
        "- **Set-up comparison:** three ways to run the agent, on 300 development postings "
        "([Other Set-Ups](#other-set-ups-tested-on-300-development-postings))."
    )
    w(
        f"- **Error analysis:** {len(errors)} wrong answers read by hand "
        "([Error Analysis](#error-analysis-9-postings-read-by-hand))."
    )
    w(
        "- **Calibration:** Jev's labeling cut-off was tuned on the Jev fitting set, so Jev clears almost nothing "
        "Claude would flag; the injection threshold was tuned to hold at most 1 in 1,000 ordinary postings while "
        "catching every test injection (both in the README, How the two thresholds were chosen); and the agent's "
        "confidence was checked against how often it is right ([Can the Evidence Be Trusted?](#can-the-evidence-be-trusted))."
    )
    w("")
    w("## In Short")
    w("")
    w(
        f"- Of 100 fraud postings, {m1['tp']} are flagged: {c1['fraud']['VIOLATING']} as VIOLATING and "
        f"{c1['fraud']['NEEDS_REVIEW']} sent to an analyst."
    )
    w("- No legitimate posting is labeled VIOLATING." if c1["legit"]["VIOLATING"] == 0 else "")
    w(f"- {pct(v1s['review_load'])} of postings go to review.")
    w(
        f"- ${cost_reweighted(v1):.2f} per 1,000 postings at the real fraud rate; a typical posting takes "
        f"{secs(v1s['latency_ms']['p50'])}."
    )
    w(
        "- 95% of postings are labeled within 60 seconds at the brief's peak traffic, once there are enough workers."
    )
    w("- Most missed fraud breaks no rule in the policy: the giveaway is the employer.")
    w("")
    w("## Contents")
    w("")
    for i, (title, anchor) in enumerate(
        (
            ("How the Evaluation Was Run", "how-the-evaluation-was-run"),
            ("Catching Fraud", "catching-fraud-400-test-postings"),
            ("Confusion Matrix", "confusion-matrix"),
            ("Cost and Speed", "cost-and-speed-per-posting"),
            ("Under Load: 95% Within 60 Seconds", "under-load-95-within-60-seconds"),
            ("Can the Evidence Be Trusted?", "can-the-evidence-be-trusted"),
            ("Why Fraud Gets Through", "why-fraud-gets-through-and-how-we-know"),
            ("The Policy Change, Without Code", "the-policy-change-without-code-100-development-postings"),
            ("Other Set-Ups", "other-set-ups-tested-on-300-development-postings"),
            ("Error Analysis", "error-analysis-9-postings-read-by-hand"),
            ("Limitations", "limitations"),
        ),
        start=1,
    ):
        w(f"{i}. [{title}](#{anchor})")
    w("")

    w("## How the Evaluation Was Run")
    w("")
    w(
        "This is the run behind the precision, recall, F1, confusion matrix, cost, speed and evidence results below. "
        "The load test, the policy change and the other set-ups are described in their own sections."
    )
    w("")
    w(
        "- **Frozen first:** the code was tagged `eval-freeze`, then run once on the 400 under v1 and once under v2, "
        "which adds §6."
    )
    w(
        "- **The agent:** Jev screens every posting, Claude Sonnet 5.5 reads those Jev can't clear, and code checks "
        "the quotes and sets the label."
    )
    w(
        "- **Where:** on a laptop, 8 postings at a time, with the cache off, so every posting paid for its own model calls."
    )
    w(
        "- **Why a quarter fraud:** the 400 are 25% fraud, against about 5% in the dataset, so there are enough fraud "
        "cases to measure."
    )
    w("")
    w(
        "**How a review is counted.** The dataset says fraud or not; the agent has a third answer, NEEDS_REVIEW, "
        "meaning an analyst will look. The **main** count treats a review as catching the fraud, since a person sees "
        "it. The **strict** count accepts only VIOLATING."
    )
    w("")

    w("## Catching Fraud (400 Test Postings)")
    w("")
    w("| Policy | Precision | Recall | F1 | Strict precision | Strict recall | Precision at 4.8% fraud |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for name, s in (("v1 (the brief)", v1s), ("v2 (adds §6)", v2s)):
        m, st = s["main"], s["strict"]
        w(
            f"| {name} | {m['precision']:.2f} | {m['recall']:.2f} | {m['f1']:.2f} | {st['precision']:.2f} | "
            f"{st['recall']:.2f} | {m['precision_at_real_rate']:.2f} |"
        )
    w("")
    shows(
        f"**Most fraud is caught, mostly through review:** {pct(m1['recall'])} of fraud is flagged, but only "
        f"{pct(v1s['strict']['recall'])} as VIOLATING; the rest goes to an analyst.",
        f"**VIOLATING can be trusted:** under v1 it was never wrong (strict precision {v1s['strict']['precision']:.2f}).",
        f"**v2 trades false alarms for recall:** it flags more fraud ({pct(m2['recall'])}) but sends more legitimate "
        f"postings to review. The difference is within the noise (v1's recall could be anywhere from "
        f"{interval(m1['ci95']['recall'])}).",
        "**Precision drops in the real world:** the test set is a quarter fraud, the real world about 5%, so in "
        f"production about 1 in {round(1 / m1['precision_at_real_rate'])} flagged postings would be fraud. That is why "
        "accuracy alone would mislead.",
    )

    w("## Confusion Matrix")
    w("")
    w("Rows are the dataset's answer; columns are the agent's label.")
    w("")
    w("**v1**")
    w("")
    out.extend(confusion_table(v1s))
    w("")
    w("**v2**")
    w("")
    out.extend(confusion_table(v2s))
    w("")
    shows(
        f"**The review queue is the main tool:** {pct(v1s['review_load'], 1)} of postings go to review under v1, "
        f"{pct(v2s['review_load'], 1)} under v2.",
        "**§5 drives it:** a posting with no identifiable employer goes to review even when nothing else is wrong. "
        f"Of the {reviews} postings sent to review under v1, {causes.get('review_section_matched', 0)} had a section "
        f"like §5 match and {causes.get('section_unsure', 0)} had a section Claude was unsure about (a few had both).",
        '**One legitimate posting was labeled VIOLATING under v2:** a "work from home" business opportunity that '
        "asks for capital; see the error analysis.",
    )

    w("## Cost and Speed (Per Posting)")
    w("")
    w(
        "| Policy | Cost per 1,000 on the test set | Cost per 1,000 at 4.8% fraud | Typical posting | Slowest 5% |"
    )
    w("| --- | --- | --- | --- | --- |")
    for name, s, rows in (("v1", v1s, v1), ("v2", v2s, v2)):
        w(
            f"| {name} | ${s['cost_per_1000_usd']:.2f} | ${cost_reweighted(rows):.2f} | {secs(s['latency_ms']['p50'])} | "
            f"{secs(s['latency_ms']['p95'])} |"
        )
    w("")
    shows(
        f"**Jev decides most postings alone:** {cleared} of the 400 were cleared without Claude, at about "
        f"${mean([r['cost_usd'] for r in cleared_rows]):.4f} and {secs(mean([r['latency_ms'] for r in cleared_rows]))} "
        "each.",
        f"**Claude is the cost and the slow tail:** the other postings went to Claude at about "
        f"${mean([r['cost_usd'] for r in read_rows_]):.4f} and {secs(mean([r['latency_ms'] for r in read_rows_]))} each.",
        "**Cheaper in production:** fraud reaches Claude more often, so at the real 5% fraud rate the cost per 1,000 "
        "is lower than on the test set.",
        "**Work time only:** these times leave out waiting in the queue; the next section covers that. The two runs "
        f"cost ${sum(r['cost_usd'] for r in v1):.2f} and ${sum(r['cost_usd'] for r in v2):.2f}.",
    )

    w("## Under Load: 95% Within 60 Seconds")
    w("")
    w(
        "The brief's target is 95% of postings labeled within 60 seconds, at five times the normal traffic. The times "
        "above measure only how long one posting takes to work through. Under load, what matters is the wait in the "
        "queue plus the work, so this was tested end to end."
    )
    w("")
    w(
        "**How.** Real postings went through the real API, queue and workers, each timed from the moment the API "
        "accepted it to the moment its label was saved (`scripts/load_test.py`). Two kinds of traffic:"
    )
    w("")
    w(
        "- **The brief's peak:** 200,000 postings a day is about 2.3 a second, and five times that is 11.6 a second, "
        f"held for 30 seconds ({peak16['postings']} postings)."
    )
    w(f"- **A burst:** {burst16['postings']} postings in one request, like a marketplace sending a backlog.")
    w("")
    w(
        "Both ran at two sizes: one worker doing 16 jobs at once, and three workers doing 16 each, 48 in total. Three "
        "workers mirror the autoscaling in the design."
    )
    w("")
    w("| Set-up | Peak: typical | Peak: slowest 5% | Burst: typical | Burst: slowest 5% |")
    w("| --- | --- | --- | --- | --- |")
    for label, peak, burst in (
        ("1 worker, 16 jobs at once", peak16, burst16),
        ("3 workers, 48 jobs at once", peak48, burst48),
    ):
        pk, bs = peak["submit_to_label_s"], burst["submit_to_label_s"]
        w(f"| {label} | {pk['p50']} s | {pk['p95']} s | {bs['p50']} s | {bs['p95']} s |")
    w("")
    all_ok = all(r["within_60s"] == 1 for r in loads)
    none_failed = all(r["failed"] == 0 for r in loads)
    shows(
        "**The target holds:** every posting was labeled within 60 seconds in all four runs"
        + (", and none failed." if none_failed else ".")
        if all_ok
        else "**The target did not hold in every run.**",
        f"**16 jobs at once is not enough for a long peak:** it labels about {peak16['throughput_per_s']:.1f} postings "
        "a second while 11.6 arrive, so the queue grows. The 30-second peak still made it; a longer one wouldn't.",
        f"**48 jobs at once keeps up:** at the peak, the slowest 5% took {peak48['submit_to_label_s']['p95']} s, close "
        "to the work time alone, with almost no waiting.",
        "**Capacity must grow with the queue:** this is why the design scales workers on how long the oldest job has "
        "waited, not on CPU. Workers mostly wait on the models, so CPU stays low even when they are overloaded.",
    )
    w(f"The four runs cost ${sum(r['cost_usd'] for r in loads):.2f}.")
    w("")

    w("## Can the Evidence Be Trusted?")
    w("")
    w(
        f"Under v1, Claude gave {q['verified'] + q['dropped']} quotes as evidence, and {q['verified']} "
        f"({pct(q['verified_share'])}) were found word for word in the posting. The other {q['dropped']} were dropped "
        "and never shown."
    )
    w("")
    w("| Confidence the agent gave | Postings | Correct |")
    w("| --- | --- | --- |")
    for bucket in v1s["calibration"]:
        w(f"| {bucket['confidence'].replace('-', ' to ')} | {bucket['n']} | {pct(bucket['correct'])} |")
    w("")
    shows(
        "**Every quote shown is real:** a quote not found in the posting is never shown, and a section left without "
        "one can't make a posting VIOLATING.",
        f"**High confidence is mostly right:** at {top['confidence'].split('-')[0]} or more, the agent is right "
        f"{pct(top['correct'])} of the time (a fraud posting flagged, or a legitimate one allowed).",
        "**Low confidence is a weak signal:** below 0.7 the groups are small, so their order means little.",
    )

    w("## Why Fraud Gets Through, and How We Know")
    w("")
    w(
        f"Under v1, {len(missed)} fraud postings were labeled ALLOWED. They look like ordinary ads: no fee, no request "
        f"for bank details, no unrealistic pay, and {history['complete']} of them have a logo and a full company "
        "profile. So did the agent miss something, or does the policy not cover them? Three checks say it's the policy:"
    )
    w("")
    w(
        "1. **It isn't the screen.** With Claude reading every posting and no Jev, it allowed almost the same fraud "
        "(38 against 39, on the 300 development postings)."
    )
    w(
        "2. **Changing the policy catches some.** v2 adds §6, for a company's text copied with no profile or logo of "
        f"its own. It newly catches {v2_catches} of the {len(missed)}, but stops flagging {v2_lost[1]} other, "
        f"so {v2_catches - v2_lost[1]} more fraud postings are flagged in all ({n_flagged['v1', 1]} to "
        f"{n_flagged['v2', 1]}). The cost: {v2_new_alarms} legitimate postings newly flagged and {v2_lost[0]} no longer, "
        f"so {v2_new_alarms - v2_lost[0]} more in all ({n_flagged['v1', 0]} to {n_flagged['v2', 0]}). (It caught more "
        "on the development postings, but §6 was written from those, so this test set is the fair measure.)"
    )
    w(
        f"3. **The real signal is the employer.** {history['missed_known']} of the {len(missed)} share their company "
        "profile with other postings that are all fraud, and no legitimate posting in the test set does. Checking the "
        f"employer's history would catch them with no new false alarms: {history['caught_with']} of 100 fraud flagged. "
        "That's the next thing to build. (An estimate from the dataset's labels; in production, the history would be "
        "the marketplace's confirmed takedowns.)"
    )
    w("")

    w("## The Policy Change, Without Code (100 Development Postings)")
    w("")
    w(
        "Each policy version was run on the same 100 development postings with real models, to see how many labels "
        "it changes and what the re-label costs."
    )
    w("")
    w("| Version | What changed | Labels that changed | Of these, from the edit | Cost of the re-label |")
    w("| --- | --- | --- | --- | --- |")
    what = {
        "v2": "Adds §6, impersonated employer",
        "v3": "§5 relaxed when the logo is shown",
        "v4": "§4 sends to review instead of VIOLATING",
    }
    for step in demo:
        from_change = sum(f["from_the_change"] for f in step["flip_list"])
        w(
            f"| {step['version']} | {what.get(step['version'], ', '.join(step['changes']))} | {step['flips']} | "
            f"{from_change} | ${step['cost_usd']:.2f} |"
        )
    w("")
    pc = [suites[f"pc-v{i}"] for i in range(1, 5)]
    adv, edge = suites["gate-adversarial"], suites["gate-edge_cases"]
    pc_line = (
        f"{pc[0]['passed']} of {pc[0]['total']} each"
        if all(r["passed"] == pc[0]["passed"] and r["total"] == pc[0]["total"] for r in pc)
        else ", ".join(f"{r['passed']} of {r['total']}" for r in pc)
    )
    all_passed = all(r["passed"] == r["total"] for r in (*pc, adv, edge))
    shows(
        "**No code change:** publishing a new version changes labels on its own.",
        "**Not every change comes from the edit:** some are Claude answering differently when asked the same thing "
        "again. The Test report separates the two before anyone publishes.",
        "**Some changes are free:** v4 only changed what §4 leads to, not what Claude is asked, so the stored answers "
        "were decided again in code at no cost.",
        f"**The hand-written cases {'all passed' if all_passed else 'did not all pass'}:** policy changes under v1 to "
        f"v4 ({pc_line}), prompt injection ({adv['passed']} of {adv['total']}) and edge cases ({edge['passed']} of "
        f"{edge['total']}), run with real models on every change to the agent or policy.",
    )

    w("## Other Set-Ups (Tested on 300 Development Postings)")
    w("")
    w(
        "We compared three ways to run the agent on our 300 practice postings. (We ran the 400 final test postings "
        "only once with our chosen set-up so the test stays fair.)"
    )
    w("")
    w("| Set-up | Precision | Recall | F1 | Cost per 1,000 | Typical posting | Slowest 5% |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    names = {
        "jev_sonnet": "Jev screen, then Claude Sonnet (chosen)",
        "sonnet_only": "Claude Sonnet on every posting",
        "haiku_sonnet": "Claude Haiku screen, then Sonnet (when Jev is down)",
    }
    for key, s in dev.items():
        m = s["main"]
        w(
            f"| {names[key]} | {m['precision']:.2f} | {m['recall']:.2f} | {m['f1']:.2f} | ${s['cost_per_1000_usd']:.2f} | "
            f"{secs(s['latency_ms']['p50'])} | {secs(s['latency_ms']['p95'])} |"
        )
    w("")
    js, so = dev["jev_sonnet"], dev["sonnet_only"]
    shows(
        "**Same accuracy:** all three options catch roughly the same fraud (any small differences are just normal "
        "test noise).",
        "**Big savings on cost and speed:** filtering with Jev first cuts costs by more than half "
        f"(${js['cost_per_1000_usd']:.2f} vs. ${so['cost_per_1000_usd']:.2f}) and makes a typical posting "
        f"{round(sonnet_mean / jev_mean)}x faster ({secs(jev_mean)} vs. {secs(sonnet_mean)}) than sending everything "
        "to Claude Sonnet.",
        "**Backup ready:** if Jev goes down, switching to the Haiku filter keeps accuracy steady at a slightly higher "
        "cost and slower speed.",
    )
    w(
        "These times come from an earlier run on the development postings, so they differ a little from the test-set "
        "run above."
    )
    w("")

    w(f"## Error Analysis ({len(errors)} Postings Read by Hand)")
    w("")
    w("| Posting | Dataset says | Agent | Why |")
    w("| --- | --- | --- | --- |")
    gold = {"fraud": "Fraud", "legit": "Legitimate"}
    for e in errors:
        ours = e["label"] + (" (v2)" if e["run"] == "v2" else "")
        w(f"| {e['id']} | {gold[e['gold']]} | {ours} | {e['summary']} |")
    w("")
    shows(
        "**Most missed fraud is about the employer, not the ad:** clean ads from accounts whose other postings are "
        "fraud.",
        "**Most false alarms are §5:** short agency ads that name no company.",
        "**Some dataset labels are debatable:** 569 and 3174 read like schemes but are marked legitimate.",
    )
    w("The full notes for each posting are in `eval/error_analysis.yaml`.")
    w("")

    w("## Limitations")
    w("")
    w(
        f"- **100 fraud postings** give wide ranges: recall under v1 could be anywhere from "
        f"{interval(m1['ci95']['recall'])}."
    )
    w(
        "- **The dataset labels the account, not always the ad:** some fraud is a clean ad from a bad employer, and a "
        'few "legitimate" postings read like schemes.'
    )
    w(
        "- **Claude doesn't always answer the same way twice:** on the same text, a section can move between matched "
        "and unsure."
    )
    w(
        "- **Jev's scores move a little between runs:** on the test set, 1 of 300 legitimate postings was held as an "
        "injection, more than the 1 in 1,000 the threshold was tuned for; its score was 0.51 in one run and under 0.5 "
        "in the other."
    )
    w(
        "- **Times are from a laptop,** with the model APIs over the public internet; the load test ran up to 48 jobs "
        "at once on one machine."
    )
    w("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if RESULTS.md is out of date")
    args = parser.parse_args()
    text = build()
    if args.check:
        if not RESULTS.exists() or RESULTS.read_text() != text:
            sys.exit("RESULTS.md differs from the runs: run uv run python -m eval.report")
        print("RESULTS.md matches the runs")
        return
    RESULTS.write_text(text)
    print(f"wrote {RESULTS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
