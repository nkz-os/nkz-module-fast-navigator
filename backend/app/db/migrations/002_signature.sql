-- Declarations, signature, frozen copy, advisors; a signed plan cannot change. Idempotent.
ALTER TABLE fast.plans ADD COLUMN IF NOT EXISTS vulnerable_zone BOOLEAN;
ALTER TABLE fast.plans ADD COLUMN IF NOT EXISTS vulnerable_zone_source TEXT;
ALTER TABLE fast.plans ADD COLUMN IF NOT EXISTS voluntary_digital_notebook BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE fast.plans ADD COLUMN IF NOT EXISTS signature JSONB;
ALTER TABLE fast.plans ADD COLUMN IF NOT EXISTS snapshot JSONB;
ALTER TABLE fast.plans ADD COLUMN IF NOT EXISTS snapshot_sha256 TEXT;
ALTER TABLE fast.plans ADD COLUMN IF NOT EXISTS signed_at TIMESTAMPTZ;
ALTER TABLE fast.results ADD COLUMN IF NOT EXISTS assembled JSONB;

CREATE TABLE IF NOT EXISTS fast.advisors (
    tenant_id           TEXT NOT NULL,
    user_id             TEXT NOT NULL,
    name                TEXT NOT NULL,
    registration_number TEXT NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);

-- A signed plan only moves to superseded; a superseded plan never changes.
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
            OR NEW.signature IS DISTINCT FROM OLD.signature
            OR NEW.snapshot IS DISTINCT FROM OLD.snapshot
            OR NEW.snapshot_sha256 IS DISTINCT FROM OLD.snapshot_sha256
            OR NEW.signed_at IS DISTINCT FROM OLD.signed_at) THEN
        RAISE EXCEPTION 'plan % is signed: it can only be superseded', OLD.id;
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS plans_guard_signed ON fast.plans;
CREATE TRIGGER plans_guard_signed BEFORE UPDATE ON fast.plans
    FOR EACH ROW EXECUTE FUNCTION fast.guard_signed_plan();
DROP TRIGGER IF EXISTS plans_no_delete ON fast.plans;
CREATE OR REPLACE FUNCTION fast.reject_plan_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'plans are never deleted';
END $$;
CREATE TRIGGER plans_no_delete BEFORE DELETE ON fast.plans
    FOR EACH ROW EXECUTE FUNCTION fast.reject_plan_delete();

-- The content of a signed or superseded plan cannot change either.
CREATE OR REPLACE FUNCTION fast.guard_signed_content() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    pid UUID;
    st  TEXT;
BEGIN
    -- Check the plan of the old row and of the new row: content cannot leave or enter a frozen plan.
    FOR i IN 1..2 LOOP
        pid := NULL;
        IF i = 1 AND TG_OP = 'INSERT' THEN CONTINUE; END IF;
        IF i = 2 AND TG_OP = 'DELETE' THEN CONTINUE; END IF;
        IF TG_TABLE_NAME IN ('crop_sheets', 'findings') THEN
            IF i = 1 THEN pid := OLD.plan_id; ELSE pid := NEW.plan_id; END IF;
        ELSIF i = 1 THEN
            SELECT plan_id INTO pid FROM fast.crop_sheets WHERE id = OLD.sheet_id;
        ELSE
            SELECT plan_id INTO pid FROM fast.crop_sheets WHERE id = NEW.sheet_id;
        END IF;
        SELECT state INTO st FROM fast.plans WHERE id = pid;
        IF st IN ('signed', 'superseded') THEN
            RAISE EXCEPTION 'plan % is %: its content cannot change', pid, st;
        END IF;
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS crop_sheets_guard_signed ON fast.crop_sheets;
CREATE TRIGGER crop_sheets_guard_signed BEFORE INSERT OR UPDATE OR DELETE ON fast.crop_sheets
    FOR EACH ROW EXECUTE FUNCTION fast.guard_signed_content();
DROP TRIGGER IF EXISTS sheet_parcels_guard_signed ON fast.sheet_parcels;
CREATE TRIGGER sheet_parcels_guard_signed BEFORE INSERT OR UPDATE OR DELETE ON fast.sheet_parcels
    FOR EACH ROW EXECUTE FUNCTION fast.guard_signed_content();
DROP TRIGGER IF EXISTS applications_guard_signed ON fast.applications;
CREATE TRIGGER applications_guard_signed BEFORE INSERT OR UPDATE OR DELETE ON fast.applications
    FOR EACH ROW EXECUTE FUNCTION fast.guard_signed_content();
DROP TRIGGER IF EXISTS results_guard_signed ON fast.results;
CREATE TRIGGER results_guard_signed BEFORE INSERT OR UPDATE OR DELETE ON fast.results
    FOR EACH ROW EXECUTE FUNCTION fast.guard_signed_content();
DROP TRIGGER IF EXISTS findings_guard_signed ON fast.findings;
CREATE TRIGGER findings_guard_signed BEFORE INSERT OR UPDATE OR DELETE ON fast.findings
    FOR EACH ROW EXECUTE FUNCTION fast.guard_signed_content();
