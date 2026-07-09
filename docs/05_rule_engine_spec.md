# 05 Rule Engine Spec

## 1. Purpose

This document defines the rule engine specification for OpenPGx Copilot v0.1.

OpenPGx Copilot v0.1 is a wellness-first educational proof of concept. The rule engine is responsible for deterministic domain matching between synthetic rsID-genotype inputs and active curated wellness trait rules.

The rule engine is not a chatbot, not a retrieval engine, and not an LLM reasoning component.

The rule engine answers:

```text
Given a validated structured input, does any active curated rule match?
```

It does not answer:

```text
What should the user do?
What medical, nutrition, fitness, supplement, or medication action should be taken?
What can be inferred from unsupported markers?
What does the literature say in general?
```

## 2. Scope

This spec applies to the v0.1 wellness trait rule engine.

v0.1 supports:

```text
synthetic rsID-genotype input
→ active marker-level wellness RuleRecord matching
→ structured TraitInterpretationResult generation
→ rule-bound evidence reference validation
```

v0.1 does not support:

```text
haplotype inference
diplotype inference
star allele calling
phenotype translation
medication context
PGx drug recommendations
diagnosis
disease-risk prediction
real patient data
runtime literature retrieval
LLM-generated rules
```

Future PGx modules may extend the rule engine with allele, diplotype, phenotype, medication, and drug recommendation logic, but those are out of scope for v0.1.

## 3. Rule Engine Responsibilities

The rule engine is responsible for:

```text
1. Loading active RuleRecords from the active rule set.
2. Validating RuleRecords before runtime use.
3. Rejecting candidate, inactive, deprecated, or invalid rules.
4. Validating that each active rule has resolvable evidence_refs.
5. Matching validated rsID-genotype inputs against active rules.
6. Returning deterministic structured match results.
7. Reporting unsupported markers or unmatched genotypes.
8. Preserving traceability from result → rule → evidence.
9. Supporting regression-testable behavior.
```

The rule engine is not responsible for:

```text
1. Parsing arbitrary natural language.
2. Assigning request intent.
3. Performing safety route classification.
4. Fetching papers at runtime.
5. Performing top-k retrieval.
6. Summarizing evidence.
7. Producing final user-facing prose.
8. Providing medical, nutrition, fitness, supplement, or medication advice.
9. Creating new rules.
10. Promoting candidate rules to active rules.
```

## 4. Runtime Position

The rule engine sits after request validation and before evidence lookup.

Runtime path:

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

The rule engine receives only validated structured inputs.

The rule engine returns structured rule match results.

It does not directly produce final user-facing explanations.

## 5. Inputs to Rule Engine

The rule engine receives a `ValidatedInterpretationRequest`.

Example:

```json
{
  "request_id": "req-001",
  "user_id": "demo-001",
  "domain": "genetic_wellness",
  "target_module": "wellness_traits",
  "response_mode": "educational_explanation",
  "safety_route": "allowed",
  "markers": [
    {
      "rsid": "rs671",
      "genotype": "AG"
    }
  ],
  "blocked_outputs": [
    "medical_advice",
    "nutrition_advice",
    "fitness_advice",
    "supplement_advice",
    "medication_advice",
    "diagnosis",
    "disease_risk_prediction"
  ]
}
```

Required fields:

```text
request_id
domain
target_module
response_mode
safety_route
markers
blocked_outputs
```

Each marker input must include:

```text
rsid
genotype
```

v0.1 assumes inputs are synthetic.

## 6. Input Pre-conditions

Before rule engine execution, the Request Validator must ensure:

```text
1. target_system is openpgx_copilot.
2. target_module is wellness_traits.
3. domain is genetic_wellness.
4. response_mode is supported.
5. safety_route is compatible with execution.
6. rsID format is valid.
7. genotype format is valid.
8. blocked output categories are present.
9. Request does not require medical, nutrition, fitness, supplement, medication, diagnosis, or disease-risk output.
```

The rule engine may repeat critical validations defensively, especially:

```text
1. rsID format.
2. genotype format.
3. active rule status.
4. evidence_refs presence.
5. candidate/active separation.
```

## 7. RuleRecord Schema

The v0.1 rule engine loads `RuleRecord` objects.

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

