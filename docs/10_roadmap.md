# 10 Roadmap

## 1. Purpose

OpenPGx Copilot is a public-data-driven genetic interpretation and pharmacogenomics decision-support prototype.

The long-term direction is pharmacogenomics decision support, but the repository starts with a wellness-first educational proof of concept in v0.1.

This roadmap is designed to preserve the core project strategy:

```text id="0k1vr8"
Wellness-first POC,
PGx-ready architecture.
```

The roadmap is not a commitment to clinical deployment. Each version must preserve safety, traceability, reviewability, and deterministic rule behavior.

## 2. Roadmap Principles

The roadmap follows these principles:

```text id="bkf0je"
1. Start with low-risk wellness educational traits.
2. Validate architecture before expanding scope.
3. Keep runtime interpretation rule-bound and evidence-linked.
4. Use LLMs only for explanation, not decisions.
5. Keep untrusted or uncertified compiler output candidate-only; govern the system, release diffs, and exceptions rather than manually reviewing every generated record.
6. Avoid medical, nutrition, fitness, supplement, medication, diagnosis, or disease-risk advice in v0.1.
7. Add PGx support gradually through TrustedSourceProfile-governed structured sources.
8. Prefer trusted, certified compilation from expert-curated PGx resources over direct paper-to-rule extraction.
9. Preserve auditability and regression testing at every stage.
10. Do not process real patient data until explicit governance, privacy, and clinical review requirements are defined.
```

## 3. Version Overview

```text id="6nt0bb"
v0.1 - Wellness-first educational POC
v0.2 - Certified compiler and exception review workflow
v0.3 - PGx reference-path prototype
v0.4 - OpenPGx-native PGx rule engine prototype
v0.5 - Evidence viewer and hybrid review retrieval
v0.6 - Clinical workflow simulation and clinician-review UX
v0.7 - Expanded PGx source integration
v0.8 - Safety, audit, and governance hardening
v1.0 - Research-grade PGx decision-support prototype
```

The roadmap intentionally does not jump directly from wellness traits to medication alerts.

## 4. v0.1 — Wellness-first Educational POC

### 4.1 Version Goal

v0.1 validates the core runtime architecture using low-risk wellness genetic traits.

The goal is not to provide clinical or lifestyle advice.

The goal is to prove that the system can:

```text id="8ymnlg"
synthetic rsID-genotype input
→ curated rule matching
→ rule-bound evidence lookup
→ educational explanation
→ safety validation
```

### 4.2 Scope

v0.1 includes:

```text id="hdif6v"
1. Synthetic rsID-genotype input.
2. Small curated wellness trait rule set.
3. Active RuleRecord schema.
4. Active EvidenceRecord schema.
5. SourceRecord schema.
6. Rule engine.
7. Evidence store.
8. LLM explanation layer boundary.
9. Output safety validator.
10. Minimal API.
11. Candidate-only compiler framework prototype (optional, non-release-blocking; full implementation in v0.2).
12. Evaluation plan and regression tests.
```

### 4.3 Supported Traits

Initial wellness trait candidates:

```text id="m9v2vm"
1. ALDH2 - alcohol metabolism
2. LCT / MCM6 - lactose tolerance
3. CYP1A2 - caffeine metabolism
4. ABCC11 - earwax type
5. TAS2R38 - bitter taste perception
```

### 4.4 API

v0.1 API:

```text id="7vehfu"
POST /pgx/check
GET  /pgx/rules
GET  /pgx/evidence/{evidence_id}
GET  /health
```

The core endpoint is `POST /pgx/check`.

### 4.5 Out of Scope

v0.1 does not include:

```text id="ypsf7m"
1. PGx medication alerts.
2. Medication recommendations.
3. Drug dosage recommendations.
4. Diagnosis.
5. Disease-risk prediction.
6. Real patient data.
7. Clinical EHR integration.
8. Star allele calling.
9. Haplotype or diplotype inference.
10. Phenotype translation.
11. Runtime literature retrieval for interpretation.
12. LLM-generated active rules.
```

### 4.6 Exit Criteria

v0.1 is complete when:

