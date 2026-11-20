import asyncio
import json

import psycopg
import pytest

from app import db


async def test_schema_applies_twice(fresh_db_url):
    async with await psycopg.AsyncConnection.connect(fresh_db_url) as conn:
        await db.apply_schema(conn)
        await db.apply_schema(conn)  # a restart applies it again: nothing may fail
        rows = await conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = {row[0] for row in await rows.fetchall()}
    assert {"policy_versions", "postings", "batches", "jobs", "labels", "decisions"} <= tables


async def test_two_processes_applying_the_schema_at_once_do_not_race(fresh_db_url):
    """The spike crashed with UniqueViolation when two processes created tables together."""

    async def apply():
        async with await psycopg.AsyncConnection.connect(fresh_db_url) as conn:
            await db.apply_schema(conn)

    await asyncio.gather(apply(), apply(), apply())


async def insert_policy(conn, name: str, status: str) -> None:
    await conn.execute(
        "INSERT INTO policy_versions (name, status, body, content_hash, model_hash, author)"
        " VALUES (%s, %s, %s, 'c', 'm', 'editor')",
        (name, status, json.dumps({"version": name})),
    )


async def test_a_published_policy_cannot_be_edited(fresh_db_url):
    async with await psycopg.AsyncConnection.connect(fresh_db_url, autocommit=True) as conn:
        await db.apply_schema(conn)
        await insert_policy(conn, "v1", "live")
        with pytest.raises(psycopg.errors.RaiseException, match="published and cannot be edited"):
            await conn.execute("UPDATE policy_versions SET body = '{}' WHERE name = 'v1'")
        await conn.execute("UPDATE policy_versions SET status = 'retired' WHERE name = 'v1'")  # allowed


async def test_a_draft_can_be_edited(fresh_db_url):
    async with await psycopg.AsyncConnection.connect(fresh_db_url, autocommit=True) as conn:
        await db.apply_schema(conn)
        await insert_policy(conn, "v2", "draft")
        await conn.execute("UPDATE policy_versions SET body = '{\"edited\": true}' WHERE name = 'v2'")


async def test_only_one_version_is_live(fresh_db_url):
    async with await psycopg.AsyncConnection.connect(fresh_db_url, autocommit=True) as conn:
        await db.apply_schema(conn)
        await insert_policy(conn, "v1", "live")
        with pytest.raises(psycopg.errors.UniqueViolation):
            await insert_policy(conn, "v2", "live")