Required fields:

```text
id
status
domain
markers
interpretation_level
result_code
evidence_refs
required_safety_message
```

Recommended fields:

```text
gene
trait
rule_version
created_at
updated_at
review_status
test_status
notes
```

## 8. RuleRecord Status

The rule engine may load only rules with:

```yaml
status: active
```

The rule engine must reject rules with:

```text
candidate
inactive
deprecated
draft
pending_review
```

Candidate rules are not runtime rules.

Example invalid rule:

```yaml
id: rule_candidate_aldh2_rs671_alcohol_metabolism_001
status: candidate
domain: wellness_trait
gene: ALDH2
trait: alcohol_metabolism
markers:
  - rsid: rs671
    genotype_pattern_candidate: "AG|AA"
```

This must not be loaded by the runtime rule engine.

## 9. Rule Domain

v0.1 active runtime rules must use:

```yaml
domain: wellness_trait
```

Future domains may include:

```text
pharmacogenomics
```

but PGx rules are out of scope for v0.1.

The rule engine must reject v0.1 rules with unsupported domain values.

## 10. Interpretation Level

v0.1 supports only:

```yaml
interpretation_level: educational
```

The rule engine must reject active v0.1 rules with interpretation levels such as:

```text
clinical
diagnostic
prescriptive
therapeutic
nutritional
fitness
supplement
medication
```

This ensures the rule engine cannot become a medical or lifestyle recommendation engine in v0.1.

## 11. Marker Pattern Model

Each RuleRecord includes one or more marker patterns.

Single-marker example:

```yaml
markers:
  - rsid: rs671
    genotype_pattern: "AG|AA"
```

Multi-marker example:

```yaml
markers:
  - rsid: rs713598
    genotype_pattern: "CC|CG"
  - rsid: rs1726866
    genotype_pattern: "GG|GA"
  - rsid: rs10246939
    genotype_pattern: "TT|TC"
```

v0.1 supports:

```text
1. Single-marker rules.
2. Simple all-required multi-marker rules.
3. Genotype pattern matching using normalized genotype strings.
```

v0.1 does not support:

```text
1. Probabilistic matching.
2. Polygenic scoring.
3. Haplotype inference beyond explicit simple marker combinations.
4. Missing marker imputation.
5. Population-specific rule activation.
6. Environment or lifestyle modifiers.
```

## 12. Genotype Normalization

The rule engine should normalize genotype strings before matching.

Normalization rules:

```text
1. Trim whitespace.
2. Convert to uppercase.
3. Remove separators such as "/", "|", spaces when appropriate.
4. Sort alleles lexicographically for unphased diploid genotypes.
5. Preserve original input genotype for audit/debug output.
```

Examples:

```text
"A/G" → "AG"
"g/a" → "AG"
"GA"  → "AG"
"A A" → "AA"
```

For v0.1, genotypes are treated as unphased diploid calls unless otherwise specified.

The rule engine must not infer a genotype when input is missing or invalid.

## 13. rsID Normalization

The rule engine should normalize rsID strings before matching.

Normalization rules:

```text
1. Trim whitespace.
2. Convert prefix to lowercase.
3. Require pattern: rs followed by digits.
```

Examples:

```text
"RS671" → "rs671"
" rs671 " → "rs671"
```

Invalid examples:

```text
"671"
"rsABC"
"chr12:..."
"ALDH2"
```

The rule engine must not interpret invalid rsID inputs.

## 14. Genotype Pattern Syntax

v0.1 genotype patterns are simple string patterns.

Supported syntax:

```text
AA
AG
GG
AG|AA
CC|CT|TT
```

Meaning:

```text
"AG|AA" means genotype equals AG or AA after normalization.
```

Pattern rules:

```text
1. Patterns are pipe-separated allowed normalized genotypes.
2. Each genotype must be valid for the marker.
3. Alleles must be uppercase.
4. No regex features are supported in v0.1.
5. No negation is supported in v0.1.
6. No dosage expressions are supported in v0.1.
```

Disallowed v0.1 pattern examples:

```text
A+
not GG
AG.*
one copy of A
risk_allele >= 1
```

The rule engine must treat genotype patterns as exact allowed-value sets, not arbitrary regex.