```text id="7ioyl7"
1. MVP-min is met: ALDH2 (rs671) works end to end as one active rule; any other trait that ships matches its expected active rule. The full five-trait set is an MVP-full target, not a release blocker.
2. Unsupported inputs do not produce invented interpretations.
3. Every matched result includes evidence_refs.
4. Every evidence_ref resolves to active EvidenceRecord.
5. Every explanation includes limitations and required safety message.
6. Unsafe advice requests are refused or downgraded.
7. Candidate rules and evidence are never used by runtime.
8. Minimal API passes integration tests.
9. Evaluation plan tests pass.
10. Documentation baseline is complete.
```

The compiler framework prototype is non-release-blocking; v0.1 may ship with hand-written rule/evidence YAML only, and full compiler delivery is a v0.2 exit criterion.

Required docs:

```text id="socrc8"
00_project_vision.md
01_safety_boundary.md
02_domain_model.md
03_mvp_scope.md
04_system_architecture.md
06_rule_engine_spec.md
07_evidence_model.md
08_llm_explanation_layer.md
09_api_spec.md
10_evaluation_plan.md
11_roadmap.md
```

Recommended additional docs:

```text id="oh97k1"
05_data_ingestion_contract.md
ADR-001-router-extraction-boundary.md
ADR-002-rule-bound-evidence-retrieval.md
ADR-003-candidate-only-compiler-output.md
```

## 5. v0.2 — Certified Compiler and Exception Review Workflow

### 5.1 Version Goal

v0.2 establishes the certified compilation and release-governance path.

The goal is to move beyond fully hand-written evidence/rule YAML by making a CertifiedCompiler the source of active records, governed at the release level: OpenPGx reviews the system, release diffs, and exceptions; it does not require per-rule manual review for every generated record.

The core governance model is trusted sources plus a certified compiler plus strong validation plus diff-based exception review plus release approval, replacing per-rule human review of every generated record.

v0.2 focuses on:

```text id="bng4ha"
TrustedSourceProfile sources
→ CertifiedCompiler
→ CompilationRun
→ ValidationReport
→ DiffReport
→ ExceptionReview
→ ReleaseApproval
→ RuntimeReleaseManifest
```

### 5.2 Scope

v0.2 includes:

```text id="2c4njt"
1. TrustedSourceProfile set and governance.
2. CertifiedCompiler and certification suite.
3. CompilationRun with reproducible provenance.
4. GWAS Catalog / dbSNP / PubMed source adapters under TrustedSourceProfile.
5. SourceSnapshot support.
6. MarkerRecord generation.
7. ValidationReport generation (strong validation).
8. DiffReport generation against the prior release.
9. ExceptionReview workflow for flagged diffs.
10. ReleaseApproval at the manifest/diff level (not per rule).
11. RuntimeReleaseManifest assembly.
12. Certified/trusted vs candidate separation tests.
```

### 5.3 Key Design Rule

```text id="4rz064"
Untrusted or uncertified compiler output remains candidate-only.
```

v0.2 must not allow:

```text id="q8mjpz"
GWAS association
→ active rule
```

without trusted-source provenance, a certified compilation, passing validation, and a release approval covering the diff.

Correct flow:

```text id="hgjqnw"
TrustedSourceProfile source
→ CertifiedCompiler CompilationRun
→ ValidationReport
→ DiffReport
→ ExceptionReview (for flagged diffs)
→ ReleaseApproval
→ RuntimeReleaseManifest
```

### 5.4 Out of Scope

v0.2 does not include:

```text id="1m6o9m"
1. Activation of uncertified or untrusted compiler output.
2. Automatic paper-to-rule extraction.
3. LLM-assigned evidence strength.
4. Large-scale SNP ingestion.
5. PGx medication alerts.
6. Real patient data.
```

### 5.5 Exit Criteria

v0.2 is complete when:

```text id="bf0brh"
1. TrustedSourceProfile governs which sources may feed the compiler.
2. CertifiedCompiler passes its certification suite; CompilationRuns are reproducible.
3. Source snapshots are versioned.
4. Active records are produced only from certified compilation over trusted sources.
5. ValidationReport is generated per CompilationRun; failed validation blocks any serving (no partial serving).
6. DiffReport is generated against the prior release, and safety-sensitive diffs require ExceptionReview.
7. ReleaseApproval is recorded at the manifest/diff level and gates the RuntimeReleaseManifest.
8. Uncertified or untrusted output cannot enter the RuntimeReleaseManifest.
9. Source traceability and compiler provenance are preserved.
10. v0.1 runtime behavior remains unchanged.
```

