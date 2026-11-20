# Short names for the commands in the README. Each line is the plain command; nothing is hidden.

.PHONY: up up-fake demo seed down reset api worker web test e2e lint eval-dev demo-versions

up:            ## everything in Docker: db, api (serves the UI on :8000), worker
	docker compose up -d --build --wait

up-fake:       ## the same, with a fake model: no keys, no cost
	LLM_BACKEND=fake docker compose up -d --build --wait

demo:          ## a fresh stack with 100 real development postings labeled by Claude (needs keys, about $0.35)
	docker compose down -v
	docker compose up -d --build --wait
	uv run python -m scripts.submit_postings --split dev --limit 100

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

demo-versions: ## the policy v2 to v4 demo with real models (needs a fresh stack with keys, about $1)
	uv run python -m scripts.demo_versions --limit 100
