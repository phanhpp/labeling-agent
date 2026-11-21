# Working on this repo

A system that labels job postings against a versioned fraud policy: a LangGraph agent (Jev screen, Claude Sonnet 5.5, quotes checked in code), a FastAPI API, a Postgres job queue and worker, and a React UI for analysts. [README.md](README.md) explains it; [DESIGN.md](DESIGN.md) is the AWS design (Part A).

## Commands

```
make up-fake seed     # the app with a stand-in model (no keys, no cost), plus sample data: http://localhost:8000
make demo             # the app with Claude: 100 development postings, v1 and v2 published, v2 live (needs keys in .env)
make api / make worker / make web    # run the parts from source, with reload (UI on :5173)
make test             # Python tests (models faked) and UI unit tests
make lint             # ruff, ruff format, TypeScript
make up-fake seed e2e # browser tests (Playwright) against a running sample stack
make reset            # delete the local demo database
make guardrails       # the API refusing bad requests and holding an injection, against the running app
make results          # rebuild RESULTS.md from eval/runs/ and check it matches
make load-test        # the 60 s target under the 5x peak and a burst (needs keys, about $1.50)
```

Python uses `uv` (`uv run pytest`, `uv run python -m scripts.<name>`); the UI uses `pnpm -C web`.

## Where things are

```
app/agent/    the graph: clean, cache, screen, escalate, check, decide (+ prompts, models, fakes)
app/api/      FastAPI: intake (/v1), analyst (/ui), policies (/policies)
app/          store.py (all SQL), queue.py, worker.py, versions.py (drafts, Test, Publish), auth.py
policies/     v1.yaml (the brief's policy) to v4.yaml
web/src/      the UI: pages/, components/, lib/ (pure helpers with unit tests)
eval/         run_eval.py, metrics, suites, thresholds.yaml, committed run files in eval/runs/
scripts/      data split, threshold fitting, demos, sample data
tests/        by area: agent, api, queue, policy, db, data, eval
```

## Rules

- **Data:** the 400 evaluation postings (`eval/eval_ids.txt`) and their 586 copies never go into the database, prompts, examples or any tuning. Development work uses the dev and Jev-fit splits in `data/splits.json`.
- **Tests:** model calls are faked in tests (`LLM_BACKEND=fake`); real-model tests are marked `e2e`. Every change comes with tests where it matters; run `make test` and `make lint` before a commit.
- **Policy is data:** never hard-code policy text in prompts or code; it is read from the version in the database at run time.
- **The label is set in code** (`app/agent/decide.py`), never by the model. Evidence must be verbatim (`app/agent/check.py`).
- **Git:** a branch and a pull request per change; merge with `gh pr merge <n> --squash` only when CI is green. Never push to `main`. Commit messages are one line, with no AI attribution.
- **Don't edit `DESIGN.md`** (the author's own); list corrections instead. `docs/` is private notes and is git-ignored.
- **Writing:** plain English, short sentences, no em dashes, in docs, UI text and comments.
- **Secrets:** keys live only in `.env` (never committed); never print them.