## 6. v0.3 — PGx Reference-path Prototype

### 6.1 Version Goal

v0.3 introduces a PGx reference path without implementing a full OpenPGx-native PGx rule engine.

The goal is to understand and validate PGx data flow using existing expert-curated tools and sources.

Primary strategy:

```text id="8yvqfl"
Use PharmCAT-compatible output or PharmCAT as a reference path.
```

This version is for architecture learning and comparison, not autonomous clinical use.

### 6.2 Scope

v0.3 may include:

```text id="7tp37h"
1. PharmCAT output adapter.
2. CPIC / ClinPGx source snapshot exploration.
3. PharmGKB / ClinPGx API exploration.
4. PharmVar source exploration.
5. PGx SourceRecord types.
6. PGx candidate evidence records.
7. PGx candidate rule records.
8. PGx review cards.
9. Synthetic PGx fixture inputs.
10. PGx output comparison against PharmCAT where possible.
```

### 6.3 PGx Reference Flow

Possible v0.3 flow:

```text id="4aohla"
synthetic genotype / VCF fixture
→ PharmCAT
→ PharmCAT output adapter
→ normalized PGx candidate records
→ review card
→ explanation prototype
```

or:

```text id="1c9b3p"
CPIC / ClinPGx / PharmGKB / PharmVar source data
→ source adapter
→ PGx candidate records
→ review card
```

### 6.4 Safety Boundary

v0.3 must not provide autonomous medication advice.

All PGx outputs must be clearly labeled as:

```text id="73ndp5"
prototype
for research / educational review only
not for clinical use
not medication advice
requires licensed clinician or pharmacist review
```

### 6.5 Out of Scope

v0.3 does not include:

```text id="ryvy5f"
1. OpenPGx-native star allele caller.
2. OpenPGx-native diplotype inference.
3. Active medication alert engine.
4. Real patient medication list processing.
5. Autonomous prescribing recommendation.
6. Clinical deployment.
```

### 6.6 Exit Criteria

v0.3 is complete when:

```text id="f3kikd"
1. PharmCAT or PharmCAT-compatible output can be parsed.
2. PGx candidate records can be generated.
3. PGx source traceability is preserved.
4. PGx outputs remain reviewer-facing or prototype-only.
5. No autonomous medication advice is returned.
6. Synthetic PGx fixtures are testable.
7. The gap between reference tools and OpenPGx-native rule engine is documented.
```

## 7. v0.4 — OpenPGx-native PGx Rule Engine Prototype

### 7.1 Version Goal

v0.4 introduces a small OpenPGx-native PGx rule engine prototype for carefully selected gene-drug pairs.

The goal is not to cover all PGx.

The goal is to validate the internal PGx domain model:

```text id="3jtx3z"
variant / star allele
→ allele function
→ diplotype
→ phenotype
→ drug-specific rule
→ evidence-bound PGx explanation
```

### 7.2 Scope

v0.4 may include:

```text id="o9wwjr"
1. AlleleDefinitionRecord.
2. AlleleFunctionRecord.
3. DiplotypePhenotypeRecord.
4. PhenotypeDefinitionRecord.
5. DrugRecommendationRule.
6. PGxEvidenceRecord.
7. Small curated PGx rule set.
8. Synthetic PGx test fixtures.
9. Comparison against PharmCAT for selected cases.
10. PGx-specific safety templates.
```

### 7.3 Candidate Gene-drug Pair Selection

v0.4 should select a small number of relatively tractable, well-documented PGx examples.

Selection criteria:

```text id="kfmbz6"
1. Strong expert-curated guideline support.
2. Clear public source availability.
3. Simple enough for prototype modeling.
4. Good synthetic fixtures available.
5. Avoid highly complex calling logic in first iteration.
```

The project should be cautious with complex genes such as CYP2D6 until the system is ready for CNV, structural variation, and complex allele handling.

