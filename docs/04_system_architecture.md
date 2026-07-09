# 04 System Architecture

## 1. Purpose

This document defines the system architecture for OpenPGx Copilot v0.1.

OpenPGx Copilot v0.1 is a wellness-first educational proof of concept with PGx-ready architecture.

The architecture must support two related but separate paths:

```text
1. Runtime interpretation path
2. Offline ingestion / candidate compiler path
```

The runtime path is responsible for safe, deterministic, user-facing educational interpretations based on active curated rules and active evidence records.

The offline ingestion/compiler path is responsible for creating source records, evidence candidates, rule candidates, and review cards from public structured or semi-structured sources. Its outputs are candidate-only by default and cannot directly produce user-facing interpretations.

## 2. Architectural Principles

OpenPGx Copilot follows these principles:

```text
1. OpenPGx Copilot is not a RAG chatbot.
2. Runtime user-facing interpretations are decided by active curated rules.
3. Evidence lookup is rule-bound, not open-ended top-k retrieval.
4. LLMs are explanation layers, not decision layers.
5. Compiler output is candidate-only until reviewed, validated, approved, and released.
6. Every active rule must have valid evidence references.
7. Every output must pass safety validation.
8. v0.1 is wellness-first, but the architecture remains PGx-ready.
9. The system must be auditable, reproducible, testable, and versioned.
```

## 3. High-Level System Diagram

```text
                         ┌──────────────────────────┐
                         │      Raw User Request     │
                         └─────────────┬────────────┘
                                       │
                                       ▼
                         ┌──────────────────────────┐
                         │ Request Adapter / Router  │
                         └─────────────┬────────────┘
                                       │
                                       ▼
                         ┌──────────────────────────┐
                         │     RoutingDecision       │
                         └─────────────┬────────────┘
                                       │
                                       ▼
                         ┌──────────────────────────┐
                         │ OpenPGx Request Validator │
                         └─────────────┬────────────┘
                                       │
                                       ▼
                         ┌──────────────────────────┐
                         │      Rule Engine          │
                         └─────────────┬────────────┘
                                       │
                                       ▼
                         ┌──────────────────────────┐
                         │ Rule-bound Evidence Store │
                         └─────────────┬────────────┘
                                       │
                                       ▼
                         ┌──────────────────────────┐
                         │    Explanation Layer      │
                         └─────────────┬────────────┘
                                       │
                                       ▼
                         ┌──────────────────────────┐
                         │  Output Safety Validator  │
                         └─────────────┬────────────┘
                                       │
                                       ▼
                         ┌──────────────────────────┐
                         │   User-facing Response    │
                         └──────────────────────────┘
```

Offline candidate compiler path:

```text
Public Sources
  ├─ GWAS Catalog
  ├─ dbSNP / NCBI Variation Services
  └─ PubMed metadata
        │
        ▼
Source Adapters
        │
        ▼
Normalizers
        │
        ▼
SourceRecords / MarkerRecords
        │
        ▼
EvidenceCandidate Compiler
        │
        ▼
RuleCandidate Compiler
        │
        ▼
ReviewCard Generator
        │
        ▼
Human Review + Validation
        │
        ▼
Active EvidenceRecords + Active RuleRecords
        │
        ▼
Released Active Rule Set
```

## 4. Runtime Architecture

The runtime path must remain deterministic and bounded.

Runtime flow:

```text
RawUserRequest
→ RequestAdapter / Router
→ RoutingDecision
→ RequestValidator
→ RuleEngine
→ EvidenceStore
→ ExplanationLayer
→ OutputSafetyValidator
→ UserFacingResponse
```

Runtime must not perform open-ended literature retrieval to decide user-facing interpretations.

Runtime must not use LLM reasoning to infer genotype-trait mapping.

Runtime must not use candidate records as active rules.

## 5. RawUserRequest

RawUserRequest represents the incoming request.

v0.1 supports structured synthetic inputs and may optionally include a simple user query.

Example:

```json
{
  "user_id": "demo-001",
  "query": "I have rs671 AG. What does it mean?",
  "genotypes": [
    {
      "rsid": "rs671",
      "genotype": "AG"
    }
  ],
  "module": "wellness_traits"
}
```

The query field may influence:

```text
1. Intent classification.
2. Response mode.
3. Safety route.
4. Entity extraction.
```

The query field must not influence:

```text
1. Genotype-to-trait mapping.
2. Evidence strength.
3. Rule matching result.
4. Active rule creation.
5. Safety boundary removal.
```

## 6. Request Adapter / Router

In v0.1, OpenPGx Copilot may include a lightweight internal Request Adapter.

The Request Adapter is responsible for:

