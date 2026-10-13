-- FaST plans: plan, crop sheets, parcels, planned applications, results, findings, audit log.
-- Idempotent: every statement can run again on an existing schema.
CREATE SCHEMA IF NOT EXISTS fast;

CREATE TABLE IF NOT EXISTS fast.plans (
    id                UUID PRIMARY KEY,
    tenant_id         TEXT NOT NULL,
    farm              TEXT NOT NULL,          -- AgriFarm URN, or 'tenant' when the parcels have none (D5)
    campaign          INTEGER NOT NULL CHECK (campaign BETWEEN 2000 AND 2100),
    version           INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    state             TEXT NOT NULL
                      CHECK (state IN ('draft', 'calculated', 'in_review', 'signed', 'superseded')),
    supersedes        UUID REFERENCES fast.plans (id),
    row_version       INTEGER NOT NULL DEFAULT 1,
    inputs_changed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    calculated_at     TIMESTAMPTZ,
    rain              JSONB,
    created_by        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, farm, campaign, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS plans_one_open_per_campaign
    ON fast.plans (tenant_id, farm, campaign) WHERE state <> 'superseded';
CREATE INDEX IF NOT EXISTS plans_tenant_campaign_ix ON fast.plans (tenant_id, campaign);

CREATE TABLE IF NOT EXISTS fast.crop_sheets (
    id        UUID PRIMARY KEY,
    plan_id   UUID NOT NULL REFERENCES fast.plans (id) ON DELETE CASCADE,
    key       TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    inputs    JSONB NOT NULL,
    overrides JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (plan_id, key),
    UNIQUE (plan_id, seq)
);

CREATE TABLE IF NOT EXISTS fast.sheet_parcels (
    sheet_id   UUID NOT NULL REFERENCES fast.crop_sheets (id) ON DELETE CASCADE,
    ord        INTEGER NOT NULL,       -- the client's order: the first parcel decides crop and soil
    parcel_urn TEXT NOT NULL,
    sigpac     TEXT,
    PRIMARY KEY (sheet_id, parcel_urn)
);

CREATE TABLE IF NOT EXISTS fast.applications (
    id       UUID PRIMARY KEY,
    sheet_id UUID NOT NULL REFERENCES fast.crop_sheets (id) ON DELETE CASCADE,
    seq      INTEGER NOT NULL,
    data     JSONB NOT NULL,
    UNIQUE (sheet_id, seq)
);

CREATE TABLE IF NOT EXISTS fast.results (
    sheet_id             UUID PRIMARY KEY REFERENCES fast.crop_sheets (id) ON DELETE CASCADE,
    result               JSONB NOT NULL,
    applications_summary JSONB NOT NULL,
    calculated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fast.findings (
    id         BIGSERIAL PRIMARY KEY,
    plan_id    UUID NOT NULL REFERENCES fast.plans (id) ON DELETE CASCADE,
    sheet_id   UUID REFERENCES fast.crop_sheets (id) ON DELETE CASCADE,
    rule_id    TEXT NOT NULL,
    severity   TEXT NOT NULL CHECK (severity IN ('block', 'warn', 'info')),
    params     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS findings_plan_ix ON fast.findings (plan_id);

-- Append-only: no foreign key cascade, plans are never deleted.
CREATE TABLE IF NOT EXISTS fast.audit_log (
    id      BIGSERIAL PRIMARY KEY,
    plan_id UUID NOT NULL REFERENCES fast.plans (id),
    at      TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    user_id TEXT NOT NULL,
    action  TEXT NOT NULL,
    detail  JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS audit_log_plan_ix ON fast.audit_log (plan_id, at);