### 7.4 Safety Boundary

v0.4 PGx outputs must be clinician-review oriented.

They must not be autonomous patient instructions.

Allowed:

```text id="ssstve"
This synthetic PGx result matches a curated gene-drug rule that would require clinician or pharmacist review.
```

Disallowed:

```text id="11l9ae"
You should stop this medication.
You should change your dose.
Use this drug instead.
```

### 7.5 Exit Criteria

v0.4 is complete when:

```text id="34lmvz"
1. Selected PGx gene-drug examples can be represented in OpenPGx-native records.
2. Synthetic PGx fixtures produce expected structured PGx results.
3. PGx evidence references resolve.
4. PGx safety validator blocks medication advice.
5. PharmCAT comparison tests pass where applicable.
6. The system remains prototype-only and non-clinical.
```

## 8. v0.5 — Evidence Viewer and Hybrid Review Retrieval

### 8.1 Version Goal

v0.5 adds retrieval for reviewer and developer workflows, not for direct runtime interpretation.

The goal is to support evidence discovery, candidate review, and audit.

### 8.2 Scope

v0.5 may include:

```text id="qkgxrs"
1. Evidence viewer UI or API.
2. BM25 search over evidence records and candidates.
3. Optional dense retrieval over reviewer-facing records.
4. Metadata filters by gene, marker, trait, drug, source type, status.
5. Evidence conflict review.
6. Candidate diff reports.
7. Reviewer annotation workflow.
```

### 8.3 Retrieval Boundary

Allowed:

```text id="xfi23b"
reviewer query
→ evidence search
→ evidence cards
→ human review
```

Disallowed:

```text id="pkdms3"
user query
→ top-k retrieval
→ LLM decides interpretation
```

Runtime interpretation must remain rule-bound.

### 8.4 Exit Criteria

v0.5 is complete when:

```text id="ylhjmg"
1. Reviewers can search evidence and candidates.
2. Search results are clearly labeled active vs candidate.
3. Retrieval does not affect runtime interpretation.
4. Evidence review workflow improves curation efficiency.
5. Candidate and active separation remains enforced.
```

## 9. v0.6 — Clinical Workflow Simulation and Clinician-review UX

### 9.1 Version Goal

v0.6 explores how OpenPGx Copilot outputs might fit into clinician or pharmacist review workflows.

This is still not clinical deployment.

The goal is workflow simulation.

### 9.2 Scope

v0.6 may include:

```text id="vzpr0q"
1. Clinician-review dashboard prototype.
2. PGx alert explanation cards.
3. Evidence trace display.
4. Questions-to-ask-clinician template.
5. Audit trail view.
6. Safety downgrade/refusal visibility.
7. Synthetic medication context fixtures.
```

### 9.3 Safety Boundary

v0.6 must clearly label outputs as:

```text id="1w6504"
prototype
synthetic
not for clinical use
requires licensed clinician / pharmacist review
```

It must not process real patient data without governance review.

### 9.4 Exit Criteria

v0.6 is complete when:

```text id="4ey9w4"
1. Synthetic PGx results can be displayed in review-friendly form.
2. Evidence trace is visible.
3. Safety boundary is visible.
4. Audit trail is visible.
5. No autonomous medication advice is provided.
```

## 10. v0.7 — Expanded PGx Source Integration

### 10.1 Version Goal

v0.7 expands PGx source ingestion and normalization.

The goal is broader coverage of trusted PGx sources while preserving candidate-only ingestion and review gates.

### 10.2 Scope

v0.7 may include:

```text id="hskmz6"
1. CPIC / ClinPGx guideline table adapters.
2. PharmGKB / ClinPGx API adapters.
3. PharmVar adapter.
4. FDA / openFDA label adapter.
5. Drug identifier normalization.
6. Gene identifier normalization.
7. Phenotype controlled vocabulary.
8. Recommendation strength mapping.
9. Source version comparison.
10. PGx source diff reports.
```

### 10.3 Exit Criteria

v0.7 is complete when:

```text id="1r5cjo"
1. Multiple PGx sources can be ingested into normalized candidate records.
2. Source versions are pinned.
3. PGx candidate records include source traceability.
4. Cross-source comparison reports can be generated.
5. Active PGx rule promotion remains review-gated.
```