```text
1. Parsing simple demo requests.
2. Extracting supported rsID-genotype patterns.
3. Assigning intent.
4. Assigning target module.
5. Assigning response mode.
6. Assigning safety route.
7. Producing a RoutingDecision.
```

The Request Adapter must not:

```text
1. Interpret genetic meaning.
2. Decide trait result.
3. Generate evidence claims.
4. Create rules.
5. Retrieve literature to decide answers.
6. Generate final user-facing domain explanations.
```

The long-term architecture may extract this responsibility into a separate repo:

```text
gene-domain-intent-router
```

But v0.1 does not require a standalone router.

## 7. RoutingDecision Contract

RoutingDecision is the structured interface between query understanding and OpenPGx Copilot core execution.

Example:

```json
{
  "request_id": "req-001",
  "source": "internal_request_adapter",
  "intent": "trait_interpretation",
  "domain": "genetic_wellness",
  "target_system": "openpgx_copilot",
  "target_module": "wellness_traits",
  "response_mode": "educational_explanation",
  "safety_route": "allowed",
  "extracted_entities": {
    "markers": [
      {
        "rsid": "rs671",
        "genotype": "AG"
      }
    ],
    "traits": [],
    "genes": [],
    "drugs": [],
    "phenotypes": []
  },
  "blocked_outputs": [
    "medical_advice",
    "nutrition_advice",
    "fitness_advice",
    "supplement_advice",
    "medication_advice",
    "diagnosis",
    "disease_risk_prediction"
  ],
  "confidence": 0.95
}
```

Supported v0.1 intents:

```text
trait_interpretation
evidence_explanation
limitation_explanation
unsupported_marker_question
personalized_advice_request
medical_or_disease_risk_request
out_of_scope_request
```

Supported v0.1 safety routes:

```text
allowed
downgrade_to_educational
refuse_personalized_advice
refuse_medical_advice
refuse_nutrition_advice
refuse_fitness_advice
refuse_supplement_advice
refuse_medication_advice
refuse_disease_risk
unsupported_input
out_of_scope
needs_clarification
```

## 8. Request Validator

The Request Validator validates RoutingDecision and structured inputs before rule matching.

It must check:

```text
1. target_system is openpgx_copilot.
2. target_module is supported.
3. response_mode is supported.
4. safety_route is compatible with requested output.
5. Required marker entities are present.
6. rsID format is valid.
7. genotype format is valid.
8. blocked output categories are respected.
9. Input is synthetic and v0.1-compatible.
```

The Request Validator must reject or downgrade if:

```text
1. The request asks for medical advice.
2. The request asks for nutrition advice.
3. The request asks for fitness advice.
4. The request asks for supplement advice.
5. The request asks for medication advice.
6. The request asks for diagnosis.
7. The request asks for disease-risk prediction.
8. The request contains unsupported input.
```

## 9. Rule Engine

The Rule Engine is the domain decision component.

It is responsible for:

```text
1. Loading active RuleRecords.
2. Validating active RuleRecords at startup.
3. Matching validated inputs against active curated rules.
4. Producing structured interpretation results.
5. Refusing unsupported markers or unmatched genotypes.
```

The Rule Engine must not:

```text
1. Use LLMs for rule matching.
2. Use top-k literature retrieval for rule matching.
3. Create rules at runtime.
4. Use candidate rules as active rules.
5. Infer unsupported traits.
6. Ignore evidence_refs.
```

Example active RuleRecord:

```yaml
id: aldh2_rs671_alcohol_metabolism
status: active
domain: wellness_trait
gene: ALDH2
trait: alcohol_metabolism
markers:
  - rsid: rs671
    genotype_pattern: "AG|AA"
interpretation_level: educational
result_code: reduced_aldh2_activity_association
evidence_refs:
  - evidence_aldh2_rs671_001
required_safety_message: wellness_educational
```

Rule loading must fail if:

```text
1. status is not active.
2. evidence_refs is empty.
3. evidence_refs cannot be resolved.
4. genotype pattern is invalid.
5. domain is unsupported.
6. required safety message is missing.
7. referenced evidence disallows educational explanation.
```

## 10. Evidence Store

The Evidence Store contains active EvidenceRecords and related SourceRecords.

It is responsible for:

```text
1. Resolving evidence_refs from matched rules.
2. Returning active evidence records.
3. Validating allowed_use and disallowed_use.
4. Providing evidence summaries and limitations to the Explanation Layer.
5. Maintaining source traceability.
```

Example active EvidenceRecord:

```yaml
id: evidence_aldh2_rs671_001
status: active
domain: wellness_trait
source_refs:
  - source_aldh2_rs671_paper_001
gene: ALDH2
markers:
  - rs671
trait: alcohol_metabolism
summary: >
  ALDH2 rs671 is associated with reduced ALDH2 enzyme activity
  and altered acetaldehyde metabolism.
population_note: "Association is especially relevant in East Asian populations."
limitations:
  - "Genotype is only one factor."
  - "Actual response may be affected by health status, environment, lifestyle, and other genetic factors."
allowed_use:
  - educational_explanation
disallowed_use:
  - medical_advice
  - nutrition_advice
  - fitness_advice
  - supplement_advice
  - medication_advice
```

## 11. Source Records

SourceRecord represents original source metadata.

Example:

```yaml
id: source_aldh2_rs671_paper_001
source_type: peer_reviewed_article
title: "..."
url: "..."
pmid: "..."
doi: "..."
retrieved_at: "2026-07-02"
raw_payload_path: "data/raw/aldh2/source_001.json"
sha256: "..."
```

SourceRecord may represent:

```text
1. GWAS Catalog association record.
2. dbSNP / NCBI Variation Services record.
3. PubMed metadata record.
```

## 12. Explanation Layer

The Explanation Layer converts structured rule/evidence outputs into user-facing educational language.

It may be template-based, LLM-assisted, or hybrid.

The Explanation Layer receives only bounded inputs:

```text
1. Matched RuleRecord fields.
2. Active EvidenceRecord fields.
3. Source metadata.
4. Limitations.
5. Required safety message.
6. Safety route.
```

The Explanation Layer may:

```text
1. Produce educational explanations.
2. Summarize provided evidence snippets.
3. Explain limitations.
4. Explain unsupported inputs.
5. Localize output language.
```

The Explanation Layer must not:

```text
1. Perform rule matching.
2. Create evidence claims.
3. Invent citations.
4. Add advice.
5. Remove safety message.
6. Upgrade association into recommendation.
7. Use candidate records as active evidence.
```

## 13. Output Safety Validator

The Output Safety Validator checks every user-facing response before return.

It must verify:

```text
1. Required safety message exists.
2. Every interpretation has evidence_refs.
3. No medical advice is present.
4. No nutrition advice is present.
5. No fitness advice is present.
6. No supplement advice is present.
7. No medication advice is present.
8. No diagnosis is present.
9. No disease-risk prediction is present.
10. Limitations are present.
11. Unsupported inputs are not interpreted.
12. Candidate records are not presented as active rule results.
```

If validation fails, the system must:

```text
1. Regenerate with stricter constraints, or
2. Downgrade to a safe template, or
3. Refuse the request.
```

## 14. Offline Ingestion / Compiler Architecture

The offline ingestion/compiler path is separate from runtime interpretation.

Its purpose is to help build and review evidence and rule candidates.

It may use public structured or semi-structured sources.

Primary wellness sources:

```text
1. GWAS Catalog
2. dbSNP / NCBI Variation Services
3. PubMed metadata
```

Optional supporting sources:

```text
1. Open Targets
2. ClinVar
3. Population frequency sources
4. SNPedia as manual research aid only
```

The compiler path is:

```text
source adapter
→ source normalization
→ source record creation
→ marker record creation
→ evidence candidate compilation
→ rule candidate compilation
→ review card generation
→ human review
→ validation
→ active record release
```

## 15. Candidate Records

Candidate records are not active records.

Candidate records may be generated by deterministic compilers or reviewer tools.

Candidate record types include:

```text
EvidenceCandidateRecord
RuleCandidateRecord
ReviewCard
```

Example RuleCandidateRecord:

```yaml
id: rule_candidate_aldh2_rs671_alcohol_metabolism_001
status: candidate
domain: wellness_trait
gene: ALDH2
trait: alcohol_metabolism
markers:
  - rsid: rs671
    genotype_pattern_candidate: "AG|AA"
candidate_basis:
  - evidence_candidate_aldh2_rs671_gwas_001
compiler_notes:
  - "Candidate generated from GWAS Catalog association and dbSNP marker validation."
requires_human_review:
  - "Confirm genotype pattern."
  - "Confirm effect direction."
  - "Confirm population note."
  - "Confirm no disease-risk claim."
```

Candidate records must not be used by runtime Rule Engine.

## 16. Wellness Compiler Boundary

For wellness traits, GWAS or association data must be treated carefully.

The compiler may use GWAS Catalog to identify association candidates, but must not automatically convert associations into active rules.

Reasons:

```text
1. Association is not deterministic prediction.
2. Effect allele does not automatically define genotype-level interpretation.
3. Population context matters.
4. Effect size may be small or context-dependent.
5. Trait definitions may not map cleanly to product-level trait labels.
6. Wellness traits may be polygenic or environment-dependent.
7. Statistical significance does not imply personal actionability.
```

