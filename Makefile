# Short names for the commands in the README. Each line is the plain command; nothing is hidden.

.PHONY: up up-fake demo demo-draft seed down reset api worker web test e2e lint eval-dev guardrails results load-test demo-versions

up:            ## everything in Docker: db, api (serves the UI on :8000), worker
	docker compose up -d --build --wait

up-fake:       ## the same, with a fake model: no keys, no cost
	LLM_BACKEND=fake docker compose up -d --build --wait

demo:          ## a fresh stack: 100 real development postings labeled by Claude under v1, v2 tested and published, v3 as a draft (needs keys, about $0.75)
	docker compose down -v
	docker compose up -d --build --wait
	uv run python -m scripts.submit_postings --split dev --limit 100 --dataset-labels
	uv run python -m scripts.demo_draft --publish
	uv run python -m scripts.demo_draft --name v3 --file policies/v3.yaml

demo-draft:    ## load policy v3 (narrows §5) as an untested draft, to Test and publish in the UI
	uv run python -m scripts.demo_draft --name v3 --file policies/v3.yaml

seed:          ## load 14 sample postings, a decision and a draft policy (any running stack)
	uv run python -m scripts.seed_fixtures

down:          ## stop everything; the data is kept
	docker compose down

reset:         ## delete the local demo database (a Docker volume) so the next `make up` starts empty
	docker compose down -v

api:           ## development: Postgres in Docker, the API from source with reload, on :8000
	docker compose up -d --wait db
	uv run uvicorn app.api.main:app --reload --port 8000

worker:        ## development: the worker from source (needs `make api` running)
	uv run python -m app.worker

web:           ## development: the UI with hot reload on :5173 (calls the API on :8000)
	pnpm -C web install
	pnpm -C web dev

test:          ## Python tests (models faked) and UI unit tests
	uv run pytest -q
	pnpm -C web test

e2e:           ## browser tests against a running stack: make up-fake seed e2e
	pnpm -C web test:e2e

lint:
	uv run ruff check .
	uv run ruff format --check .
	pnpm -C web typecheck

eval-dev:      ## real models on 50 development postings (about $0.20)
	uv run python -m eval.run_eval --split dev --limit 50 --config jev_sonnet

guardrails:    ## show the API's guardrails (413, partial batch, 403, 404, injection) against the running app
	uv run python -m scripts.demo_guardrails

results:       ## write RESULTS.md from the committed eval runs (needs the dataset CSV); --check is the CI-style test
	uv run python -m eval.report
	uv run python -m eval.report --check

load-test:     ## the 60 s target through the real API and queue: the 5x peak for 30 s, then a burst of 200 (needs keys, about $1.50; adds the postings to the running app)
	uv run python -m scripts.load_test --rate 11.6 --seconds 30 --name peak
	uv run python -m scripts.load_test --burst 200 --name burst

demo-versions: ## the policy v2 to v4 demo with real models (needs a fresh stack with keys, about $1)
	uv run python -m scripts.demo_versions --limit 100