## 11. v0.8 — Safety, Audit, and Governance Hardening

### 11.1 Version Goal

v0.8 strengthens safety, auditability, governance, and deployment readiness.

The goal is not yet clinical deployment, but stronger governance posture.

### 11.2 Scope

v0.8 may include:

```text id="z1bigw"
1. Stronger audit logs.
2. Rule and evidence approval records.
3. Reviewer identity and sign-off metadata.
4. Versioned release manifests.
5. Safety policy test suite expansion.
6. Red-team unsafe prompt tests.
7. Data privacy review checklist.
8. Deployment configuration hardening.
9. Model output monitoring for LLM explanation layer.
10. Stronger fallback template system.
```

### 11.3 Exit Criteria

v0.8 is complete when:

```text id="ztx22t"
1. Every active release has trusted-source provenance, certified-compiler provenance, validation reports, a diff report, resolved exception reviews, and a release approval.
2. Every active evidence record has source traceability.
3. Every release has an audit manifest.
4. Safety tests block unsafe output.
5. LLM output monitoring is available.
6. Candidate-to-active promotion is auditable.
```

## 12. v1.0 — Research-grade PGx Decision-support Prototype

### 12.1 Version Goal

v1.0 is a research-grade, public-data-driven PGx decision-support prototype.

It should still be clearly bounded and not marketed as autonomous clinical decision software.

The goal is to demonstrate an end-to-end, auditable PGx interpretation architecture using public curated sources and synthetic or approved non-production data.

### 12.2 Scope

v1.0 may include:

```text id="v3n9st"
1. Wellness educational module.
2. PGx prototype module.
3. Active curated PGx rule set for selected gene-drug pairs.
4. PGx evidence traceability.
5. Clinician-review-oriented explanation layer.
6. Evidence viewer.
7. Reviewer workflow.
8. Rule/evidence release management.
9. Strong safety validator.
10. Minimal API for PGx checks.
11. Full regression suite.
```

### 12.3 v1.0 Must Still Not Do

Unless formal clinical, legal, regulatory, and privacy requirements are addressed, v1.0 must not:

```text id="aw1xxs"
1. Provide autonomous medication advice.
2. Replace clinicians or pharmacists.
3. Process real patient data without governance.
4. Be used for prescribing decisions.
5. Claim diagnostic capability.
6. Claim disease-risk prediction capability.
```

### 12.4 Exit Criteria

v1.0 is complete when:

```text id="m2z3iv"
1. Selected PGx gene-drug examples work end-to-end.
2. Rule/evidence traceability is complete.
3. Safety validation is mandatory and passing.
4. Candidate/active separation is enforced.
5. LLM explanation boundary is enforced.
6. Reviewer workflow is functional.
7. Regression tests cover supported wellness and PGx examples.
8. Documentation is complete.
9. Limitations and non-clinical status are explicit.
```

## 13. Cross-version Capability Matrix

| Capability                   |      v0.1 |     v0.2 |     v0.3 |      v0.4 |      v0.5 |     v0.6 |     v0.7 |                v0.8 |                v1.0 |
| ---------------------------- | --------: | -------: | -------: | --------: | --------: | -------: | -------: | ------------------: | ------------------: |
| Wellness runtime rules       |       Yes |      Yes |      Yes |       Yes |       Yes |      Yes |      Yes |                 Yes |                 Yes |
| Rule-bound evidence lookup   |       Yes |      Yes |      Yes |       Yes |       Yes |      Yes |      Yes |                 Yes |                 Yes |
| Candidate-only compiler      | Prototype |      Yes |      Yes |       Yes |       Yes |      Yes |      Yes |                 Yes |                 Yes |
| GWAS/dbSNP/PubMed adapters   |  Optional |      Yes |      Yes |       Yes |       Yes |      Yes |      Yes |                 Yes |                 Yes |
| Evidence review cards        |  Optional |      Yes |      Yes |       Yes |       Yes |      Yes |      Yes |                 Yes |                 Yes |
| Runtime RAG interpretation   |        No |       No |       No |        No |        No |       No |       No |                  No |                  No |
| LLM as decision layer        |        No |       No |       No |        No |        No |       No |       No |                  No |                  No |
| PharmCAT reference path      |        No |       No |      Yes |       Yes |       Yes |      Yes |      Yes |                 Yes |                 Yes |
| OpenPGx-native PGx rules     |        No |       No |       No | Prototype | Prototype | Expanded | Expanded |            Hardened |     Selected active |
| Medication advice            |        No |       No |       No |        No |        No |       No |       No |                  No |       No autonomous |
| Real patient data            |        No |       No |       No |        No |        No |       No |       No | Governance required | Governance required |
| Evidence viewer retrieval    |        No | Optional | Optional |  Optional |       Yes |      Yes |      Yes |                 Yes |                 Yes |
| Clinician-review UX          |        No |       No |       No |  Optional |  Optional |      Yes |      Yes |                 Yes |                 Yes |
| Audit / governance hardening |     Basic |    Basic |    Basic |     Basic |    Medium |   Medium |   Medium |              Strong |              Strong |

