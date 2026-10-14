-- Release schema DDL (ADR-0005). The loader runs this with search_path set to a new gwas_r<YYYY_MM_DD> schema.
-- Column names and types follow raw/gwas_catalog/contracts/gwas_curation_contract.json.

CREATE TABLE study (
    date_added_to_catalog date,
    pubmed_id integer,
    first_author text,
    publication_date date,
    journal text,
    link text,
    study text,
    disease_trait text,
    initial_sample_size text,
    replication_sample_size text,
    platform_snps_passing_qc text,
    association_count integer,
    mapped_trait text,
    mapped_trait_uri text,
    study_accession text PRIMARY KEY,
    genotyping_technology text,
    submission_date date,
    statistical_model text,
    background_trait text,
    mapped_background_trait text,
    mapped_background_trait_uri text,
    cohort text,
    full_summary_statistics boolean,
    summary_stats_location text,
    gxe boolean
);

-- One row per published_associations source row; full duplicates are kept, each with its own association_id.
-- p-values are never a double (ADR-0009): filter significance on pvalue_mlog. *_text keeps the source text.
CREATE TABLE association (
    association_id bigint PRIMARY KEY,
    date_added_to_catalog date,
    pubmed_id integer,
    first_author text,
    publication_date date,
    journal text,
    link text,
    study text,
    disease_trait text,
    initial_sample_size text,
    replication_sample_size text,
    region text,
    chr_id text,
    chr_pos text,
    reported_genes text,
    mapped_gene text,
    upstream_gene_id text,
    downstream_gene_id text,
    snp_gene_ids text,
    upstream_gene_distance integer,
    downstream_gene_distance integer,
    strongest_snp_risk_allele text,
    snps text NOT NULL,
    merged boolean,
    snp_id_current text,
    context text,
    intergenic boolean,
    risk_allele_frequency double precision,
    risk_allele_frequency_text text,
    p_value_mantissa numeric NOT NULL,
    p_value_exponent integer NOT NULL,
    p_value_text text NOT NULL,
    pvalue_mlog double precision,
    p_value_qualifier text,
    or_beta double precision,
    or_beta_text text,
    ci_text text,
    platform_snps_passing_qc text,
    cnv text,
    mapped_trait text,
    mapped_trait_uri text,
    study_accession text NOT NULL REFERENCES study,
    genotyping_technology text,
    snp_combination text NOT NULL,
    -- Locus Alignment failed: Variant Token and CHR_ID/CHR_POS/risk allele counts differ, so they are not paired.
    misaligned boolean NOT NULL
);
CREATE INDEX ON association (study_accession);

-- One row per Variant Token of association.snps, numbered from 1 in source order.
CREATE TABLE association_snp (
    association_id bigint NOT NULL REFERENCES association,
    position integer NOT NULL,
    variant_token text NOT NULL,
    variant_kind text NOT NULL,
    rsid text,
    chr text,
    pos integer,
    risk_allele text,
    PRIMARY KEY (association_id, position)
);
CREATE INDEX ON association_snp (rsid);
CREATE INDEX ON association_snp (chr, pos);

-- Rejected Rows (ADR-0007): one row per Required Field violation of a source row kept out of the Curated Layer.
CREATE TABLE rejected_row (
    source_file text NOT NULL,
    source_line integer NOT NULL,
    source_column text NOT NULL,
    reason text NOT NULL,
    value text NOT NULL,
    PRIMARY KEY (source_file, source_line, source_column)
);
