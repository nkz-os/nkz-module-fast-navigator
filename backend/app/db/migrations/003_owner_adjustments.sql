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
