"""The FastAPI app: the intake API (/v1), the analyst API (/ui), health, and the built UI.

At startup it creates the tables (and LangGraph's checkpoint tables) and inserts policy v1. It is
the only process that does: the worker starts once the API reports healthy.

Run: uv run uvicorn app.api.main:app
"""

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config, db, store
from app import queue as jobs
from app.agent import checkpoints
from app.agent.configs import missing_keys, worker_config
from app.agent.graph import build
from app.api import analyst, intake

log = logging.getLogger("app.api")

MAX_BODY_BYTES = 10 * 1024 * 1024  # a full batch of 500 dataset postings is about 2.5 MB
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
API_PREFIXES = ("v1", "ui", "policies", "health", "docs", "openapi.json")
ROUTERS = [intake.router, analyst.router]  # the route-walk test checks every route in these


def create_app(database_url: str | None = None) -> FastAPI:
    url = database_url or config.database_url()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pool = await db.open_pool(url)
        async with app.state.pool.connection() as conn:
            await db.apply_schema(conn)
            await store.bootstrap_policy(conn)
        await checkpoints.setup_checkpoints(url)
        saver, saver_pool = await checkpoints.open_checkpointer(url, max_size=4)
        app.state.graph = build(checkpointer=saver)  # the API only reads checkpoints, for the steps view
        try:
            yield
        finally:
            await saver_pool.close()
            await app.state.pool.close()

    app = FastAPI(title="Policy labeling API", lifespan=lifespan)
    app.add_middleware(BodyLimit, max_bytes=MAX_BODY_BYTES)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        """Every response carries a request id. A crash becomes a 500 with the code and the id only;
        the details go to the log. (Caught here, so the 500 gets the header too.)"""
        request.state.request_id = uuid.uuid4().hex[:12]
        try:
            response = await call_next(request)
        except Exception as error:  # noqa: BLE001
            log.error("request %s failed: %s", request.state.request_id, type(error).__name__, exc_info=error)
            response = JSONResponse({"error": "internal_error", "request_id": request.state.request_id}, 500)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    # Errors carry a code and the request id, never the submitted text.
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return JSONResponse(
            {"error": error.detail, "request_id": _rid(request)}, error.status_code, headers=error.headers
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError):
        # Which field and why, but not the submitted value: it could be posting text.
        details = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in error.errors()]
        return JSONResponse(
            {"error": "invalid_request", "details": details, "request_id": _rid(request)}, 422
        )

    @app.get("/health")
    async def health(request: Request):
        """Public. live_labeling is false when the worker's API keys are missing: postings are
        accepted and queued, but nothing is labeled until the keys are set."""
        agent = worker_config()
        missing = missing_keys(agent)
        async with request.app.state.pool.connection() as conn:
            queue = await jobs.counts(conn)
        return {
            "status": "ok",
            "live_labeling": not missing,
            "missing_keys": missing,
            "agent_config": agent.name,
            "llm_backend": config.llm_backend(),
            "jobs": queue,
        }

    for router in ROUTERS:
        app.include_router(router)
    _serve_ui(app)
    return app


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _serve_ui(app: FastAPI) -> None:
    """The built React app (web/dist), on the same origin. Any other GET returns index.html, so a
    browser refresh on /labels/12 loads the UI instead of a 404, while unknown API paths stay 404."""
    if (WEB_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def ui(path: str):
        if path.split("/", 1)[0] in API_PREFIXES:
            raise HTTPException(404, "not_found")
        index = WEB_DIST / "index.html"
        if not index.is_file():
            return JSONResponse({"error": "ui_not_built"}, 404)
        return FileResponse(index)


class BodyLimit:
    """413 for a request body over max_bytes, before it is parsed. Checks the declared length first,
    then counts the bytes as they arrive, since a client can send a body without declaring it."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope["headers"]).get(b"content-length")
        if declared and int(declared) > self.max_bytes:
            response = JSONResponse({"error": "request_too_large"}, 413)
            return await response(scope, receive, send)
        received = 0

        async def counted():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HTTPException(413, "request_too_large")
            return message

        await self.app(scope, counted, send)


app = create_app()
