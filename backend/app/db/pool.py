"""asyncpg pool of the FaST schema. POSTGRES_URL is mandatory: there is no fallback DSN."""
from __future__ import annotations

import json

import asyncpg
from fastapi import Request

SCHEMA = "fast"


async def _init_connection(conn: asyncpg.Connection) -> None:
    for type_name in ("json", "jsonb"):
        await conn.set_type_codec(type_name, encoder=json.dumps, decoder=json.loads,
                                  schema="pg_catalog")


async def create_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=10, command_timeout=30,
                                     server_settings={"search_path": f"{SCHEMA},public"},
                                     init=_init_connection)


def get_db(request: Request) -> asyncpg.Pool:
    """FastAPI dependency: the pool opened by the application lifespan."""
    return request.app.state.pool
