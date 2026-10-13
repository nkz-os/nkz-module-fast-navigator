import asyncpg

from app.db.migrate import MIGRATIONS_DIR, apply_migrations

TABLES = {"plans", "crop_sheets", "sheet_parcels", "applications", "results", "findings",
          "audit_log", "schema_migrations"}


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
        assert await apply_migrations(conn) == sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
        assert await apply_migrations(conn) == sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    finally:
        await conn.close()


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
        await c.execute("UPDATE plans SET state = 'superseded'")
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
