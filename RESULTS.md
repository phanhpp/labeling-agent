# Results

The labeling agent on the 400 evaluation postings: the fixed test set, 100 fraud and 300 legitimate, kept apart from all tuning. Each number below is computed by `eval/report.py` from the run files in `eval/runs/`; `uv run python -m eval.report --check` fails if this page and the runs disagree.

**In short.** Under the brief's policy (v1) the agent flags 59 of 100 fraud postings (46 for an analyst, 13 as VIOLATING) and never labels a legitimate posting VIOLATING. It sends 23% of postings to an analyst and costs $2.75 per 1,000 postings at the real fraud rate. Most of the fraud it misses (27 of 41) are complete, plausible ads that break no rule in the policy; the evidence points to who posted them, which a posting-level policy can't see.

## The setup

- **The 400:** the brief's fixed set, listed in `eval/eval_ids.txt`: 100 fraud and 300 legitimate, so 25% fraud against the dataset's 4.8%. They and their 586 exact copies elsewhere in the dataset never went into the database, prompts, examples or any tuning.
- **Frozen first:** the code was tagged `eval-freeze` before the first run, and each policy was run once.
- **The agent:** `jev_sonnet`. Jev screens every posting (a section scored 0.17 or more goes on); Claude Sonnet 5.5 reads the rest against the policy; quotes are checked word for word in code; the label is set in code from Claude's answers.
- **Where:** in-process on a laptop, 8 postings at a time, cache off, so every posting paid for its model calls.

## How NEEDS_REVIEW is counted

The dataset has two answers (fraud or not); the agent has three. **The main count treats NEEDS_REVIEW as flagging the posting**, like VIOLATING: an analyst will look at it, so the fraud isn't missed. The strict count takes only VIOLATING as flagged. Both are shown; the review load (how many go to an analyst) is the price of the main count.

## Precision, recall and F1 (the fraud class)

| Policy | Precision | Recall | F1 | Strict precision | Strict recall | Precision at 4.8% fraud |
| --- | --- | --- | --- | --- | --- | --- |
| v1 (the brief) | 0.57 | 0.59 | 0.58 | 1.00 | 0.13 | 0.17 |
| v2 (adds §6) | 0.53 | 0.65 | 0.59 | 0.92 | 0.11 | 0.15 |

95% intervals (bootstrap) for v1: precision 0.48 to 0.66, recall 0.51 to 0.69, F1 0.50 to 0.66. With 100 fraud postings, a difference of a few points between v1 and v2 is inside the noise.

Precision at 4.8% fraud is what precision would be at the dataset's real rate: on the 400, one posting in four is fraud, which makes precision look better than it would be in production.

## Confusion matrix

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

**Review load:** 22.8% of postings under v1, 27.5% under v2. Under v1, 59 went to review because a section that sends to review matched (mostly §5, unverifiable employer) and 36 because Claude was unsure about a section.

## Cost and latency

| Policy | Cost per 1,000 (the 400, 25% fraud) | Cost per 1,000 at 4.8% fraud | Typical (p50) | Slowest 5% (p95) |
| --- | --- | --- | --- | --- |
| v1 | $3.35 | $2.75 | 0.7 s | 6.8 s |
| v2 | $3.74 | $3.02 | 1.1 s | 7.2 s |

- **Jev decides most postings alone:** under v1, 221 of 400 were cleared by Jev (on average $0.0001 and 0.4 s each) and never reached Claude. Fraud reaches Claude more often, so at the real 4.8% fraud rate the cost is lower.
- **Claude is the slow step:** the postings it read took 5.8 s and cost $0.0075 on average, which sets the p95. Latency is per posting, on a laptop, with 8 in flight.
- **These two runs cost** $1.34 and $1.50.

## Evidence and confidence

