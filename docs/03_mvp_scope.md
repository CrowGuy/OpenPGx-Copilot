# 03 MVP Scope

## 1. Purpose

This document defines the version 0.1 MVP scope for OpenPGx Copilot.

OpenPGx Copilot is a public-data-driven genetic interpretation and pharmacogenomics decision-support prototype. The long-term direction is pharmacogenomics medication alert support, but v0.1 starts with a wellness-first proof of concept.

The purpose of v0.1 is to validate the core architecture using low-risk wellness genetic trait examples before expanding toward pharmacogenomics medication alert workflows.

## 2. v0.1 Scope Statement

OpenPGx Copilot v0.1 is a wellness-first educational proof of concept.

It accepts synthetic rsID-genotype inputs, matches them against a small curated wellness trait rule set, resolves rule-bound evidence references, and produces safe educational explanations with limitations and safety messages.

v0.1 may also include a candidate-only evidence/rule compiler framework for wellness traits. This compiler framework is optional and non-release-blocking for v0.1; its full implementation is deferred to v0.2, and v0.1 may ship with hand-written rule/evidence YAML only. When present, it may generate candidate records from public structured or semi-structured sources, but it must not directly generate active user-facing rules.

v0.1 does not provide medical, nutrition, fitness, supplement, medication, diagnosis, disease-risk, treatment, or lifestyle advice.

## 3. MVP Architecture Goal

The goal of v0.1 is not to build a complete consumer genetics product.

The goal is to validate this reusable runtime architecture:

```text
synthetic rsID-genotype input
→ input validation
→ curated rule matching
→ evidence reference validation
→ rule-bound evidence lookup
→ structured interpretation result
→ educational explanation
→ output safety validation
```

It may also validate this candidate-only ingestion architecture:

```text
public structured / semi-structured source
→ source adapter
→ normalization
→ evidence candidate compiler
→ rule candidate compiler
→ review card generation
→ human curation
→ active evidence/rule release
```

This architecture should later be extensible to pharmacogenomics modules.

## 4. v0.1 Core Capabilities

v0.1 must implement:

```text
1. Synthetic rsID-genotype input handling.
2. Basic request validation.
3. Small curated wellness trait rule set.
4. Marker-level rule matching for supported traits.
5. Evidence reference validation.
6. Rule-bound evidence lookup.
7. Structured interpretation result generation.
8. Educational explanation generation.
9. Limitation statement generation.
10. Required safety message inclusion.
11. Unsupported input handling.
12. Unsafe request refusal or downgrade.
13. LLM output safety validation.
14. Regression tests for rule correctness and unsafe output.
```

v0.1 may implement:

```text
1. GWAS Catalog source adapter.
2. dbSNP / NCBI Variation Services source adapter.
3. PubMed metadata source adapter.
4. EvidenceCandidateRecord compiler.
5. RuleCandidateRecord compiler.
6. ReviewCard generator.
7. Candidate-to-active manual approval workflow prototype.
```

## 5. v0.1 Supported Inputs

v0.1 supports synthetic input only.

The minimum supported structured input is:

```json
{
  "user_id": "demo-001",
  "input_type": "synthetic",
  "genotypes": [
    {
      "rsid": "rs671",
      "genotype": "AG"
    }
  ],
  "module": "wellness_traits"
}
```

v0.1 may also support a lightweight natural-language query field:

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

The natural-language query may be used for intent routing, response mode selection, and safety classification. It must not be used as domain interpretation logic.

Structured `genotypes[]` is the sole domain authority. The query is never parsed for markers or genotypes; any rsID or genotype text written inside the query is ignored for interpretation. Because the query is never a source of markers, there is no query-versus-payload genotype conflict to resolve. The query affects only the safety route, the response mode, and the output wording.

## 6. v0.1 Input Constraints

v0.1 inputs must be constrained to:

