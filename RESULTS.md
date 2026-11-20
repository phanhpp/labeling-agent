# Results

How the labeling agent performs on the 400 test postings the assignment fixes (100 fraud, 300 legitimate), which were never used for tuning. Every number is computed by `eval/report.py` from the saved runs in `eval/runs/`; `make results` fails if this page and the runs disagree.

**In short**

- Of 100 fraud postings, 59 are flagged: 13 as VIOLATING and 46 sent to an analyst.
- No legitimate posting is labeled VIOLATING.
- 23% of postings go to review.
- $2.75 per 1,000 postings at the real fraud rate; a typical posting takes 0.7 s, and 95% are labeled within 60 seconds at the brief's peak traffic.
- Most missed fraud breaks no rule in the policy: the giveaway is the employer.

## How the test was run

The code was frozen (git tag `eval-freeze`) and run once on the 400 under the brief's policy (v1), and once under v2, which adds §6. Jev screens every posting, Claude Sonnet 5.5 reads those Jev can't clear, and code checks the quotes and sets the label. The runs were in-process on a laptop, 8 postings at a time, with the cache off, so every posting paid for its own model calls. The 400 are a quarter fraud, against about 5% in the dataset, so there are enough fraud cases to measure.

## How a review is counted

The dataset answers fraud or not; the agent has a third answer, NEEDS_REVIEW, meaning an analyst will look. The **main** count treats a review as catching the fraud, since a person sees it. The **strict** count accepts only VIOLATING. The share sent to review is the price of the main count, so it is reported alongside.

## Catching fraud

| Policy | Precision | Recall | F1 | Strict precision | Strict recall | Precision at 4.8% fraud |
| --- | --- | --- | --- | --- | --- | --- |
| v1 (the brief) | 0.57 | 0.59 | 0.58 | 1.00 | 0.13 | 0.17 |
| v2 (adds §6) | 0.53 | 0.65 | 0.59 | 0.92 | 0.11 | 0.15 |

