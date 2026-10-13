import asyncpg
import pytest

from app.db.migrate import MIGRATIONS_DIR, apply_migrations

TABLES = {"advisors", "plans", "crop_sheets", "sheet_parcels", "applications", "results", "findings",
          "audit_log", "schema_migrations", "holder_qualifications"}


async def test_migrations_create_the_schema(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'fast'")
        assert TABLES <= {r["table_name"] for r in rows}
        applied = await conn.fetch("SELECT name FROM fast.schema_migrations")
        assert {r["name"] for r in applied} == {p.name for p in MIGRATIONS_DIR.glob("*.sql")}
    finally:
        await conn.close()


async def test_migrations_are_idempotent(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        assert await apply_migrations(conn) == []     # the fixture applied them all
        assert await apply_migrations(conn) == []
        await conn.execute("DELETE FROM fast.schema_migrations")
        assert await apply_migrations(conn) == sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    finally:
        await conn.close()


async def test_a_recorded_migration_is_not_run_again(pg_url, tmp_path, monkeypatch):
    (tmp_path / "900_probe.sql").write_text(
        "CREATE TABLE IF NOT EXISTS fast.mig_probe (n INTEGER); "
        "INSERT INTO fast.mig_probe VALUES (1);", encoding="utf-8")
    monkeypatch.setattr("app.db.migrate.MIGRATIONS_DIR", tmp_path)
    conn = await asyncpg.connect(pg_url)
    try:
        assert await apply_migrations(conn) == ["900_probe.sql"]
        assert await apply_migrations(conn) == []
        assert await conn.fetchval("SELECT count(*) FROM fast.mig_probe") == 1
    finally:
        await conn.execute("DROP TABLE IF EXISTS fast.mig_probe")
        await conn.execute("DELETE FROM fast.schema_migrations WHERE name = '900_probe.sql'")
        await conn.close()


def test_start_up_migrates_on_a_connection_without_a_command_timeout(pg_url, monkeypatch):
    from fastapi.testclient import TestClient

    from app import main
    from app.config import get_settings

    seen = []
    real = main.apply_migrations

    async def spy(conn):
        seen.append(conn._config.command_timeout)
        return await real(conn)

    monkeypatch.setenv("POSTGRES_URL", pg_url)
    monkeypatch.setattr(main, "apply_migrations", spy)
    get_settings.cache_clear()
    try:
        with TestClient(main.app):
            pass
    finally:
        get_settings.cache_clear()
    assert seen == [None]


async def test_one_open_plan_per_farm_and_campaign(pool):
    async with pool.acquire() as c:
        insert = ("INSERT INTO plans (id, tenant_id, farm, campaign, state, created_by) "
                  "VALUES (gen_random_uuid(), 't', 'tenant', 2027, $1, 'u')")
        await c.execute(insert, "draft")
        try:
            await c.execute(insert, "draft")
            raise AssertionError("a second open plan was accepted")
        except asyncpg.UniqueViolationError:
            pass
        await c.execute("UPDATE plans SET state = 'superseded', signature = '{}', "
                        "snapshot = '{}', snapshot_sha256 = 'x', signed_at = now()")
        await c.execute("INSERT INTO plans (id, tenant_id, farm, campaign, version, state, created_by) "
                        "VALUES (gen_random_uuid(), 't', 'tenant', 2027, 2, 'draft', 'u')")


async def test_states_are_constrained(pool):
    async with pool.acquire() as c:
        try:
            await c.execute("INSERT INTO plans (id, tenant_id, farm, campaign, state, created_by) "
                            "VALUES (gen_random_uuid(), 't', 'tenant', 2027, 'nonsense', 'u')")
            raise AssertionError("an unknown state was accepted")
        except asyncpg.CheckViolationError:
            pass


async def test_json_round_trips(pool):
    async with pool.acquire() as c:
        plan_id = await c.fetchval(
            "INSERT INTO plans (id, tenant_id, farm, campaign, state, created_by, rain) "
            "VALUES (gen_random_uuid(), 't', 'tenant', 2027, 'draft', 'u', $1) RETURNING id",
            {"annual_mm": 512.5, "years": [2016, 2017]})
        assert await c.fetchval("SELECT rain FROM plans WHERE id = $1", plan_id) == {
            "annual_mm": 512.5, "years": [2016, 2017]}


async def test_the_audit_log_is_append_only(pool):
    async with pool.acquire() as c:
        plan_id = await c.fetchval(
            "INSERT INTO plans (id, tenant_id, farm, campaign, state, created_by) "
            "VALUES (gen_random_uuid(), 't', 'tenant', 2027, 'draft', 'u') RETURNING id")
        await c.execute("INSERT INTO audit_log (plan_id, user_id, action) VALUES ($1, 'u', 'x')",
                        plan_id)
        for statement in ("UPDATE audit_log SET action = 'y'", "DELETE FROM audit_log"):
            with pytest.raises(asyncpg.RaiseError):
                await c.execute(statement)
        assert await c.fetchval("SELECT action FROM audit_log") == "x"


async def test_the_open_plan_index_is_replaced_on_a_database_that_had_the_old_one(pg_url):
    conn = await asyncpg.connect(pg_url)
    try:
        await conn.execute("DROP INDEX IF EXISTS fast.plans_one_open_per_campaign")
        await conn.execute("CREATE UNIQUE INDEX plans_one_open_per_campaign ON fast.plans "
                           "(tenant_id, farm, campaign) WHERE state IN ('draft', 'calculated')")
        await conn.execute("DELETE FROM fast.schema_migrations WHERE name = "
                           "'003_owner_adjustments.sql'")
        assert await apply_migrations(conn) == ["003_owner_adjustments.sql"]
        defn = await conn.fetchval("SELECT indexdef FROM pg_indexes WHERE schemaname = 'fast' "
                                   "AND indexname = 'plans_one_open_per_campaign'")
        assert "in_review" in defn
    finally:
        await conn.close()