```text
1. Synthetic user identifier.
2. Synthetic rsID-genotype list.
3. Supported wellness trait module.
4. Optional simple user query.
```

v0.1 must not require or process:

```text
1. Real patient data.
2. Clinical records.
3. Medication history.
4. Diagnosis history.
5. Symptoms.
6. Family history.
7. Raw sequencing data.
8. FASTQ, BAM, CRAM, or VCF processing.
9. Haplotype or diplotype inference.
10. Star allele calling.
11. Phenotype conversion.
```

`input_type` must be `synthetic` and is required; a request that omits it or declares any other type must be rejected. The synthetic `user_id` and optional `query` are free-text fields: they must not be persisted or logged in cleartext, and are used only for routing, never as domain interpretation logic. Because a genotype's realness cannot be determined from its content, this boundary is enforced by the declared input type and by data minimization, not by inspecting genotype values.

## 7. v0.1 Supported Trait Set

v0.1 supports a small curated set of wellness genetic traits.

Initial supported trait candidates:

```text
1. ALDH2 - alcohol metabolism
2. LCT / MCM6 - lactose tolerance
3. CYP1A2 - caffeine metabolism
4. ABCC11 - earwax type
5. TAS2R38 - bitter taste perception
```

These traits are selected because they are useful for validating the architecture and can be explained as educational associations without making personal health recommendations.

### MVP Release Profile

v0.1 defines two profiles so completion is unambiguous:

```text
MVP-min (release-blocking):
- ALDH2 (rs671) delivered as one schema-valid active rule, working end to end
  (input -> rule match -> evidence -> explanation -> safety validation).
- Unsupported, deferred, invalid-input, and safety tests pass.

MVP-full (target, non-release-blocking):
- All five traits above delivered as active rules.
```

The remaining four traits are targets: they may ship in v0.1, but their absence does not block the v0.1 release. Any trait that does ship must meet the same active-rule, evidence, and safety requirements as ALDH2.

## 8. v0.1 Deferred Trait Set

The following traits are deferred from v0.1:

```text
1. ACTN3 - exercise trait association
2. FTO - weight management association
3. VDR - vitamin D metabolism association
4. PER3 / CLOCK - sleep pattern association
```

These are deferred because they are more likely to be overinterpreted as personalized exercise, weight management, supplement, sleep, or lifestyle advice.

## 9. v0.1 Example Marker Coverage

The initial marker candidates are:

```text
ALDH2:
- rs671

LCT / MCM6:
- rs4988235

CYP1A2:
- rs762551

ABCC11:
- rs17822931

TAS2R38:
- rs713598
- rs1726866
- rs10246939
```

The exact supported genotype patterns must be defined in curated RuleRecord files.

The presence of a marker candidate in this document does not automatically make it an active rule. A marker is active only if there is a schema-valid curated rule with valid evidence references.

## 10. v0.1 Rule Scope

v0.1 uses manually curated marker-level active rules.

A rule may match:

```text
rsID + genotype pattern
```

Example:

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

v0.1 rules must not:

```text
1. Provide medical advice.
2. Provide nutrition advice.
3. Provide fitness advice.
4. Provide supplement advice.
5. Provide medication advice.
6. Predict disease risk.
7. Diagnose disease.
8. Infer unsupported outcomes.
9. Depend on LLM-generated decision logic.
10. Activate without valid evidence references.
```

## 11. v0.1 Evidence Scope

v0.1 uses manually curated active evidence records.

Each active rule must reference at least one valid EvidenceRecord.

Example:

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

v0.1 evidence records must support:

```text
1. Evidence traceability.
2. Source references.
3. Allowed-use boundaries.
4. Disallowed-use boundaries.
5. Limitations.
6. Structured entities for future retrieval.
```

## 12. v0.1 Source Scope

v0.1 may use manually curated metadata from public sources.

Primary public source categories include:

```text
1. GWAS Catalog
2. dbSNP / NCBI Variation Services
3. PubMed metadata
4. Peer-reviewed papers
```