## 15. Match Semantics

v0.1 supports two rule types:

```text
single_marker_all_required
multi_marker_all_required
```

Single-marker rule match:

```text
A rule matches if the input contains the required rsID and the normalized genotype is in genotype_pattern.
```

Multi-marker all-required rule match:

```text
A rule matches if all marker patterns in the rule are present in the input and each normalized genotype matches its corresponding genotype_pattern.
```

v0.1 does not support partial matches as positive interpretations.

If a multi-marker rule is missing one or more markers, the result must be:

```text
unsupported_or_insufficient_input
```

not a guessed interpretation.

## 16. Match Result Types

The rule engine may return:

```text
matched
unsupported_marker
unmatched_genotype
insufficient_markers
invalid_input
conflicted_input
duplicate_ignored
blocked_by_safety
rule_validation_error
```

Definitions:

```text
matched:
A validated active rule matched the input.

unsupported_marker:
No active rule exists for the provided marker.

unmatched_genotype:
The marker is supported, but the genotype does not match any active interpretation rule.

insufficient_markers:
A multi-marker rule may require additional markers that were not provided.

invalid_input:
The input marker or genotype failed validation.

conflicted_input:
The same rsID was provided more than once with differing normalized genotypes;
the rsID is excluded from matching (see Multi-Input Semantics).

duplicate_ignored:
An exact duplicate of an earlier normalized input; ignored after the first (see
Multi-Input Semantics).

blocked_by_safety:
The request was not eligible for rule matching due to safety route or blocked output.

rule_validation_error:
An active rule set contains invalid rule configuration and should not be used.
```

## 17. Rule Engine Output

The rule engine returns a `RuleEngineResult`.

Example matched output:

```json
{
  "request_id": "req-001",
  "status": "matched",
  "matches": [
    {
      "rule_id": "aldh2_rs671_alcohol_metabolism",
      "domain": "wellness_trait",
      "trait": "alcohol_metabolism",
      "gene": "ALDH2",
      "matched_markers": [
        {
          "rsid": "rs671",
          "input_genotype": "AG",
          "normalized_genotype": "AG"
        }
      ],
      "interpretation_level": "educational",
      "result_code": "reduced_aldh2_activity_association",
      "evidence_refs": [
        "evidence_aldh2_rs671_001"
      ],
      "required_safety_message": "wellness_educational"
    }
  ],
  "unsupported_inputs": [],
  "warnings": []
}
```

Example unsupported output:

```json
{
  "request_id": "req-002",
  "status": "unsupported_marker",
  "matches": [],
  "unsupported_inputs": [
    {
      "rsid": "rs999999",
      "genotype": "AG",
      "reason": "No active v0.1 rule supports this marker."
    }
  ],
  "warnings": [
    "Unsupported markers must not be interpreted."
  ]
}
```

Example unmatched genotype output:

```json
{
  "request_id": "req-003",
  "status": "unmatched_genotype",
  "matches": [],
  "unsupported_inputs": [
    {
      "rsid": "rs671",
      "genotype": "GG",
      "reason": "Marker is supported, but this genotype does not match an active interpretation rule."
    }
  ],
  "warnings": [
    "No interpretation was generated."
  ]
}
```

## 17a. Multi-Input (Batch) Semantics

`ValidatedInterpretationRequest` may carry multiple marker inputs. The engine processes them deterministically so the same batch always yields the same result.

The result carries two arrays: `input_results[]` (one entry per input marker, with a per-input status) and `matches[]` (one entry per matched rule). A matched input references its rule via `matched_rule_id`; a multi-marker rule produces several matched `input_results` that map to a single `matches[]` entry.

Processing rules:

```text
1. Every input marker appears exactly once in input_results[].
2. Exact duplicate normalized inputs are deduplicated: the first is kept, later
   identical inputs get status duplicate_ignored plus a warning.
3. The same rsID with differing normalized genotypes is a conflict: all entries for
   that rsID get status conflicted_input and the rsID is excluded from matching.
4. An invalid marker/genotype is a per-input invalid_input; it does not abort the batch.
5. Matching runs only on the remaining valid, non-duplicate, non-conflicted inputs.
6. unsupported_marker, unmatched_genotype, insufficient_markers, invalid_input, and
   conflicted_input are terminal for that input and must never be turned into an
   interpretation by the LLM or any downstream layer.
```