Therefore:

```text
GWAS association
→ EvidenceCandidate
→ ReviewCard
→ curated EvidenceRecord
→ curated RuleRecord
```

not:

```text
GWAS association
→ active RuleRecord
```

## 17. Future PGx Architecture

Future PGx modules should extend the same architecture but with PGx-specific record types.

Future PGx path:

```text
variant / haplotype / star allele
→ diplotype
→ gene function
→ phenotype
→ medication context
→ drug-specific rule
→ PGx alert
→ evidence-bound explanation
```

Future PGx records may include:

```text
AlleleDefinitionRecord
AlleleFunctionRecord
DiplotypePhenotypeRecord
PhenotypeDefinitionRecord
DrugRecommendationRule
PGxEvidenceRecord
MedicationContextRecord
```

Future PGx source strategy should prioritize expert-curated public pharmacogenomics resources:

```text
1. CPIC / ClinPGx
2. PharmGKB
3. PharmCAT-compatible datasets and output behavior
4. PharmVar
5. FDA / openFDA drug labels
6. ClinVar as supporting variant metadata
```

Original papers and literature retrieval may support evidence discovery and reviewer workflows but must not directly create active PGx rules without validation and human approval.

## 18. Module Boundaries

v0.1 modules:

```text
request_adapter
request_validator
rule_engine
evidence_store
explanation_layer
output_safety_validator
source_adapters
normalizers
candidate_compilers
review_card_generator
registry
tests
```

Runtime-only modules:

```text
request_adapter
request_validator
rule_engine
evidence_store
explanation_layer
output_safety_validator
```

Offline-only modules:

```text
source_adapters
normalizers
candidate_compilers
review_card_generator
source_cache
review_workflow
```

Shared modules:

```text
schemas
controlled_vocabularies
source_records
evidence_records
rule_records
validators
registry
```

## 19. Suggested Repository Structure

```text
openpgx-copilot/
  docs/
    00_project_vision.md
    01_safety_boundary.md
    02_domain_model.md
    03_mvp_scope.md
    04_system_architecture.md
    05_data_ingestion_contract.md
    06_rule_engine_spec.md
    07_evidence_model.md
    08_explanation_layer.md
    09_api_contract.md
    10_evaluation_plan.md
    11_roadmap.md

  docs/adr/
    ADR-001-router-extraction-boundary.md
    ADR-002-rule-bound-evidence-retrieval.md
    ADR-003-candidate-only-compiler-output.md

  data/
    raw/
    normalized/
    evidence/
    rules/
    candidates/
    sources/

  src/openpgx_copilot/
    schemas/
    request_adapter/
    validation/
    rule_engine/
    evidence_store/
    explanation/
    safety/
    ingestion/
      source_adapters/
      normalizers/
      compilers/
      review_cards/
    registry/

  tests/
    fixtures/
    unit/
    integration/
    safety/
    regression/
```

## 20. Versioning and Release Model

The system should version:

```text
1. Source snapshots.
2. SourceRecords.
3. EvidenceRecords.
4. RuleRecords.
5. Candidate records.
6. Active rule sets.
7. Safety templates.
8. Schema versions.
```

Example active rule set metadata:

```yaml
rule_set_id: wellness_rules_v0_1_2026_07
status: active
domain: wellness_trait
created_at: "2026-07-07"
source_snapshot_refs:
  - gwas_catalog_snapshot_2026_07
  - dbsnp_snapshot_2026_07
evidence_record_version: "0.1"
rule_record_version: "0.1"
review_status: approved
test_status: passed
```

No active rule set should be released unless:

```text
1. All rules are schema-valid.
2. All evidence_refs resolve.
3. All referenced evidence records are active.
4. Safety validation passes.
5. Regression tests pass.
6. Review status is approved.
```

## 21. Testing Architecture

The test suite should include:

```text
1. Schema validation tests.
2. Rule matching tests.
3. Evidence reference resolution tests.
4. Unsupported input tests.
5. Unsafe request tests.
6. Output safety validation tests.
7. Candidate/active separation tests.
8. Source adapter tests.
9. Compiler candidate generation tests.
10. Regression tests for supported markers.
```

Critical tests:

```text
1. Rule without evidence_refs cannot load.
2. Rule with unresolved evidence_ref cannot load.
3. Candidate rule cannot be used by runtime.
4. Unsupported rsID cannot produce interpretation.
5. Unsafe advice request is refused or downgraded.
6. LLM output missing safety message fails validation.
7. LLM output with advice fails validation.
8. Same input produces same structured rule result.
```