- **Every quote shown is real:** Claude quoted 211 passages as evidence under v1; 204 (97%) were found word for word in the posting. The other 7 were dropped and never shown; a section left without evidence can't make a posting VIOLATING.
- **High confidence is mostly right:** 89% of the labels given 0.9 or more are correct (a fraud posting flagged, or a legitimate one allowed), against about half below 0.7. Below 0.7 the buckets are small, so their order isn't meaningful.

| Confidence | Postings | Correct |
| --- | --- | --- |
| 0.0-0.5 | 10 | 50% |
| 0.5-0.7 | 47 | 40% |
| 0.7-0.9 | 133 | 77% |
| 0.9-1.0 | 210 | 89% |

## Why fraud gets through, and how we know

Under v1, 41 fraud postings were labeled ALLOWED: 26 cleared by Jev before Claude read them, and 15 read by Claude and allowed. They don't break a rule the policy states: 27 of the 41 have a logo and a full company profile, and read like ordinary ads. Three checks say the policy, not the agent, is the limit:

1. **Not the screen** (on the 300 development postings): with Claude reading every posting and no Jev, 38 fraud postings were still allowed, against 39 with Jev.
2. **Changing the policy changes what is caught.** v2 adds §6 (a company's text copied, with no profile or logo of its own). On the 400 it catches 7 of the 41 that v1 missed, and sends 13 more legitimate postings to review. On the development postings, which §6 was written from, it caught 19 of 39: the 400 is the fair test, and §6 helps less here because most of these misses do show a logo.
3. **The employer's history would catch most of the rest.** 27 of the 41 missed postings share their company profile with other postings in the dataset (outside the 400), all of them fraud. No legitimate posting in the 400 does (0 of 300). Adding that check to v1 would flag 86 of 100 fraud postings with the same 45 false alarms. This is an estimate from the dataset's labels; in production the history would be the marketplace's confirmed takedowns. It is the next thing to build (not built here).

## The policy change, without code

Publishing a new version changes labels with no code change, and re-labels existing postings in the cheapest valid way (see README, Changing the policy). Each version run on the same 100 development postings with real models:

| Version | What changed | Labels that changed | Of these, from the edit | Cost of the re-label |
| --- | --- | --- | --- | --- |
| v2 | adds §6, impersonated employer | 13 | 7 | $0.41 (full) |
| v3 | §5 relaxed when the logo is shown | 8 | 6 | $0.42 (full) |
| v4 | §4 sends to review instead of VIOLATING | 1 | 1 | $0.00 (redecide) |

v4 costs nothing: only what a section leads to changed, not what Claude is asked, so the stored answers are decided again in code. A change not from the edit is Claude answering differently when asked again; the Test report marks which is which before anyone publishes.

**Fixed suites:** policy change under v1 5 of 5, v2 5 of 5, v3 5 of 5, v4 5 of 5, prompt injection 5 of 5, edge cases 8 of 8 passed.

## Other set-ups (development postings only)

Compared on the 300 development postings, not on the 400 (the 400 were run once, with the chosen set-up):

| Set-up | Precision | Recall | F1 | Cost per 1,000 | p50 | p95 |
| --- | --- | --- | --- | --- | --- | --- |
| Jev screen, then Claude Sonnet (chosen) | 0.51 | 0.48 | 0.49 | $3.26 | 0.3 s | 5.7 s |
| Claude Sonnet on every posting | 0.51 | 0.49 | 0.50 | $7.36 | 4.8 s | 5.8 s |
| Claude Haiku screen, then Sonnet (when Jev is down) | 0.53 | 0.49 | 0.51 | $4.72 | 5.8 s | 8.5 s |

The screen changes cost and speed, not quality: every set-up lands within a few points, inside the noise.

## Error analysis

Nine postings, read by hand after the runs (`eval/error_analysis.yaml`). Under v1, 45 legitimate postings were sent to review, 44 of them over §5.

| Posting | Dataset | Ours | Why |
| --- | --- | --- | --- |
| 2137 | fraud | ALLOWED | An "Electrical Technician III" ad that opens with Aker Solutions' real corporate overview, with a logo and a full profile. Jev's highest score was 0.05, so it was cleared without Claude. v2's §6 needs the logo to be missing, so v2 misses it too. Its company profile is on 31 rows of the dataset, all fraud: a check of the employer's other postings would catch it. |
| 3056 | fraud | ALLOWED | Puget Sound Energy's job text pasted in, with no logo and no profile. v1 has no section for it and Jev cleared it (0.07). v2's §6 (impersonated employer) matches it: NEEDS_REVIEW. This is the kind of miss a policy change fixes without code. |
| 2274 | fraud | ALLOWED | "Customer Service Representative", work from home, salary 30,000 to 50,000, logo and a long profile. Nothing asks for money or data, and the pay is plausible. Jev's highest score was 0.10, under the 0.17 cut-off, so Claude never read it. Its profile is on 12 rows of the dataset, all fraud: the fraud is in who posted it, not in what the ad says. |
| 662 | fraud | ALLOWED | "Director of Strategy" at a fast-growing SaaS company: detailed, well written, logo and a long profile. Claude read it and found nothing the policy names. Its profile is on 35 rows of the dataset, all fraud: account-level fraud, which a policy about one posting can't see. Under v2 Claude marked §5 unsure (review), a different answer to the same text, not the change. |
| 3612 | fraud | ALLOWED | "Account Sales Managers $80-$130,000/yr", commission-based, for a no-credit-check finance firm. The policy's edge case says a commission-only role is ALLOWED when the pay is stated plainly, and it is. Following the policy gives ALLOWED; the dataset says fraud (its profile is on 20 rows, all fraud). |
| 434 | legit | NEEDS_REVIEW | A three-line contract ad ("Scrum Master, 4 months, Norwalk CT") with no profile, no logo and no employer name. §5 (unverifiable employer) can't be ruled out, so it goes to review. 44 of the 45 false alarms under v1 are §5 like this one: short, legitimate agency ads that name no company. |
| 569 | legit | NEEDS_REVIEW | "English Teacher Abroad": "Play with kids, get paid for it ... Excellent for student loans/credit cards", a 53-character profile and a personal name with links. §5 matched (review). The dataset marks it legitimate; an analyst would still want to look. The same ad appears twice in the 400 (177), both held for review. |
| 10628 | legit | NEEDS_REVIEW | An ordinary "Web Developer (AngularJS)" ad. Jev's injection score was 0.51, just over the 0.5 threshold, so it was held as an injection and no model labeled it. In the v2 run Jev scored it under 0.5 and it was ALLOWED. The threshold was fitted to flag at most 0.1% of ordinary postings; here 1 of 300 (0.3%). The cost of a false hold is one analyst look, not a wrong label. |
| 3174 | legit | VIOLATING (v2) | "Self Employed - Work from Home": a business opportunity for "anyone over 18" that requires capital investment, with income hype and a profile that names no business. Under v2 Claude matched §1 (payment to take part) and §5, so it is VIOLATING: the only legitimate posting labeled VIOLATING in either run. The policy reading is defensible; the dataset says legitimate. |

Categories: cleared by screen 1, copied employer 2, debatable gold 2, empty profile 1, injection edge 1, policy silent 2.

## Limitations

- **100 fraud postings** give wide intervals: recall's 95% interval under v1 is 0.51 to 0.69.
- **The dataset's labels are about the account, not always the ad.** Several misses are clean ads from employers whose other postings are fraud, and a few 'legitimate' postings read like schemes (3174, 569).
- **Claude doesn't always answer the same way twice.** On the same text, a section can move between matched and unsure; the Test report separates these changes from the policy edit.
- **Jev's scores move a little between runs.** One legitimate posting scored 0.51 for injection in one run (held) and under 0.5 in the other (allowed).
- **Latency is from a laptop,** with the model APIs over the public internet.
