# Policy labeling agent

Reads a job posting and decides whether it breaks a fraud policy. For each posting it gives one of three labels, the policy sections behind it, and the exact sentences from the posting that show it. For example:

```json
{
  "job_id": "fx-fee",
  "label": "VIOLATING",
  "policy_sections": ["§1"],
  "evidence": ["registration fee of $120 for your tools."],
  "rationale": "The applicant must pay $120 before the first shift: an advance fee under §1.",
  "confidence": 0.93,
  "policy_version": "v1"
}
```

- **VIOLATING:** the posting matches a section of the policy, for example it asks the applicant to pay a fee.
- **NEEDS_REVIEW:** not clear enough to decide, so an analyst looks at it.
- **ALLOWED:** nothing in the policy matches.

The key idea: **a model reads the posting and points at the evidence; plain code checks that evidence and sets the label.** Every quote must really be in the posting, the model never chooses the label itself, and when anything fails the posting goes to review, never quietly to ALLOWED.

The design for running this on AWS is in [DESIGN.md](DESIGN.md). This repo runs the same system on your machine.

## Run it

You need Docker. For development also [uv](https://docs.astral.sh/uv/) (Python) and pnpm (Node).

```
cp .env.example .env     # then add ANTHROPIC_API_KEY and TYPESAFE_API_KEY to label for real
make up                  # starts the database, the API and the worker in Docker
open http://localhost:8000
```

- **Without keys** it still starts: postings are accepted and wait in a queue, and the page says labeling is off.
- **To try it with no keys and no cost:** `make up-fake seed`. A fake model labels by simple word rules, and `seed` adds 14 sample postings, an analyst decision and a draft policy.
- **To stop:** `make down`. Your data is kept for next time.
- **To reset the demo:** `make reset` deletes the local demo database (the Docker volume on your machine), so the next `make up` starts empty. The demo scripts need this.

### Running the parts separately (development)

Three terminals, each reloading when you change code:

```
make api       # Postgres in Docker, then the API from source:   http://localhost:8000
make worker    # the worker that labels queued postings
make web       # the UI with hot reload:                         http://localhost:5173
```

The UI on :5173 forwards its API calls to :8000. In `make up` there is no separate UI server: the API serves the built UI itself.

Every `make` target is one or two plain commands; see the [Makefile](Makefile).

## How a posting is labeled

```
posting
   │
   ▼
API          checks the fields, saves the posting, puts a job in the queue
   │
   ▼
worker       takes the job and runs these steps:

  clean      remove hidden HTML text and invisible characters
  cache      seen this exact posting under this policy before? reuse that label
  screen     a phrase like "ignore previous instructions"?   → NEEDS_REVIEW, no model reads it
             Jev, a fast classifier, scores each section:
               looks like an injection (score ≥ 0.5)?        → NEEDS_REVIEW, no model reads it
               every section clearly unlikely (< 0.17)?      → ALLOWED, no need for Claude
  escalate   otherwise Claude (Sonnet 5.5) reads the policy and the posting, and for each section
             answers matched / unsure / not matched, with quotes
  check      each quote is looked up in the posting; one that isn't there is thrown away
  decide     code sets the label from the checked answer:
               a VIOLATING section matched with a real quote → VIOLATING
               a section unsure, or §5 (unknown employer)    → NEEDS_REVIEW
               nothing matched                               → ALLOWED
```

- Each step is saved as it finishes. A worker that crashes picks up where it stopped, and the UI shows every step of every posting.
- The policy itself is a file, `policies/v1.yaml`, read while running. Changing it needs no code change (see "Changing the policy").

## How well it works

The dataset (17,880 postings, about 5% fraud) comes with a fixed test set of 400 postings chosen by the assignment, 100 of them fraud. Those 400 are kept apart: nothing was tuned on them. The final results on them are in [RESULTS.md](RESULTS.md).

All tuning used 300 other postings: 75 fraud, 225 legitimate. This is where they ended up, with Jev screening and Claude labeling:

| | Labeled VIOLATING | Sent to an analyst | Labeled ALLOWED |
| --- | --- | --- | --- |
| 75 fraud postings | 5 | 31 | 39 |
| 225 legitimate postings | 0 | 35 | 190 |

- **No legitimate posting is labeled VIOLATING.** When the system says VIOLATING, it can show the sentence that breaks the policy.
- **Analysts check 66 of the 300 postings (22%).** Most are there because the posting has no company profile, so the employer can't be identified (§5). About half of them are fraud.
- **39 fraud postings are labeled ALLOWED**, because nothing in their text breaks the policy: no fee, no request for bank details, no unrealistic pay. They read like ordinary job ads. Catching them takes a new policy section; v2's §6 is a first step (see "Changing the policy").
- **Cost: about a third of a cent per posting** ($3.26 per 1,000). Jev clears about half the postings in 0.3 s, almost for free. The rest go to Claude, which takes about 5 s and costs about $0.007 each. Sending every posting to Claude would cost $7.36 per 1,000.
- **Every piece of evidence shown is a real quote.** Claude quoted 130 sentences as evidence; 125 were found word for word in the posting. The other 5 couldn't be found word for word, so they were discarded and never shown.

## How the two thresholds were chosen

**When may a posting skip Claude? Jev score under 0.17 on every section.**
The threshold was set so that Jev agrees with Claude: at most 2% of the postings Claude would flag get cleared without it. On new postings, 1 in 57 was. (`scripts/fit_cutoff.py`)

**When is a posting held as a possible injection? Jev injection score of 0.5 or more.**
- **Data:** 3,852 ordinary postings, and 600 postings with one of 10 hand-written injection attempts added. Four of the attempts were kept out of the tuning, to check it works on new wording.
- **Rule:** the lowest threshold that holds at most 1 in 1,000 ordinary postings. Lowest, because a missed injection could slip through as ALLOWED, while a false alarm only costs one review.
- **Result:** 3 of 3,852 ordinary postings held, and every injection caught, the new wording included. (`scripts/fit_injection.py`)

## Changing the policy

A new policy version goes through the UI or the API, with no code change:

1. **Draft:** an editor copies the live version and edits it.
2. **Test:** recent postings are labeled under the draft in the background, and a report lists every posting whose label would change.
3. **Publish:** a publisher who did not edit the draft makes it live (four eyes).
4. **Re-label:** recent postings get labels under the new version. Until then, reads say the old label is out of date.
5. **Roll back** if needed: the old labels are still stored.

`make demo-versions` runs three versions with Claude on 100 postings:

```
v2   adds §6: a company's text copied, with no profile or logo      13 results change   $0.41
v3   §5 relaxed: an empty profile is fine when the logo is shown      8 results change   $0.42
v4   §4 (unrealistic pay) goes to review instead of VIOLATING         1 result changes    $0.00
```

v4 costs nothing: only what the label does with §4 changed, not what Claude is asked, so the stored answers are simply decided again in code. Asking Claude twice doesn't always give the same answer, so the Test report marks which changes (label or sections) come from the policy edit (7 of 13 for v2) and which are Claude answering differently.

## Safety checks

- **API:** every field is checked, oversized requests are refused, each client sees only its own postings, every endpoint needs the right role (a test checks them all), and logs never contain posting text.
- **Model:** hidden text is removed before any model reads the posting; the posting is marked as data, not instructions; suspected injections never reach Claude; Claude has no tools; quotes are checked; code sets the label.
- **UI:** postings are shown as plain text, so HTML inside a posting never runs. Published policies can't be edited.
- **Known gap:** an injection worded unlike anything tested could score under 0.5 and be cleared. If Jev and its backup both fail, Claude reads postings that only the phrase check has seen.

## AWS design (DESIGN.md) vs this repo

| On AWS | Here |
| --- | --- |
| API Gateway and services | One FastAPI app |
| SQS queues | A `jobs` table in Postgres |
| ECS workers | The `worker` container |
| Aurora, S3, AppConfig | Postgres: postings, labels, policy versions, saved steps |
| Bedrock | Anthropic API (Claude) and TypeSafe (Jev) |
| Cognito sign-in | Demo users, picked with "Acting as" in the UI |
| CloudFront | The API serves the UI |
| Webhooks, gradual rollout | Not built: clients ask for labels, and Test runs in the background |

## Tests

- `make test`: 248 Python tests (with a fake model, so no keys needed) and the UI's unit tests.
- `make up-fake seed e2e`: browser tests on the running app, including the role check (a viewer can't edit, an editor can't publish, the person who edited a draft can't publish it).
- Every pull request runs all of these. Changes to the agent or the policy also run real-model checks: hand-written edge cases, injection attempts and policy changes must all pass, and a 50-posting sample must stay above its marks.

## Where things are

```
app/agent/    the labeling steps: clean, screen, escalate, check, decide
app/api/      the API: postings (/v1), labels (/ui), policies (/policies)
app/          queue, worker, database access, policy versions
policies/     the policy, v1 to v4
web/          the UI (React)
eval/         the evaluation: runner, metrics, test suites, results
scripts/      data split, threshold fitting, demos, sample data
tests/        Python tests, by area
```
