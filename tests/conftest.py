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
