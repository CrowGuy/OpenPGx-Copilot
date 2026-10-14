-- 0002: load report summary per Release (ADR-0007): row counts, Rejected Row ratios and reasons per dataset.
ALTER TABLE meta.release ADD COLUMN IF NOT EXISTS load_report jsonb;
