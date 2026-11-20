# One image for the api and the worker (compose picks the command).

# The analyst UI, built to static files that the API serves on the same origin.
FROM node:24-slim AS web
RUN corepack enable
WORKDIR /web
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /srv
# Dependencies first, so a code change doesn't reinstall them. Runtime packages only.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY policies ./policies
COPY --from=web /web/dist ./web/dist

RUN useradd --create-home --uid 1000 labeler
USER labeler

EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