Supporting sources may include:

```text
1. Open Targets as optional cross-check.
2. ClinVar as supporting metadata or do-not-overclaim check.
3. Population frequency sources as optional metadata enrichment.
4. SNPedia as research aid or manual cross-check only.
```

v0.1 must not automatically convert source records or evidence candidates into active rules.

## 13. v0.1 Ingestion and Compiler Scope

v0.1 uses Ingestion Lite.

v0.1 must define:

```text
1. Source adapter output schema.
2. SourceRecord schema.
3. EvidenceCandidateRecord schema.
4. EvidenceRecord schema.
5. RuleCandidateRecord schema.
6. RuleRecord schema.
7. Manually curated evidence records for supported traits.
8. Rule loading validation.
9. Evidence reference validation.
10. Source metadata fields.
11. Test fixtures.
```

v0.1 may optionally implement:

```text
1. GWAS Catalog association fetcher.
2. dbSNP rsID metadata fetcher.
3. PubMed metadata fetcher.
4. Source cache.
5. Candidate review card generator.
```

v0.1 does not implement:

```text
1. Automatic active rule extraction from papers.
2. Automatic evidence strength assignment.
3. Automatic conflict resolution across papers.
4. Automatic patient explanation generation from raw papers.
5. Large-scale SNP ingestion.
6. Full-text paper parsing.
7. LLM-generated active rules.
8. Automatic candidate-to-active promotion.
```

Core ingestion principle:

```text
No ingestion output can become an active rule without curation and validation.
```

## 14. v0.1 Retrieval Scope

v0.1 does not use NaiveRAG as the runtime interpretation path.

The primary runtime evidence path is:

```text
matched_rule.evidence_refs
→ evidence_store.get(evidence_id)
→ explanation layer
```

This is deterministic rule-bound evidence lookup.

v0.1 may reserve retrieval-oriented fields in EvidenceRecord for future search, BM25, dense retrieval, or hybrid retrieval.

Future retrieval paths may include:

```text
1. Evidence viewer retrieval.
2. Developer review search.
3. Evidence discovery.
4. Structured research exploration.
5. Conflict analysis.
```

These future retrieval paths must not replace curated rule-bound interpretation for user-facing answers.

## 15. v0.1 LLM Scope

The LLM may be used only as an explanation layer.

The LLM may:

```text
1. Rewrite structured results into user-friendly educational explanations.
2. Summarize provided evidence snippets.
3. Explain limitations.
4. Explain unsupported inputs.
5. Produce bilingual or localized explanation text if needed.
6. Summarize candidate evidence for reviewer workflows.
```

The LLM must not:

```text
1. Perform rule matching.
2. Create active rules.
3. Decide evidence strength.
4. Infer unsupported traits.
5. Invent evidence.
6. Invent citations.
7. Provide advice.
8. Remove safety messages.
9. Convert educational association into recommendation.
10. Approve compiler-generated candidates.
```

## 16. v0.1 Output Scope

The v0.1 output must include:

```text
1. Structured trait interpretation results.
2. Matched genetic trait rules.
3. Evidence references.
4. Educational explanation.
5. Limitation statements.
6. Required safety message.
7. Unsupported-input warnings when applicable.
```

Example output shape:

```json
{
  "user_id": "demo-001",
  "results": [
    {
      "rule_id": "aldh2_rs671_alcohol_metabolism",
      "domain": "wellness_trait",
      "trait": "alcohol_metabolism",
      "gene": "ALDH2",
      "matched_marker": {
        "rsid": "rs671",
        "genotype": "AG"
      },
      "interpretation_level": "educational",
      "summary": "This genotype is associated with reduced ALDH2 enzyme activity in some populations.",
      "limitations": [
        "Genotype is only one factor.",
        "Actual response may be affected by environment, health status, lifestyle, and other genetic factors."
      ],
      "evidence_refs": [
        "evidence_aldh2_rs671_001"
      ],
      "safety_message": "This explanation is for educational purposes only and should not be used as medical, nutrition, fitness, supplement, or medication advice."
    }
  ]
}
```

