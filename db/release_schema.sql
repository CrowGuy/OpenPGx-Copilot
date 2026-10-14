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
