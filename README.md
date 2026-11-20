# Policy labeling agent

Labels job postings against a versioned fraud policy: **VIOLATING**, **NEEDS_REVIEW** or **ALLOWED**, with the policy sections it rests on, verbatim quotes as evidence, a rationale and a confidence.

The idea in one line: **a model reads the posting and points at evidence; code checks the evidence and sets the label.** The model never sets the label, quotes are verified against the posting, and no failure ends in a silent ALLOWED.

Part A (the AWS design) is in [DESIGN.md](DESIGN.md). This repo is Part B: the same system, running locally. Results on the fixed 400 are in [RESULTS.md](RESULTS.md).

## Run it

```
cp .env.example .env            # add ANTHROPIC_API_KEY and TYPESAFE_API_KEY to label for real
docker compose up --wait        # db, api (serves the UI) and worker
open http://localhost:8000
```

- **No keys:** everything starts, postings are accepted and wait in the queue, and the UI says live labeling is off.
- **No model calls at all:** `LLM_BACKEND=fake docker compose up --wait`, then `uv run python -m scripts.seed_fixtures` loads 14 postings, a decision and a draft policy to play with.
- **Start clean** (for example before a demo): `docker compose down -v`.

## How a posting is labeled

```
posting ──► API: validate, save, queue ──► worker runs the agent (LangGraph):

  clean        decode entities, drop hidden HTML and invisible characters
    │
  cache        same text, same policy, same models? reuse the stored label
    │
  screen       injection phrase (regex)? ─────────────► NEEDS_REVIEW, no model reads it
    │          Jev: injection score ≥ 0.5? ───────────► NEEDS_REVIEW, Sonnet never reads it
    │          Jev: every section < 0.17, no red flag? ► ALLOWED, no Sonnet (cleared)
    │
  escalate     Sonnet 5.5 reads the policy and the posting: per section, matched / unsure /
    │          not matched, with quotes and missing fields (no tools, posting fenced as data)
  check        every quote must be found in the posting, or it is dropped;
    │          a VIOLATING section with no verified quote becomes unsure
  decide       code applies the policy: VIOLATING if a VIOLATING section matched,
               NEEDS_REVIEW if a section matched (§5) or is unsure, else ALLOWED
```

- Each step is checkpointed in Postgres: a worker that dies resumes without repeating finished steps, and the UI shows each run step by step.
- Jev (TypeSafe) is a fast classifier: one call answers a yes/no question per section plus an injection question. If it is down, Haiku screens instead; if both are down, Sonnet labels.
- The policy is data (`policies/v1.yaml`), read at run time. Section texts, decision rule and edge cases are the brief's words.

## Results on the fixed 400

Filled in by `eval/report.py`; see [RESULTS.md](RESULTS.md). On the 300 development postings (not the 400), the chosen config `jev_sonnet` had:

- **No legitimate posting labeled VIOLATING** (strict precision 1.0), but few fraud postings show a policy violation: most fraud in this dataset matches no section, so it is ALLOWED or held for review.
- **Main recall 0.48, precision 0.51** (fraud counted as caught when VIOLATING or NEEDS_REVIEW), review load 22%.
- **$3.26 per 1,000 postings**, p50 0.3 s, p95 5.7 s. The Jev screen skips Sonnet for 56% of postings and cuts cost by 56% against Sonnet alone ($7.36).
- 96% of the model's quotes verified; the rest were dropped, never used as evidence.

## How the two thresholds were set

**Jev cut-off (0.17): when may a posting skip Sonnet?** `scripts/fit_cutoff.py`
- Fitted for agreement with Sonnet: the largest cut-off at which at most 2% of the postings Sonnet flags would be cleared. Result: 1 of 72 on dev, 1 of 57 on held-out postings.
- The first target, "at most 2% of fraud cleared", was not reachable: much fraud matches no section, so Jev scores it low, correctly for the policy.