Overall `interpretation_status` (ignoring duplicate_ignored entries):

```text
matched           - at least one input matched and all remaining inputs matched.
partial_success   - at least one input matched and at least one did not.
no_match          - no input matched.
blocked_by_safety - the safety route refused the request; matching is not performed.
```

Example mixed result:

```json
{
  "request_id": "req-010",
  "interpretation_status": "partial_success",
  "input_results": [
    { "rsid": "rs671", "normalized_genotype": "AG", "status": "matched", "matched_rule_id": "aldh2_rs671_alcohol_metabolism" },
    { "rsid": "rs999999", "normalized_genotype": "AG", "status": "unsupported_marker" },
    { "rsid": "rsABC", "input_genotype": "XZ", "status": "invalid_input" },
    { "rsid": "rs762551", "normalized_genotype": "AA", "status": "conflicted_input" },
    { "rsid": "rs762551", "normalized_genotype": "AC", "status": "conflicted_input" },
    { "rsid": "rs4988235", "normalized_genotype": "AA", "status": "duplicate_ignored" }
  ],
  "matches": [
    {
      "rule_id": "aldh2_rs671_alcohol_metabolism",
      "trait": "alcohol_metabolism",
      "matched_markers": [ { "rsid": "rs671", "normalized_genotype": "AG" } ],
      "interpretation_level": "educational",
      "result_code": "reduced_aldh2_activity_association",
      "evidence_refs": ["evidence_aldh2_rs671_001"]
    }
  ],
  "warnings": [
    "rs4988235 AA was a duplicate and was ignored.",
    "rs762551 had conflicting genotypes and was excluded from matching."
  ]
}
```

## 18. Evidence Reference Validation

Every active rule must contain at least one `evidence_ref`.

At rule loading time, the rule engine or registry validator must check:

```text
1. evidence_refs is present.
2. evidence_refs is non-empty.
3. Every evidence_ref resolves to an EvidenceRecord.
4. Every referenced EvidenceRecord has status active.
5. Every referenced EvidenceRecord allows educational_explanation.
6. No referenced EvidenceRecord disallows the requested response mode.
```

A rule with missing or invalid evidence_refs must not be loaded.

Example invalid rule:

```yaml
id: invalid_aldh2_rule
status: active
domain: wellness_trait
markers:
  - rsid: rs671
    genotype_pattern: "AG|AA"
interpretation_level: educational
result_code: reduced_aldh2_activity_association
evidence_refs: []
required_safety_message: wellness_educational
```

Expected behavior:

```text
Rule loading fails.
The rule is not available at runtime.
```

## 19. Safety Compatibility

The rule engine must respect safety constraints from the validated request.

The rule engine may execute only when the safety route is compatible with educational output.

Allowed runtime matching safety routes:

```text
allowed
downgrade_to_educational
```

Routes that should not produce normal rule interpretation:

```text
refuse_personalized_advice
refuse_medical_advice
refuse_nutrition_advice
refuse_fitness_advice
refuse_supplement_advice
refuse_medication_advice
refuse_disease_risk
out_of_scope
```

For `unsupported_input`, the rule engine may be used only to confirm unsupported status, not to infer interpretation.

## 20. Blocked Output Enforcement

The rule engine must not return result types implying blocked outputs.

Blocked output categories:

```text
medical_advice
nutrition_advice
fitness_advice
supplement_advice
medication_advice
diagnosis
disease_risk_prediction
treatment_recommendation
```

The rule engine result must not contain fields such as:

```text
recommendation
dosage
diet_plan
exercise_plan
supplement_plan
diagnosis
disease_risk
treatment_action
```

v0.1 result fields must remain educational and evidence-linked.

## 21. Determinism Requirements

The rule engine must be deterministic.

For the same:

```text
input
active rule set
schema version
normalization version
```

the rule engine must produce the same structured result.

The rule engine must not depend on:

```text
LLM sampling
runtime search ranking
network calls
non-versioned external source state
implicit current literature
```

Runtime rule matching must be reproducible in regression tests.

## 22. Runtime Data Access

The rule engine may access:

