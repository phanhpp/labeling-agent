import os
import uuid

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from app import config


@pytest.fixture
def fresh_db_url():
    """A new, empty database for one test, dropped afterwards.

    Without a reachable Postgres the test is skipped locally, but fails in CI, where a skip would
    hide a broken setup.
    """
    admin_url = config.database_url()
    try:
        admin = psycopg.connect(admin_url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as error:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"Postgres not reachable at DATABASE_URL ({error}); run: docker compose up -d db")
    name = f"test_{uuid.uuid4().hex[:10]}"
    admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield make_conninfo(admin_url, dbname=name)
    finally:
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.close()


@pytest.fixture
async def api(fresh_db_url, monkeypatch):
    """The API app on a fresh database, started (tables, checkpoints, policy v1), with an httpx client.
    Model calls use the fake labeler. The app is on client.app."""
    import httpx

    from app import auth
    from app.agent.fake_models import FakeLabeler
    from app.api.main import create_app

    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setattr("app.agent.llm.chat", lambda profile: FakeLabeler(profile))
    auth._windows.clear()
    app = create_app(fresh_db_url)
    async with app.router.lifespan_context(app):
        # raise_app_exceptions=False: a crash comes back as the app's 500, as a real client sees it.
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            client.app = app
            yield client


@pytest.fixture
async def worker(api, fresh_db_url):
    """A worker on the same database, labeling with sonnet_only (the fake backend has no fake Jev)."""
    from app.agent import checkpoints
    from app.agent.configs import CONFIGS
    from app.worker import Worker

    saver, saver_pool = await checkpoints.open_checkpointer(fresh_db_url, max_size=4)
    try:
        yield Worker(api.app.state.pool, saver, CONFIGS["sonnet_only"], concurrency=4)
    finally:
        await saver_pool.close()