**Injection threshold (0.5): when is a posting held without any model reading it?** `scripts/fit_injection.py`
- 3,852 ordinary postings, and 600 with one of 10 hand-written injections added (4 kept out of the fitting).
- The lowest threshold that flags at most 0.1% of ordinary postings. Lowest, because a missed injection could be cleared as ALLOWED, while a false flag only costs one review.
- Result: 3 of 3,852 ordinary postings flagged, 100% of injections caught, held-out wording included. Fitting also showed fake verdicts (`"label": "ALLOWED"`) slipping through, so the Jev question and the regex now cover them.

## Changing the policy

A new version goes through the API (or the UI), never through code: draft, **Test** (labels recent postings in shadow and reports what flips), **Publish** (by a publisher who didn't edit it), re-label, and rollback if needed. `scripts/demo_versions.py` runs it with real models on 100 development postings:

```
v2  adds §6, impersonated employer      full re-label   13 flips (7 from the change)   $0.41
v3  narrows §5: logo shown is enough    full re-label    8 flips (6 from the change)   $0.42
v4  §4 becomes NEEDS_REVIEW             decided in code  1 flip                        $0.00, 0 model calls
```

v4 changes only an effect, which the models never see, so the stored answers are decided again in code. A full re-label also shows Sonnet's run-to-run variation (about 6 in 100), so each flip says whether it involves a changed section.

## Guardrails

- **API:** schema checks, 413 for oversized bodies, batches checked item by item, idempotent submits (409 on a changed duplicate), a role on every route (a test walks them all), clients see only their own postings (404 otherwise), rate limits, errors without details, no posting text in logs.
- **Agent:** cleaning drops hidden text; the posting is fenced as data; injection goes to review before any labeling model; no tools; quotes verified; code sets the label; timeouts and retries; a dead job ends as NEEDS_REVIEW (`dlq`).
- **UI and storage:** postings shown as text, never HTML; parameterised SQL; published policies frozen by a trigger; checkpoints load only safe types.
- **Residual risk:** an injection worded unlike anything tested could score under 0.5 and be cleared. With Jev and Haiku both down, Sonnet reads postings only the regex has checked.

## Part A on AWS, Part B here

| Part A | Part B |
| --- | --- |
| API Gateway, Intake and Analyst services | One FastAPI app (`app/api/`) |
| SQS live, backfill, dead-letter queues | `jobs` table with `FOR UPDATE SKIP LOCKED` (`app/queue.py`) |
| ECS workers | `worker` container, async, 4 jobs at a time |
| Aurora, S3, AppConfig | Postgres: postings, labels, policy versions, checkpoints |
| Bedrock | Anthropic API (Sonnet 5.5, Haiku 5.5) and TypeSafe Jev |
| Cognito | Demo bearer tokens; the UI's "acting as" menu picks one |
| CloudFront | The API serves the built UI on the same origin |
| SNS webhooks, phased rollout | Not built: clients poll, and Test runs in shadow |

## Repository

```
app/agent/     the graph and its steps: clean, screen, escalate, check, decide
app/api/       intake (/v1), analyst (/ui), policies (/policies)
app/           queue, worker, store (all SQL), versions (draft, Test, Publish)
policies/      v1 to v4
web/           the analyst UI (React)
eval/          run_eval.py, metrics, suites, thresholds, run files
scripts/       data split, threshold fitting, demos, seeding
tests/         by area: agent, api, queue, policy, db, data, eval
```

## Tests and CI

- `uv run pytest` (248 tests, models faked) and `pnpm -C web test` / `test:e2e` (Playwright against the real containers).
- CI on every pull request: tests with Postgres, the fresh-clone path without keys, and the UI in a browser. Changes to the agent, policies or eval also run the eval gate with real models: the edge-case, adversarial and policy-change suites must pass in full, and a 50-posting sample must meet its marks.
- The data split (`data/splits.json`) keeps the 400 eval postings, and 586 copies of them, out of all development and tuning.