## 14. Versioning Strategy

The project should version:

```text id="g1y5h1"
1. Application version.
2. API version.
3. Schema version.
4. Rule set version.
5. Evidence set version.
6. Source snapshot version.
7. Safety policy version.
8. Prompt template version.
9. Evaluation suite version.
```

Example:

```yaml id="56fzbv"
app_version: "0.1.0"
api_version: "0.1"
schema_version: "0.1"
rule_set_id: wellness_rules_v0_1_2026_07
evidence_set_id: wellness_evidence_v0_1_2026_07
safety_policy_version: wellness_safety_v0_1
prompt_template_version: llm_explanation_v0_1
evaluation_suite_version: eval_v0_1
```

## 15. Release Gate Policy

Every version must pass:

```text id="12kv3m"
1. Rule correctness tests.
2. Evidence traceability tests.
3. Safety tests.
4. Unsupported input tests.
5. LLM output validation tests.
6. Regression tests.
```

Versions with ingestion or compiler changes must also pass:

```text id="jj6qu1"
1. Candidate/active separation tests.
2. Source adapter tests.
3. Source snapshot validation.
4. Review card generation tests.
```

Versions with PGx changes must also pass:

```text id="ztol70"
1. PGx source traceability tests.
2. Allele / phenotype / rule compatibility tests.
3. PharmCAT comparison tests where applicable.
4. Medication advice blocking tests.
```

## 16. Non-goals Across All Versions

Unless explicitly re-scoped with clinical, legal, regulatory, and privacy review, OpenPGx Copilot must not become:

```text id="w2rheo"
1. A prescribing system.
2. A diagnostic system.
3. A disease-risk prediction system.
4. A medication management system.
5. A replacement for clinicians or pharmacists.
6. A consumer health recommendation engine.
7. A nutrition, fitness, supplement, or lifestyle coaching system.
8. A runtime RAG chatbot that interprets genetics from top-k literature.
```

## 17. Roadmap Risks

Key risks:

```text id="u9g2an"
1. Wellness associations being overinterpreted as lifestyle advice.
2. PGx outputs being mistaken for medication recommendations.
3. Candidate records leaking into runtime.
4. LLM inventing citations or advice.
5. Source version drift.
6. Rule/evidence mismatch.
7. Complex PGx genes requiring unsupported calling logic.
8. Weak source trust (untrusted or misgoverned sources feeding the compiler).
9. Weak compiler certification (an uncertified or under-tested compiler producing active records).
10. Missed diff exception (a safety-sensitive release diff activated without exception review).
11. Public source licensing constraints.
12. Real patient data governance gaps.
```

Mitigations:

```text id="tyfmej"
1. Keep v0.1 educational only.
2. Use candidate/active separation.
3. Require evidence_refs for every active rule.
4. Use deterministic rule engine.
5. Use safety validator on every output.
6. Prefer expert-curated PGx sources.
7. Use PharmCAT as reference path before native PGx engine.
8. Govern trusted sources through TrustedSourceProfile.
9. Certify the compiler through a compiler certification suite.
10. Require mandatory ExceptionReview for safety-sensitive diffs, gated by ReleaseApproval.
11. Version source snapshots.
12. Do not process real patient data until governance exists.
```
