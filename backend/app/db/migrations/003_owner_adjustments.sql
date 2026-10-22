-- Owner adjustments to 05c: justified N adjustment per sheet (annex III-I.3) and the holder's
-- qualification (art. 21.3). Idempotent.
ALTER TABLE fast.crop_sheets ADD COLUMN IF NOT EXISTS n_adjustment JSONB;

CREATE TABLE IF NOT EXISTS fast.holder_qualifications (
    tenant_id     TEXT PRIMARY KEY,
    holder_name   TEXT NOT NULL,
    qualification TEXT NOT NULL,
    reference     TEXT NOT NULL,
    updated_by    TEXT NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The open-plan index also covers in_review; a database that ran an older 001 has the old
-- predicate, and CREATE INDEX IF NOT EXISTS would keep it.
DROP INDEX IF EXISTS fast.plans_one_open_per_campaign;
CREATE UNIQUE INDEX IF NOT EXISTS plans_one_open_per_campaign
    ON fast.plans (tenant_id, farm, campaign) WHERE state IN ('draft', 'calculated', 'in_review');
CREATE UNIQUE INDEX IF NOT EXISTS plans_one_signed_per_campaign
    ON fast.plans (tenant_id, farm, campaign) WHERE state = 'signed';

-- Holder's declaration (art. 4.2): irrigated unit sown or planted 1-Mar..30-Jun 2026.
-- NULL = not declared (FaST assumes yes, fail-safe).
ALTER TABLE fast.plans ADD COLUMN IF NOT EXISTS irrigated_spring_2026 BOOLEAN;

-- Same guard as 002 with the new declaration frozen too (the trigger already exists).
CREATE OR REPLACE FUNCTION fast.guard_signed_plan() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.state = 'superseded' THEN
        RAISE EXCEPTION 'plan % is superseded and cannot change', OLD.id;
    END IF;
    IF OLD.state = 'signed' AND (
            NEW.state <> 'superseded'
            OR NEW.id IS DISTINCT FROM OLD.id
            OR NEW.created_by IS DISTINCT FROM OLD.created_by
            OR NEW.created_at IS DISTINCT FROM OLD.created_at
            OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
            OR NEW.farm IS DISTINCT FROM OLD.farm
            OR NEW.campaign IS DISTINCT FROM OLD.campaign
            OR NEW.version IS DISTINCT FROM OLD.version
            OR NEW.supersedes IS DISTINCT FROM OLD.supersedes
            OR NEW.inputs_changed_at IS DISTINCT FROM OLD.inputs_changed_at
            OR NEW.calculated_at IS DISTINCT FROM OLD.calculated_at
            OR NEW.rain IS DISTINCT FROM OLD.rain
            OR NEW.vulnerable_zone IS DISTINCT FROM OLD.vulnerable_zone
            OR NEW.vulnerable_zone_source IS DISTINCT FROM OLD.vulnerable_zone_source
            OR NEW.voluntary_digital_notebook IS DISTINCT FROM OLD.voluntary_digital_notebook
            OR NEW.irrigated_spring_2026 IS DISTINCT FROM OLD.irrigated_spring_2026
            OR NEW.signature IS DISTINCT FROM OLD.signature
            OR NEW.snapshot IS DISTINCT FROM OLD.snapshot
            OR NEW.snapshot_sha256 IS DISTINCT FROM OLD.snapshot_sha256
            OR NEW.signed_at IS DISTINCT FROM OLD.signed_at) THEN
        RAISE EXCEPTION 'plan % is signed: it can only be superseded', OLD.id;
    END IF;
    RETURN NEW;
END $$;