```text
1. Active RuleRecords.
2. Active EvidenceRecord metadata required for validation.
3. MarkerRecord metadata required for validation, if available.
4. Controlled vocabularies.
5. Safety templates by ID.
```

The rule engine must not access:

```text
1. Candidate RuleRecords for matching.
2. Candidate EvidenceRecords for matching.
3. Raw papers for matching.
4. Runtime top-k search results for matching.
5. LLM-generated interpretations for matching.
```

## 23. Rule Loading Process

At startup or release load time:

```text
1. Load RuleSetRelease metadata.
2. Confirm RuleSetRelease status is active.
3. Load referenced RuleRecords.
4. Validate every RuleRecord schema.
5. Reject any non-active RuleRecord.
6. Validate marker patterns.
7. Validate interpretation_level.
8. Validate evidence_refs.
9. Validate required_safety_message.
10. Build in-memory rule index.
```

v0.1 uses strict mode only. If any active RuleRecord or referenced active EvidenceRecord fails validation, the entire rule set load must fail:

```text
strict mode (v0.1, required):
Any active rule or evidence validation failure fails the whole load.
The service must fail startup (fail-closed). If a deployment is started for
diagnostics, /health and /pgx/check must return 503 and must not serve.
```

Quarantine / degraded mode (excluding invalid rules and serving a partial active set) is not part of v0.1. It is dev-only or future work and must never serve a partial active set in a released v0.1.

## 24. Rule Indexing

The rule engine should build an index for deterministic matching.

Recommended index:

```text
rsid → list[RuleRecord]
```

Example:

```text
rs671 → [aldh2_rs671_alcohol_metabolism]
rs4988235 → [lct_mcm6_rs4988235_lactose_tolerance]
rs762551 → [cyp1a2_rs762551_caffeine_metabolism]
```

For multi-marker rules, each marker may point to the rule, but the engine must verify all required markers before returning a match.

## 25. Conflict Handling

v0.1 should avoid conflicting active rules.

A conflict exists if two active rules:

```text
1. Match the same marker/genotype pattern.
2. Produce incompatible result_code values.
3. Refer to the same trait but conflicting interpretation summaries.
```

At rule loading time, the engine should detect conflicts.

Conflict policy:

```text
1. Fail rule set load in strict mode.
2. Require human review.
3. Do not let LLM choose between conflicting rules.
```

Allowed non-conflict:

```text
The same genotype may match multiple distinct traits only if explicitly reviewed and approved.
```

Example:

```text
A marker matching both earwax type and another trait should require explicit multi-trait review.
```

## 26. Multi-Marker Rule Handling

TAS2R38 may be used to test simple multi-marker rules.

Example candidate active rule shape:

```yaml
id: tas2r38_bitter_taste_multi_marker
status: active
domain: wellness_trait
gene: TAS2R38
trait: bitter_taste_perception
markers:
  - rsid: rs713598
    genotype_pattern: "CC"
  - rsid: rs1726866
    genotype_pattern: "GG"
  - rsid: rs10246939
    genotype_pattern: "TT"
interpretation_level: educational
result_code: bitter_taste_perception_association
evidence_refs:
  - evidence_tas2r38_bitter_taste_001
required_safety_message: wellness_educational
```

All marker patterns must match.

If only one or two markers are provided, the engine must return insufficient markers, not a partial interpretation.

## 27. Unsupported Input Handling

Unsupported input is a first-class result.

The rule engine must not try to interpret unsupported markers.

Examples:

```text
rs999999 AG
ACTN3 rs1815739 CT
FTO rs9939609 AA
```

If these are not active v0.1 rules, the engine must return unsupported status.

The rule engine must not call retrieval or LLM to fill the gap.

## 28. Unmatched Supported Marker Handling

A marker may be supported by the rule set, but a specific genotype may not match an interpretation rule.

Example:

```text
rs671 GG
```

If active rules only define `AG|AA`, then `GG` should return `unmatched_genotype`.

The system may explain:

```text
This marker is recognized by the active v0.1 rule set, but the provided genotype does not match an active interpretation rule.
```

It must not infer a negative or normal interpretation unless there is an explicit active rule for that genotype.

## 29. Rule Engine and Evidence Store Boundary