## 17. Out of Scope for v0.1

The following are out of scope:

```text
1. PGx medication alerts.
2. Medication recommendation.
3. Drug dosage recommendation.
4. Drug substitution recommendation.
5. Diagnosis.
6. Disease-risk prediction.
7. Real patient data.
8. Clinical EHR integration.
9. Medication list processing.
10. Phenoconversion.
11. Drug-drug-gene interaction.
12. HLA allele interpretation.
13. CNV or structural variant interpretation.
14. Star allele calling.
15. Haplotype phasing.
16. Diplotype-to-phenotype conversion.
17. Full CPIC or PharmGKB implementation.
18. Full PharmCAT integration.
19. Automatic paper-to-active-rule extraction.
20. Open-ended genetics chatbot behavior.
21. Runtime top-k literature retrieval deciding user-facing answers.
```

## 18. Acceptance Criteria

v0.1 is accepted if:

```text
1. The MVP-min bar is met: ALDH2 (rs671) works end to end as one active rule (see the MVP Release Profile in section 7). Any additional supported trait that ships also triggers its correct curated rule.
2. Unsupported rsID does not produce invented interpretation.
3. Invalid genotype format returns validation error or unsupported warning.
4. Every interpretation links to at least one evidence reference.
5. Every active rule has valid evidence_refs.
6. A rule without evidence_refs fails validation and cannot be loaded as active.
7. Every user-facing explanation includes the required safety message.
8. Explanations include limitation statements.
9. Unsafe requests are refused or downgraded.
10. LLM output does not provide medical, nutrition, fitness, supplement, medication, diagnosis, or disease-risk advice.
11. Runtime interpretation is reproducible and regression-testable.
12. Candidate records cannot be used as active rules without review and approval.
13. The same core rule/evidence/explanation architecture can later support PGx medication alert modules.
```

## 19. MVP Test Scenarios

v0.1 should include tests for:

```text
1. Supported marker and genotype match.
2. Supported marker but non-matching genotype.
3. Unsupported marker.
4. Invalid rsID format.
5. Invalid genotype format.
6. Rule with missing evidence_refs.
7. Rule with unresolved evidence_ref.
8. Evidence record with disallowed requested use.
9. User request asking for medical advice.
10. User request asking for nutrition advice.
11. User request asking for fitness advice.
12. User request asking for supplement advice.
13. User request asking for medication advice.
14. User request asking for disease-risk prediction.
15. LLM output missing safety message.
16. LLM output containing unsafe recommendation.
17. Reproducibility of same input to same structured result.
18. Candidate rule accidentally routed into runtime rule engine.
19. GWAS association candidate incorrectly treated as active interpretation.
20. Compiler output missing source references.
```

## 20. Future Expansion Direction

After v0.1, future versions may add:

```text
1. Evidence viewer retrieval.
2. BM25 or hybrid evidence search.
3. Developer review workflow.
4. More wellness traits with stronger safety controls.
5. Pharmacogenomics-specific evidence models.
6. Star allele and diplotype modeling.
7. Phenotype translation.
8. Medication context modeling.
9. PGx rule modules.
10. CPIC / PharmGKB / PharmCAT / PharmVar integration.
11. Gene Domain Intent Router extraction.
12. API integration with external systems.
```

Future pharmacogenomics expansion must preserve the v0.1 architectural principles:

```text
1. Curated rules decide user-facing interpretations.
2. Evidence must be explicitly linked.
3. LLM explains but does not decide.
4. Safety validation remains part of runtime.
5. Unsupported or unsafe requests must not produce invented claims.
6. Source/compiler outputs must pass validation and review before becoming active.
```