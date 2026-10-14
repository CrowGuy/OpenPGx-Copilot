-- 0003: what each Release was built from (#6): RawSnapshot manifest, CurationContract version and sha256, genome build.
-- ponytail: nullable so Releases loaded before #6 stay valid; the loader always writes all four.
ALTER TABLE meta.release
    ADD COLUMN IF NOT EXISTS manifest_sha256 text,
    ADD COLUMN IF NOT EXISTS curation_contract_version integer,
    ADD COLUMN IF NOT EXISTS curation_contract_sha256 text,
    ADD COLUMN IF NOT EXISTS genome_build text;