The rule engine does not own evidence content.

It validates evidence references and returns evidence_refs.

The Evidence Store resolves full evidence records after rule matching.

Boundary:

```text
Rule Engine:
- match input to active rule
- return evidence_refs

Evidence Store:
- resolve evidence_refs
- return evidence summaries, limitations, source metadata, allowed_use, disallowed_use
```

The rule engine may check evidence existence at load time, but it should not generate evidence summaries.

## 30. Rule Engine and Explanation Layer Boundary

The rule engine does not generate final prose.

It returns structured match results.

The Explanation Layer generates user-facing educational explanations from:

```text
RuleEngineResult
EvidenceRecord
SourceRecord metadata
SafetyRoute
Safety templates
```

The Explanation Layer must not alter rule match decisions.

## 31. Rule Engine and LLM Boundary

The LLM must not participate in rule matching.

Disallowed:

```text
input genotype
→ LLM decides matching rule
```

Allowed:

```text
rule engine output
+ evidence snippets
→ LLM-assisted educational explanation
```

The LLM must not:

```text
1. Add a rule that did not match.
2. Remove a rule that matched.
3. Change result_code.
4. Change evidence_refs.
5. Change interpretation_level.
6. Convert interpretation into advice.
```

## 32. Candidate Rule Boundary

Candidate rules may exist in the repository or registry, but runtime must exclude them.

Candidate records may be used by:

```text
1. Review workflows.
2. Diff reports.
3. Human curation.
4. Candidate compiler tests.
```

Candidate records must not be used by:

```text
1. Runtime Rule Engine.
2. User-facing interpretation.
3. Active RuleSetRelease.
```

Required test:

```text
If a RuleCandidateRecord is placed in candidate storage, the runtime Rule Engine must not load or match it.
```

## 33. Error Handling

The rule engine should return structured errors.

Examples:

```json
{
  "request_id": "req-004",
  "status": "invalid_input",
  "matches": [],
  "errors": [
    {
      "code": "invalid_rsid_format",
      "message": "Invalid rsID format. Expected pattern rs followed by digits.",
      "field": "markers[0].rsid"
    }
  ]
}
```

```json
{
  "request_id": "req-005",
  "status": "rule_validation_error",
  "matches": [],
  "errors": [
    {
      "code": "missing_evidence_refs",
      "message": "Active rule invalid_aldh2_rule has no evidence references.",
      "rule_id": "invalid_aldh2_rule"
    }
  ]
}
```

Errors must be machine-readable and testable.

## 34. Logging and Audit Trail

The rule engine should log:

```text
1. request_id.
2. active rule set version.
3. normalized marker inputs.
4. matched rule IDs.
5. unmatched or unsupported inputs.
6. evidence_refs returned.
7. rule engine status.
8. validation errors.
```

Logs must not contain real patient data in v0.1.

Since v0.1 uses synthetic inputs only, logs should still avoid unnecessary sensitive data patterns.

## 35. Release Integration

The rule engine loads rules through the active `RuntimeReleaseManifest` (see 02_domain_model.md section 18a), never by picking a `RuleSetRelease` on its own. The manifest pins one coherent bundle: the `rule_set_id`, the `evidence_set_id`, `source_snapshot_refs`, and the `schema_version` / `normalization_version` they share.

The rule engine loads only the `rule_set_id` and `evidence_set_id` named by the active manifest, and must verify:

```text
1. The rule set and evidence set match the manifest schema_version and normalization_version.
2. The rule set and evidence set match the manifest source_snapshot_refs.
3. Every evidence_ref in the rule set resolves within the manifest's pinned evidence set.
4. review_status and test_status are approved/passed on the manifest and both sets.
```

The referenced `RuleSetRelease` example:

```yaml
rule_set_id: wellness_rules_v0_1_2026_07
status: active
domain: wellness_trait
created_at: "2026-07-07"
schema_version: "0.1"
normalization_version: "0.1"
review_status: approved
test_status: passed
active_rule_refs:
  - aldh2_rs671_alcohol_metabolism
active_evidence_refs:
  - evidence_aldh2_rs671_001
```

The rule engine must reject a rule set if:

