# Results

How the labeling agent performs on the 400 test postings the assignment fixes (100 fraud, 300 legitimate). These postings were never used for tuning. Every number comes from the saved runs in `eval/runs/`.

## What Tests Were Done

- **Evaluation on the 400 test postings:** run once under the brief's policy (v1) and once under v2, with real models and the code frozen first. It gives the precision, recall, F1, confusion matrix, cost, speed and evidence results ([how it was run](#how-the-evaluation-was-run), [Catching Fraud](#catching-fraud-400-test-postings), [Confusion Matrix](#confusion-matrix), [Cost and Speed](#cost-and-speed-per-posting), [Can the Evidence Be Trusted?](#can-the-evidence-be-trusted)).
- **Load tests:** the brief's peak traffic and a burst, through the real API, queue and workers ([Under Load](#under-load-95-within-60-seconds)).
- **Policy change:** versions v2 to v4 on 100 development postings ([The Policy Change, Without Code](#the-policy-change-without-code-100-development-postings)).
- **Hand-written cases:** edge cases, prompt injections and policy changes, run with real models on every change ([The Policy Change, Without Code](#the-policy-change-without-code-100-development-postings)).
- **Set-up comparison:** three ways to run the agent, on 300 development postings ([Other Set-Ups](#other-set-ups-tested-on-300-development-postings)).
- **Error analysis:** 9 wrong answers read by hand ([Error Analysis](#error-analysis-9-postings-read-by-hand)).
- **Calibration:** Jev's labeling cut-off was tuned on the Jev fitting set, so Jev clears almost nothing Claude would flag; the injection threshold was tuned to hold at most 1 in 1,000 ordinary postings while catching every test injection (both in the README, How the two thresholds were chosen); and the agent's confidence was checked against how often it is right ([Can the Evidence Be Trusted?](#can-the-evidence-be-trusted)).

## In Short

- Of 100 fraud postings, 59 are flagged: 13 as VIOLATING and 46 sent to an analyst.
- No legitimate posting is labeled VIOLATING.
- 23% of postings go to review.
- $2.75 per 1,000 postings at the real fraud rate; a typical posting takes 0.7 s.
- 95% of postings are labeled within 60 seconds at the brief's peak traffic, once there are enough workers.
- Most missed fraud breaks no rule in the policy: the giveaway is the employer.

## Contents

1. [How the Evaluation Was Run](#how-the-evaluation-was-run)
2. [Catching Fraud](#catching-fraud-400-test-postings)
3. [Confusion Matrix](#confusion-matrix)
4. [Cost and Speed](#cost-and-speed-per-posting)
5. [Under Load: 95% Within 60 Seconds](#under-load-95-within-60-seconds)
6. [Can the Evidence Be Trusted?](#can-the-evidence-be-trusted)
7. [Why Fraud Gets Through](#why-fraud-gets-through-and-how-we-know)
8. [The Policy Change, Without Code](#the-policy-change-without-code-100-development-postings)
9. [Other Set-Ups](#other-set-ups-tested-on-300-development-postings)
10. [Error Analysis](#error-analysis-9-postings-read-by-hand)
11. [Limitations](#limitations)

## How the Evaluation Was Run

This is the run behind the precision, recall, F1, confusion matrix, cost, speed and evidence results below. The load test, the policy change and the other set-ups are described in their own sections.

- **Frozen first:** the code was tagged `eval-freeze`, then run once on the 400 under v1 and once under v2, which adds §6.
- **The agent:** Jev screens every posting, Claude Sonnet 5.5 reads those Jev can't clear, and code checks the quotes and sets the label.
- **Where:** on a laptop, 8 postings at a time, with the cache off, so every posting paid for its own model calls.
- **Why a quarter fraud:** the 400 are 25% fraud, against about 5% in the dataset, so there are enough fraud cases to measure.

**How a review is counted.** The dataset says fraud or not; the agent has a third answer, NEEDS_REVIEW, meaning an analyst will look. The **main** count treats a review as catching the fraud, since a person sees it. The **strict** count accepts only VIOLATING.

## Catching Fraud (400 Test Postings)

| Policy | Precision | Recall | F1 | Strict precision | Strict recall | Precision at 4.8% fraud |
| --- | --- | --- | --- | --- | --- | --- |
| v1 (the brief) | 0.57 | 0.59 | 0.58 | 1.00 | 0.13 | 0.17 |
| v2 (adds §6) | 0.53 | 0.65 | 0.59 | 0.92 | 0.11 | 0.15 |

What this shows:

- **Most fraud is caught, mostly through review:** 59% of fraud is flagged, but only 13% as VIOLATING; the rest goes to an analyst.
- **VIOLATING can be trusted:** under v1 it was never wrong (strict precision 1.00).
- **v2 trades false alarms for recall:** it flags more fraud (65%) but sends more legitimate postings to review. The difference is within the noise (v1's recall could be anywhere from 0.51 to 0.69).
- **Precision drops in the real world:** the test set is a quarter fraud, the real world about 5%, so in production about 1 in 6 flagged postings would be fraud. That is why accuracy alone would mislead.

## Confusion Matrix

Rows are the dataset's answer; columns are the agent's label.

**v1**

| | Labeled VIOLATING | Sent to review | Labeled ALLOWED |
| --- | --- | --- | --- |
| 100 fraud | 13 | 46 | 41 |
| 300 legitimate | 0 | 45 | 255 |

**v2**

| | Labeled VIOLATING | Sent to review | Labeled ALLOWED |
| --- | --- | --- | --- |
| 100 fraud | 11 | 54 | 35 |
| 300 legitimate | 1 | 56 | 243 |

What this shows:

- **The review queue is the main tool:** 22.8% of postings go to review under v1, 27.5% under v2.
- **§5 drives it:** a posting with no identifiable employer goes to review even when nothing else is wrong. Of the 91 postings sent to review under v1, 59 had a section like §5 match and 36 had a section Claude was unsure about (a few had both).
- **One legitimate posting was labeled VIOLATING under v2:** a "work from home" business opportunity that asks for capital; see the error analysis.

## Cost and Speed (Per Posting)

| Policy | Cost per 1,000 on the test set | Cost per 1,000 at 4.8% fraud | Typical posting | Slowest 5% |
| --- | --- | --- | --- | --- |
| v1 | $3.35 | $2.75 | 0.7 s | 6.8 s |
| v2 | $3.74 | $3.02 | 1.1 s | 7.2 s |

What this shows:

- **Jev decides most postings alone:** 221 of the 400 were cleared without Claude, at about $0.0001 and 0.4 s each.
- **Claude is the cost and the slow tail:** the other postings went to Claude at about $0.0075 and 5.8 s each.
- **Cheaper in production:** fraud reaches Claude more often, so at the real 5% fraud rate the cost per 1,000 is lower than on the test set.
- **Work time only:** these times leave out waiting in the queue; the next section covers that. The two runs cost $1.34 and $1.50.

## Under Load: 95% Within 60 Seconds

The brief's target is 95% of postings labeled within 60 seconds, at five times the normal traffic. The times above measure only how long one posting takes to work through. Under load, what matters is the wait in the queue plus the work, so this was tested end to end.

**How.** Real postings went through the real API, queue and workers, each timed from the moment the API accepted it to the moment its label was saved (`scripts/load_test.py`). Two kinds of traffic:

- **The brief's peak:** 200,000 postings a day is about 2.3 a second, and five times that is 11.6 a second, held for 30 seconds (348 postings).
- **A burst:** 200 postings in one request, like a marketplace sending a backlog.

Both ran at two sizes: one worker doing 16 jobs at once, and three workers doing 16 each, 48 in total. Three workers mirror the autoscaling in the design.

| Set-up | Peak: typical | Peak: slowest 5% | Burst: typical | Burst: slowest 5% |
| --- | --- | --- | --- | --- |
| 1 worker, 16 jobs at once | 11.0 s | 20.6 s | 15.6 s | 27.2 s |
| 3 workers, 48 jobs at once | 1.0 s | 6.2 s | 9.2 s | 14.8 s |

What this shows:

- **The target holds:** every posting was labeled within 60 seconds in all four runs, and none failed.
- **16 jobs at once is not enough for a long peak:** it labels about 6.8 postings a second while 11.6 arrive, so the queue grows. The 30-second peak still made it; a longer one wouldn't.
- **48 jobs at once keeps up:** at the peak, the slowest 5% took 6.2 s, close to the work time alone, with almost no waiting.
- **Capacity must grow with the queue:** this is why the design scales workers on how long the oldest job has waited, not on CPU. Workers mostly wait on the models, so CPU stays low even when they are overloaded.

The four runs cost $3.02.

## Can the Evidence Be Trusted?

Under v1, Claude gave 211 quotes as evidence, and 204 (97%) were found word for word in the posting. The other 7 were dropped and never shown.

| Confidence the agent gave | Postings | Correct |
| --- | --- | --- |
| 0.0 to 0.5 | 10 | 50% |
| 0.5 to 0.7 | 47 | 40% |
| 0.7 to 0.9 | 133 | 77% |
| 0.9 to 1.0 | 210 | 89% |

What this shows:

- **Every quote shown is real:** a quote not found in the posting is never shown, and a section left without one can't make a posting VIOLATING.
- **High confidence is mostly right:** at 0.9 or more, the agent is right 89% of the time (a fraud posting flagged, or a legitimate one allowed).
- **Low confidence is a weak signal:** below 0.7 the groups are small, so their order means little.

## Why Fraud Gets Through, and How We Know

Under v1, 41 fraud postings were labeled ALLOWED. They look like ordinary ads: no fee, no request for bank details, no unrealistic pay, and 27 of them have a logo and a full company profile. So did the agent miss something, or does the policy not cover them? Three checks say it's the policy:

1. **It isn't the screen.** With Claude reading every posting and no Jev, it allowed almost the same fraud (38 against 39, on the 300 development postings).
2. **Changing the policy catches some.** v2 adds §6, for a company's text copied with no profile or logo of its own. It newly catches 7 of the 41, but stops flagging 1 other, so 6 more fraud postings are flagged in all (59 to 65). The cost: 13 legitimate postings newly flagged and 1 no longer, so 12 more in all (45 to 57). (It caught more on the development postings, but §6 was written from those, so this test set is the fair measure.)
3. **The real signal is the employer.** 27 of the 41 share their company profile with other postings that are all fraud, and no legitimate posting in the test set does. Checking the employer's history would catch them with no new false alarms: 86 of 100 fraud flagged. That's the next thing to build. (An estimate from the dataset's labels; in production, the history would be the marketplace's confirmed takedowns.)

## The Policy Change, Without Code (100 Development Postings)

Each policy version was run on the same 100 development postings with real models, to see how many labels it changes and what the re-label costs.

| Version | What changed | Labels that changed | Of these, from the edit | Cost of the re-label |
| --- | --- | --- | --- | --- |
| v2 | Adds §6, impersonated employer | 13 | 7 | $0.41 |
| v3 | §5 relaxed when the logo is shown | 8 | 6 | $0.42 |
| v4 | §4 sends to review instead of VIOLATING | 1 | 1 | $0.00 |

What this shows:

- **No code change:** publishing a new version changes labels on its own.
- **Not every change comes from the edit:** some are Claude answering differently when asked the same thing again. The Test report separates the two before anyone publishes.
- **Some changes are free:** v4 only changed what §4 leads to, not what Claude is asked, so the stored answers were decided again in code at no cost.
- **The hand-written cases all passed:** policy changes under v1 to v4 (5 of 5 each), prompt injection (6 of 6) and edge cases (8 of 8), run with real models on every change to the agent or policy.

## Other Set-Ups (Tested on 300 Development Postings)

We compared three ways to run the agent on our 300 practice postings. (We ran the 400 final test postings only once with our chosen set-up so the test stays fair.)

| Set-up | Precision | Recall | F1 | Cost per 1,000 | Typical posting | Slowest 5% |
| --- | --- | --- | --- | --- | --- | --- |
| Jev screen, then Claude Sonnet (chosen) | 0.51 | 0.48 | 0.49 | $3.26 | 0.3 s | 5.7 s |
| Claude Sonnet on every posting | 0.51 | 0.49 | 0.50 | $7.36 | 4.8 s | 5.8 s |
| Claude Haiku screen, then Sonnet (when Jev is down) | 0.53 | 0.49 | 0.51 | $4.72 | 5.8 s | 8.5 s |

What this shows:

- **Same accuracy:** all three options catch roughly the same fraud (any small differences are just normal test noise).
- **Big savings on cost and speed:** filtering with Jev first cuts costs by more than half ($3.26 vs. $7.36) and makes a typical posting 16x faster (0.3 s vs. 4.8 s) than sending everything to Claude Sonnet.
- **Backup ready:** if Jev goes down, switching to the Haiku filter keeps accuracy steady at a slightly higher cost and slower speed.

These times come from an earlier run on the development postings, so they differ a little from the test-set run above.

## Error Analysis (9 Postings Read by Hand)

| Posting | Dataset says | Agent | Why |
| --- | --- | --- | --- |
| 2137 | Fraud | ALLOWED | Copies a real company's overview (Aker Solutions), with a logo and a full profile, so Jev cleared it. Its profile appears on 31 other postings, all fraud. |
| 3056 | Fraud | ALLOWED | A real company's job text (Puget Sound Energy) pasted in, with no logo or profile. v1 has no rule for it; v2's §6 catches it. |
| 2274 | Fraud | ALLOWED | A plausible work-from-home customer service job. Nothing in the ad breaks a rule; its profile appears on 12 other postings, all fraud. |
| 662 | Fraud | ALLOWED | A polished "Director of Strategy" ad. Claude found nothing the policy names; its profile appears on 35 other postings, all fraud. |
| 3612 | Fraud | ALLOWED | A commission-only sales job with the pay stated plainly, which the policy explicitly allows. |
| 434 | Legitimate | NEEDS_REVIEW | A three-line contract ad with no employer named, so §5 sends it to review. 44 of the 45 false alarms are like this. |
| 569 | Legitimate | NEEDS_REVIEW | "English Teacher Abroad: play with kids, get paid for it", a tiny profile and a personal name. Marked legitimate, but worth an analyst's look. |
| 10628 | Legitimate | NEEDS_REVIEW | An ordinary web developer ad that Jev scored 0.51 for injection, just over the 0.5 line, so it was held. In the v2 run it scored under 0.5. |
| 3174 | Legitimate | VIOLATING (v2) | A "work from home" business opportunity that requires capital investment. Labeling it VIOLATING under §1 is defensible; the dataset says legitimate. |

What this shows:

- **Most missed fraud is about the employer, not the ad:** clean ads from accounts whose other postings are fraud.
- **Most false alarms are §5:** short agency ads that name no company.
- **Some dataset labels are debatable:** 569 and 3174 read like schemes but are marked legitimate.

The full notes for each posting are in `eval/error_analysis.yaml`.

## Limitations

- **100 fraud postings** give wide ranges: recall under v1 could be anywhere from 0.51 to 0.69.
- **The dataset labels the account, not always the ad:** some fraud is a clean ad from a bad employer, and a few "legitimate" postings read like schemes.
- **Claude doesn't always answer the same way twice:** on the same text, a section can move between matched and unsure.
- **Jev's scores move a little between runs:** on the test set, 1 of 300 legitimate postings was held as an injection, more than the 1 in 1,000 the threshold was tuned for; its score was 0.51 in one run and under 0.5 in the other.
- **Times are from a laptop,** with the model APIs over the public internet; the load test ran up to 48 jobs at once on one machine.