Under v1, 57% of the postings flagged are fraud (precision) and 59% of the fraud is flagged (recall). When the agent says VIOLATING it is right every time (strict precision 1.00), but it says so for only 13% of fraud: most fraud goes to review instead. v2 flags more fraud (65%) at the cost of more false alarms. The 95% ranges are wide (v1's recall runs from 0.51 to 0.69), so v1 and v2 are within the noise of each other.

The last column matters most for production. The test set is a quarter fraud; the real world is about 5%. At the real rate, about 1 in 6 flagged postings would be fraud, which is why the review queue is treated as a cost, and why accuracy alone would mislead.

**Confusion matrix.** Rows are the dataset's answer; columns are the agent's label.

v1:

| | Labeled VIOLATING | Sent to review | Labeled ALLOWED |
| --- | --- | --- | --- |
| 100 fraud | 13 | 46 | 41 |
| 300 legitimate | 0 | 45 | 255 |

v2:

| | Labeled VIOLATING | Sent to review | Labeled ALLOWED |
| --- | --- | --- | --- |
| 100 fraud | 11 | 54 | 35 |
| 300 legitimate | 1 | 56 | 243 |

**Review load:** 22.8% of postings under v1, 27.5% under v2. Most come from §5: a posting with no identifiable employer goes to review even when nothing else is wrong. Under v1, 59 went to review because such a section matched, and 36 because Claude was unsure about a section.

## Cost and speed

| Policy | Cost per 1,000 on the test set | Cost per 1,000 at 4.8% fraud | Typical posting | Slowest 5% |
| --- | --- | --- | --- | --- |
| v1 | $3.35 | $2.75 | 0.7 s | 6.8 s |
| v2 | $3.74 | $3.02 | 1.1 s | 7.2 s |

Jev decides most postings alone: 221 of the 400 were cleared without Claude, at about $0.0001 and 0.4 s each. The rest went to Claude at about $0.0075 and 5.8 s each, which sets the slow tail. Fraud reaches Claude more often, so the cost at the real fraud rate is lower than on the test set. These times are the work on each posting only; the next section adds the wait in the queue. The two runs cost $1.34 and $1.50.

## Under load: 95% within 60 seconds

The brief's target is 95% of postings labeled within 60 seconds, at five times the normal traffic. The times above measure only how long one posting takes to work through. Under load, what matters is the wait in the queue plus the work, so this was tested end to end.

**How.** Real postings went through the real API, queue and workers, each timed from the moment the API accepted it to the moment its label was saved (`scripts/load_test.py`). Two kinds of traffic:

- **The brief's peak:** 200,000 postings a day is about 2.3 a second, and five times that is 11.6 a second, held for 30 seconds (348 postings).
- **A burst:** 200 postings in one request, like a marketplace sending a backlog.

Both ran at two sizes: one worker doing 16 jobs at once, and three workers doing 16 each, 48 in total. Three workers mirror the autoscaling in the design.

**With 16 parallel jobs,** the system labels about 6.8 postings a second while 11.6 arrive, so the queue grows. At the peak, a typical posting took 11.0 s and the slowest 5% took 20.6 s; the burst finished with the slowest 5% at 27.2 s. Every posting made it under 60 seconds, but only because the peak lasted 30 seconds: a longer peak would keep the queue growing until the target broke. 16 is not enough capacity for a sustained peak.

**With 48 parallel jobs,** it keeps up. At the peak, a typical posting took 1.0 s and the slowest 5% 6.2 s, close to the working time alone, with almost no waiting. The burst cleared with the slowest 5% at 14.8 s.

**What it shows:**

1. The 60-second target holds at the brief's peak, with room to spare, once there is enough capacity.
2. Capacity has to grow with the queue. That is the design's choice: workers scale on how long the oldest job has waited, not on CPU, because workers mostly wait on the models and CPU stays low even when they are overloaded.

No posting failed, and the four runs cost $3.02.

## Can the evidence be trusted?

**Every quote shown is real.** Under v1, Claude gave 211 quotes as evidence, and 204 (97%) were found word for word in the posting. The other 7 were dropped and never shown, and a section left without a verified quote can't make a posting VIOLATING.

**Confidence means something at the top end:**

| Confidence | Postings | Correct |
| --- | --- | --- |
| 0.0-0.5 | 10 | 50% |
| 0.5-0.7 | 47 | 40% |
| 0.7-0.9 | 133 | 77% |
| 0.9-1.0 | 210 | 89% |

When the agent gives 0.9 or more, it is right 89% of the time (a fraud posting flagged, or a legitimate one allowed). Below 0.7 the groups are small, so their order means little.

## Why fraud gets through, and how we know

Under v1, 41 fraud postings were labeled ALLOWED. They look like ordinary ads: no fee, no request for bank details, no unrealistic pay, and 27 of them have a logo and a full company profile. So did the agent miss something, or does the policy not cover them? Three checks say it's the policy:

1. **It isn't the screen.** With Claude reading every posting and no Jev, it allowed almost the same fraud (38 against 39, on the 300 development postings).
2. **Changing the policy catches some.** v2 adds §6, for a company's text copied with no profile or logo of its own. It catches 7 of the 41, at the cost of 13 more legitimate postings sent to review. (It caught more on the development postings, but §6 was written from those, so this test set is the fair measure.)
3. **The real signal is the employer.** 27 of the 41 share their company profile with other postings that are all fraud, and no legitimate posting in the test set does. Checking the employer's history would catch them with no new false alarms: 86 of 100 fraud flagged. That's the next thing to build. (An estimate from the dataset's labels; in production, the history would be the marketplace's confirmed takedowns.)

## The policy change, without code

Publishing a new policy version changes labels with no code change. Each version below was run on the same 100 development postings with real models, to see how many labels it changes and what the re-label costs:

| Version | What changed | Labels that changed | Of these, from the edit | Cost of the re-label |
| --- | --- | --- | --- | --- |
| v2 | adds §6, impersonated employer | 13 | 7 | $0.41 (full) |
| v3 | §5 relaxed when the logo is shown | 8 | 6 | $0.42 (full) |
| v4 | §4 sends to review instead of VIOLATING | 1 | 1 | $0.00 (redecide) |

"From the edit" counts changes that involve a section the version changed. The rest are Claude answering differently when asked the same thing again; the Test report separates the two before anyone publishes. v4 costs nothing: only what §4 leads to changed, not what Claude is asked, so the stored answers were decided again in code.

**Hand-written cases,** run with real models on every change to the agent or policy: policy changes under v1 5 of 5, v2 5 of 5, v3 5 of 5, v4 5 of 5, prompt injection 5 of 5, edge cases 8 of 8, all passed.

## Other set-ups (development postings only)

Three ways to run the agent, compared on the 300 development postings. The 400 were run once, with the chosen set-up, so they stay a clean test:

| Set-up | Precision | Recall | F1 | Cost per 1,000 | Typical posting | Slowest 5% |
| --- | --- | --- | --- | --- | --- | --- |
| Jev screen, then Claude Sonnet (chosen) | 0.51 | 0.48 | 0.49 | $3.26 | 0.3 s | 5.7 s |
| Claude Sonnet on every posting | 0.51 | 0.49 | 0.50 | $7.36 | 4.8 s | 5.8 s |
| Claude Haiku screen, then Sonnet (when Jev is down) | 0.53 | 0.49 | 0.51 | $4.72 | 5.8 s | 8.5 s |

The screen changes cost and speed, not quality: all three land within a few points of each other, inside the noise. Running Claude on every posting costs 2.3 times as much and is slower for a typical posting; the Haiku screen, used only while Jev is down, is the slowest.

## Error analysis

Nine postings the agent got wrong, read by hand after the runs (`eval/error_analysis.yaml`). Most missed fraud is a clean ad from an employer whose other postings are fraud. Most false alarms are short agency ads with no company named, which §5 sends to review: under v1, 44 of the 45 legitimate postings sent to review were §5. Two are cases where the dataset's own label is debatable.

| Posting | Dataset says | Agent | Why |
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
- **Times are from a laptop,** with the model APIs over the public internet; the load test ran up to 48 parallel jobs on one machine.