```text
1. status is not active.
2. review_status is not approved.
3. test_status is not passed.
4. schema_version is unsupported.
5. active_rule_refs includes candidate or invalid rules.
6. active_evidence_refs includes unresolved evidence.
7. It is not the rule_set_id pinned by the active RuntimeReleaseManifest.
8. Its schema_version, normalization_version, or source_snapshot_refs disagree with the manifest or the pinned evidence set.
```

## 36. Suggested Interfaces

### RuleEngine

```python
class RuleEngine:
    def load_rule_set(self, rule_set_id: str) -> RuleSetLoadResult:
        ...

    def match(self, request: ValidatedInterpretationRequest) -> RuleEngineResult:
        ...
```

### RuleSetLoadResult

```python
class RuleSetLoadResult:
    rule_set_id: str
    status: str
    loaded_rule_count: int
    rejected_rule_count: int
    errors: list[RuleValidationError]
    warnings: list[str]
```

### RuleEngineResult

```python
class RuleEngineResult:
    request_id: str
    status: str
    matches: list[RuleMatch]
    unsupported_inputs: list[UnsupportedInput]
    errors: list[RuleEngineError]
    warnings: list[str]
```

### RuleMatch

```python
class RuleMatch:
    rule_id: str
    domain: str
    trait: str
    gene: str | None
    matched_markers: list[MatchedMarker]
    interpretation_level: str
    result_code: str
    evidence_refs: list[str]
    required_safety_message: str
```

## 37. Implementation Notes

Recommended implementation approach for v0.1:

```text
1. Store active RuleRecords as YAML.
2. Store active EvidenceRecords as YAML.
3. Store RuleSetRelease metadata as YAML.
4. Load records at startup.
5. Validate with Pydantic or equivalent schema validation.
6. Build rsID-based in-memory index.
7. Use deterministic exact matching.
8. Return structured JSON-compatible results.
9. Keep explanation generation outside rule engine.
10. Add regression tests for every active rule.
```

The first implementation should favor clarity and auditability over optimization.

## 38. v0.1 Example Active Rules

Initial active rule candidates to curate:

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

Presence in this list does not make a rule active.

A rule is active only if:

```text
1. RuleRecord status is active.
2. RuleRecord is included in active RuleSetRelease.
3. evidence_refs resolve.
4. referenced evidence is active.
5. review_status is approved.
6. tests pass.
```

## 39. Required Tests

Rule engine test categories:

```text
1. Rule loading tests.
2. Rule schema validation tests.
3. Evidence reference validation tests.
4. Candidate exclusion tests.
5. rsID normalization tests.
6. Genotype normalization tests.
7. Single-marker match tests.
8. Multi-marker match tests.
9. Unsupported marker tests.
10. Unmatched genotype tests.
11. Insufficient marker tests.
12. Safety route compatibility tests.
13. Conflict detection tests.
14. Determinism tests.
15. RuleSetRelease validation tests.
```

Critical tests:

```text
1. Active rule with valid evidence loads successfully.
2. Active rule without evidence_refs fails load.
3. Active rule with unresolved evidence_ref fails load.
4. Candidate rule is not loaded.
5. Unsupported rsID produces unsupported_marker.
6. Supported rsID with unmatched genotype produces unmatched_genotype.
7. Multi-marker rule with missing marker produces insufficient_markers.
8. Request asking for medical advice does not produce normal rule interpretation.
9. Same input and rule set produce same RuleEngineResult.
10. Conflicting active rules fail strict rule set validation.
```

## 40. Acceptance Criteria

The v0.1 rule engine is acceptable if:

```text
1. It loads only active RuleRecords from an approved RuleSetRelease.
2. It rejects candidate, inactive, deprecated, or invalid rules.
3. It validates that every active rule has resolvable active evidence_refs.
4. It performs deterministic rsID-genotype matching.
5. It supports single-marker rules.
6. It supports simple all-required multi-marker rules.
7. It returns structured match, unsupported, unmatched, insufficient, and invalid-input results.
8. It never uses LLMs for rule matching.
9. It never uses runtime retrieval for rule matching.
10. It never generates medical, nutrition, fitness, supplement, medication, diagnosis, or disease-risk outputs.
11. It preserves rule and evidence traceability.
12. It is covered by regression tests.
```