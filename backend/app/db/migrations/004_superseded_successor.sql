-- A superseded plan always has a signed (or later superseded) successor: no campaign is left
-- without the version that replaced it. Checked at commit, so a revision can supersede the old
-- version and sign the new one in the same transaction. Idempotent.
CREATE OR REPLACE FUNCTION fast.check_superseded_successor() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.state = 'superseded' AND NOT EXISTS (
            SELECT 1 FROM fast.plans s
            WHERE s.supersedes = NEW.id AND s.state IN ('signed', 'superseded')) THEN
        RAISE EXCEPTION 'plan % is superseded without a signed successor', NEW.id;
    END IF;
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS plans_superseded_successor ON fast.plans;
CREATE CONSTRAINT TRIGGER plans_superseded_successor AFTER UPDATE ON fast.plans
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    WHEN (NEW.state = 'superseded' AND OLD.state IS DISTINCT FROM 'superseded')
    EXECUTE FUNCTION fast.check_superseded_successor();
-- The same guard for a plan inserted already superseded.
DROP TRIGGER IF EXISTS plans_superseded_successor_insert ON fast.plans;
CREATE CONSTRAINT TRIGGER plans_superseded_successor_insert AFTER INSERT ON fast.plans
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    WHEN (NEW.state = 'superseded')
    EXECUTE FUNCTION fast.check_superseded_successor();
