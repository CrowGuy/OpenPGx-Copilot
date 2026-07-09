# 07 LLM Explanation Layer

## 1. Purpose

This document defines the role, boundaries, inputs, outputs, and safety constraints of the LLM Explanation Layer in OpenPGx Copilot v0.1.

OpenPGx Copilot v0.1 is a wellness-first educational proof of concept with PGx-ready architecture.

The LLM Explanation Layer exists to convert structured, validated rule/evidence outputs into clear, user-friendly, limitation-aware educational explanations.

The LLM Explanation Layer is not a decision engine.

The LLM Explanation Layer must not decide genetic interpretations, create rules, create evidence, assign evidence strength, or provide medical, nutrition, fitness, supplement, medication, diagnosis, or disease-risk advice.

## 2. Core Principle

The core principle is:

```text
Rule engine decides.
Evidence records bound the explanation.
LLM communicates.
Safety validator verifies.
```

The LLM may explain only what has already been determined by:

```text
1. Validated request.
2. Active RuleRecord.
3. Active EvidenceRecord.
4. SourceRecord metadata.
5. SafetyRoute.
6. Required safety template.
```

The LLM must not add new domain claims.

## 3. Runtime Position

The LLM Explanation Layer sits after rule matching and evidence lookup, and before output safety validation.

Runtime path:

```text
RawUserRequest
→ RequestAdapter / Router
→ RoutingDecision
→ RequestValidator
→ RuleEngine
→ EvidenceStore
→ LLM Explanation Layer
→ OutputSafetyValidator
→ UserFacingResponse
```

The LLM receives bounded structured context.

The LLM produces draft explanation content.

The OutputSafetyValidator must validate the LLM output before it is returned to the user.

## 4. What the LLM Is Allowed To Do

The LLM may:

```text
1. Rewrite structured rule engine outputs into user-friendly educational language.
2. Summarize provided EvidenceRecord summaries.
3. Explain provided limitations.
4. Explain why unsupported inputs cannot be interpreted.
5. Explain why advice requests are refused or downgraded.
6. Produce bilingual or localized explanations if requested.
7. Format explanations for readability.
8. Generate reviewer-facing summaries of candidate evidence, if clearly marked as non-active.
9. Help create draft documentation, review cards, or internal notes from provided structured records.
```

The LLM may only use information provided in the bounded context.

The LLM may not rely on memory, general biomedical knowledge, runtime search, or inferred claims to expand the explanation.

## 5. What the LLM Is Not Allowed To Do

The LLM must not:

```text
1. Perform rule matching.
2. Decide whether a genotype matches a rule.
3. Create active RuleRecords.
4. Create active EvidenceRecords.
5. Promote candidate records into active records.
6. Infer unsupported traits from genotype data.
7. Infer phenotype from genotype in v0.1.
8. Infer disease risk.
9. Diagnose disease.
10. Provide medical advice.
11. Provide nutrition advice.
12. Provide fitness advice.
13. Provide supplement advice.
14. Provide medication advice.
15. Recommend starting, stopping, replacing, or changing medication dosage.
16. Recommend diet plans.
17. Recommend exercise plans.
18. Recommend sleep interventions.
19. Recommend supplements.
20. Recommend weight management plans.
21. Invent citations, source IDs, PMIDs, DOIs, URLs, population claims, or effect sizes.
22. Assign or modify evidence strength.
23. Upgrade association into recommendation.
24. Remove required safety messages.
25. Suppress limitations.
26. Override the safety route.
27. Override the rule engine result.
28. Use runtime top-k literature retrieval to expand user-facing explanations.
```

## 6. LLM Boundary Statement

The LLM Explanation Layer must follow this boundary:

```text
The LLM may transform approved structured content into safer, clearer language.

The LLM may not create, modify, or decide domain content.
```

Allowed transformation:

```text
Structured result:
"rs671 AG matched aldh2_rs671_alcohol_metabolism."

LLM output:
"Your provided rs671 AG genotype matches a curated educational rule related to ALDH2 and alcohol metabolism."
```

Disallowed transformation:

```text
Structured result:
"rs671 AG matched aldh2_rs671_alcohol_metabolism."

LLM output:
"You should avoid alcohol because this genotype increases your cancer risk."
```

The second output is disallowed because it adds advice and disease-risk interpretation not permitted in v0.1.

## 7. Input Contract

The LLM Explanation Layer must receive a structured `ExplanationContext`.

Example:

```json
{
  "request_id": "req-001",
  "language": "en",
  "response_mode": "educational_explanation",
  "safety_route": "allowed",
  "rule_engine_result": {
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
    ]
  },
  "evidence_records": [
    {
      "id": "evidence_aldh2_rs671_001",
      "status": "active",
      "summary": "ALDH2 rs671 is associated with reduced ALDH2 enzyme activity and altered acetaldehyde metabolism.",
      "population_note": "Association is especially relevant in East Asian populations.",
      "limitations": [
        "Genotype is only one factor.",
        "Actual response may be affected by health status, environment, lifestyle, and other genetic factors."
      ],
      "allowed_use": [
        "educational_explanation"
      ],
      "disallowed_use": [
        "medical_advice",
        "nutrition_advice",
        "fitness_advice",
        "supplement_advice",
        "medication_advice",
        "diagnosis",
        "disease_risk_prediction"
      ],
      "source_refs": [
        "source_aldh2_rs671_paper_001"
      ]
    }
  ],
  "required_safety_message": "This explanation is for educational purposes only and should not be used as medical, nutrition, fitness, supplement, or medication advice.",
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

The LLM must not be called with raw source documents alone for user-facing interpretation.

The LLM must not be called with candidate-only records for runtime explanation.

## 8. Input Requirements

The LLM Explanation Layer input must include:

```text
1. request_id.
2. response_mode.
3. safety_route.
4. RuleEngineResult.
5. Resolved active EvidenceRecords.
6. Evidence limitations.
7. Required safety message.
8. Blocked output categories.
```

The input should include:

```text
1. SourceRecord metadata.
2. Language preference.
3. User query if needed for tone or response mode.
4. Unsupported input details if no rule matched.
```

The input must not include:

```text
1. Candidate RuleRecords for runtime explanation.
2. Candidate EvidenceRecords for runtime explanation.
3. Raw papers as direct interpretation sources.
4. Unreviewed LLM-generated evidence summaries.
5. Real patient records in v0.1.
```

## 9. Output Contract

The LLM Explanation Layer should return an `ExplanationDraft`.

Example:

```json
{
  "request_id": "req-001",
  "status": "draft_generated",
  "language": "en",
  "response_mode": "educational_explanation",
  "sections": {
    "summary": "Your provided rs671 AG genotype matches a curated educational rule related to ALDH2 and alcohol metabolism.",
    "interpretation": "The linked evidence describes an association between ALDH2 rs671 and reduced ALDH2 enzyme activity, which can affect acetaldehyde metabolism.",
    "limitations": "Genotype is only one factor. Actual response may also depend on health status, environment, lifestyle, ancestry, and other genetic factors.",
    "safety_message": "This explanation is for educational purposes only and should not be used as medical, nutrition, fitness, supplement, or medication advice.",
    "evidence": "Evidence reference: evidence_aldh2_rs671_001."
  },
  "used_rule_refs": [
    "aldh2_rs671_alcohol_metabolism"
  ],
  "used_evidence_refs": [
    "evidence_aldh2_rs671_001"
  ],
  "contains_candidate_records": false
}
```

The output must be treated as a draft until it passes OutputSafetyValidator.

## 10. Required Output Elements

Every successful educational explanation must include:

```text
1. Matched trait or unsupported-input status.
2. Matched marker or markers.
3. Educational interpretation summary.
4. Evidence reference IDs.
5. Limitations.
6. Required safety message.
```

For unsupported inputs, output must include:

```text
1. Unsupported marker or genotype.
2. Explanation that no active v0.1 rule matched.
3. Statement that the system cannot infer an interpretation.
4. Required safety message if the response discusses genetic interpretation boundaries.
```

For refused or downgraded advice requests, output must include:

```text
1. Clear refusal or downgrade statement.
2. Safe educational explanation if an active rule matched and downgrade is allowed.
3. Limitations.
4. Required safety message.
```

## 11. Required Safety Message

The following message must appear in every user-facing v0.1 interpretation:

```text
This explanation is for educational purposes only and should not be used as medical, nutrition, fitness, supplement, or medication advice.
```

Chinese version:

```text
本說明僅供教育用途，不應作為醫療、營養、運動訓練、補充劑或用藥建議。
```

The LLM must not remove, paraphrase away, weaken, or hide this message.

If the output language is Chinese, the Chinese version should be used.

If the output is bilingual, both versions may be included.

## 12. Response Modes

v0.1 supports these response modes:

```text
educational_explanation
evidence_explanation
limitation_explanation
unsupported_input_explanation
safe_refusal
downgraded_educational_explanation
```

### 12.1 educational_explanation

Used when the request is allowed and a rule matched.

The LLM may explain:

```text
1. The matched marker.
2. The matched trait.
3. The curated association.
4. The limitations.
5. Evidence references.
```

The LLM must not provide advice.

### 12.2 evidence_explanation

Used when the user asks about evidence behind a matched result.

The LLM may summarize:

```text
1. EvidenceRecord summary.
2. Source metadata.
3. Limitations.
4. Allowed use.
5. Disallowed use.
```

The LLM must not search for new papers or add uncited claims.

### 12.3 limitation_explanation

Used when the user asks what the result cannot tell them.

The LLM may explain:

```text
1. Genotype is one factor.
2. Association is not deterministic.
3. The system does not provide advice.
4. Environmental and other biological factors matter.
```

### 12.4 unsupported_input_explanation

Used when no active rule supports the input.

The LLM must say:

```text
1. The input is unsupported by the active v0.1 rule set.
2. No interpretation can be generated.
3. The system will not infer a result.
```

### 12.5 safe_refusal

Used when the request is outside the safety boundary.

The LLM must refuse clearly and briefly.

Example:

```text
OpenPGx Copilot v0.1 cannot provide disease-risk prediction or medical advice.
```

### 12.6 downgraded_educational_explanation

Used when a user asks for advice, but a safe educational explanation can still be provided from an active rule.

Example:

```text
I cannot tell you whether you should change your behavior based on this genotype. For educational purposes only, the matched rule describes an association between the provided genotype and a genetic trait.
```

## 13. Safety Route Behavior

The LLM must follow the validated `safety_route`.

### allowed

The LLM may generate a normal educational explanation from active rule and evidence context.

### downgrade_to_educational

The LLM must not answer the advice part of the request.

It may provide an educational explanation if an active rule matched.

### refuse_personalized_advice

The LLM must refuse the personalized advice request.

It may provide general educational context only if allowed by evidence and safety validator.

### refuse_medical_advice

The LLM must not provide medical advice.

### refuse_nutrition_advice

The LLM must not provide diet plans, food recommendations, or nutrition guidance.

### refuse_fitness_advice

The LLM must not provide exercise or training guidance.

### refuse_supplement_advice

The LLM must not recommend supplements.

### refuse_medication_advice

The LLM must not provide drug, dosage, medication-change, or medication-selection advice.

### refuse_disease_risk

The LLM must not predict or discuss individual disease risk.

### unsupported_input

The LLM must not infer interpretation.

### out_of_scope

The LLM must state that the request is outside v0.1 scope.

### needs_clarification

The LLM may ask for missing non-sensitive structured information, but v0.1 should prefer deterministic unsupported or invalid-input responses where possible.

## 14. Prompt Construction Requirements

LLM prompts must be constructed from bounded context.

A prompt should include:

```text
1. System role boundary.
2. Response mode.
3. Safety route.
4. RuleEngineResult.
5. EvidenceRecord summaries.
6. Limitations.
7. Required safety message.
8. Blocked output categories.
9. Explicit instruction not to add claims.
```

A prompt must not include:

```text
1. Instructions to infer missing genetic meaning.
2. Instructions to search memory.
3. Instructions to use general biomedical knowledge.
4. Candidate records for active explanation.
5. Raw papers as direct evidence for user-facing interpretation.
```

## 15. Prompt Template: Matched Educational Explanation

Template:

```text
You are the explanation layer for OpenPGx Copilot v0.1.

You must only use the provided rule result and evidence records.
Do not add medical, nutrition, fitness, supplement, medication, diagnosis, or disease-risk advice.
Do not add claims not present in the provided evidence.
Do not infer unsupported traits.
Do not invent citations, PMIDs, DOIs, source IDs, population claims, or effect sizes.
Include the required safety message exactly.

Response mode: educational_explanation
Safety route: {safety_route}

Matched rule:
{rule_engine_result}

Evidence records:
{evidence_records}

Required safety message:
{required_safety_message}

Write a clear educational explanation with:
1. What matched.
2. What the evidence says.
3. Limitations.
4. Evidence reference IDs.
5. Required safety message.
```

## 16. Prompt Template: Unsupported Input

Template:

```text
You are the explanation layer for OpenPGx Copilot v0.1.

The rule engine did not find an active supported rule for the provided input.
Do not infer an interpretation.
Do not search for additional evidence.
Do not provide medical, nutrition, fitness, supplement, medication, diagnosis, or disease-risk advice.
Include the required safety message if discussing genetic interpretation boundaries.

Rule engine result:
{rule_engine_result}

Required safety message:
{required_safety_message}

Write a brief unsupported-input explanation.
```

## 17. Prompt Template: Downgraded Advice Request

Template:

```text
You are the explanation layer for OpenPGx Copilot v0.1.

The user asked for advice that is outside v0.1 scope.
You must not answer the advice request.
You may provide only an educational explanation based on the matched active rule and active evidence records.
Do not recommend actions.
Do not provide medical, nutrition, fitness, supplement, medication, diagnosis, or disease-risk advice.
Include the required safety message exactly.

Safety route:
{安全_route}

Blocked outputs:
{blocked_outputs}

Matched rule:
{rule_engine_result}

Evidence records:
{evidence_records}

Required safety message:
{required_safety_message}

Write:
1. A short boundary statement.
2. A safe educational explanation.
3. Limitations.
4. Evidence reference IDs.
5. Required safety message.
```

## 18. Prompt Template: Evidence Explanation

Template:

```text
You are the explanation layer for OpenPGx Copilot v0.1.

The user asked about evidence behind an interpretation.
Use only the provided EvidenceRecords and SourceRecord metadata.
Do not search for other papers.
Do not add claims beyond provided evidence.
Do not infer medical, nutrition, fitness, supplement, medication, diagnosis, or disease-risk conclusions.
Include the required safety message.

Evidence records:
{evidence_records}

Source records:
{source_records}

Required safety message:
{required_safety_message}

Write:
1. Evidence summary.
2. Source references by ID.
3. Limitations.
4. What the evidence does not support.
5. Required safety message.
```

## 19. Banned Output Patterns

The OutputSafetyValidator should reject LLM output containing unsafe phrases or equivalent meanings.

Examples of banned patterns:

```text
You should...
You need to...
You must stop...
You can safely...
You are at risk for...
You have a higher risk of disease...
You should take...
You should avoid...
Ask your doctor to change your medication...
Change your dose...
This means you are lactose intolerant...
This means you will dislike...
This means you should drink...
This means you should not drink...
```

Some phrases may be acceptable only in refusal form.

Allowed refusal example:

```text
I cannot tell you whether you should change your medication.
```

Disallowed advice example:

```text
You should change your medication.
```

## 20. Allowed Output Patterns

Safe patterns include:

```text
The provided genotype matches a curated educational rule.
The linked evidence describes an association with...
This is not a deterministic prediction.
Genotype is only one factor.
Actual response may depend on other genetic, environmental, lifestyle, or health-related factors.
OpenPGx Copilot v0.1 cannot provide medical advice.
No active v0.1 rule supports this marker.
The system cannot generate an interpretation for this unsupported input.
Evidence reference: ...
```

## 21. Trait-Specific LLM Boundaries

| Trait | Allowed | Disallowed |
| --- | --- | --- |
| **ALDH2 - Alcohol Metabolism** | Educational explanation of ALDH2 rs671 association with ALDH2 activity or acetaldehyde metabolism. | Alcohol consumption advice. Disease-risk prediction. Cancer-risk interpretation. Statements such as “you should stop drinking” or “you can safely drink.” |
| **LCT / MCM6 - Lactose Tolerance** | Educational explanation of lactase persistence or lactose tolerance association. | Diet advice. Diagnosis of lactose intolerance. Statements such as “you should avoid milk.” |
| **CYP1A2 - Caffeine Metabolism** | Educational explanation of caffeine metabolism association. | Daily coffee amount recommendation. Pregnancy advice. Medication interaction advice. Statements such as “you should drink fewer cups.” |
| **ABCC11 - Earwax Type** | Educational explanation of earwax type association. | Health status inference. Medical interpretation. |
| **TAS2R38 - Bitter Taste Perception** | Educational explanation of bitter taste perception association. | Diet recommendation. Behavior prediction. Statements such as “you will dislike broccoli.” |

## 22. Candidate Evidence Explanation Boundary

The LLM may summarize candidate evidence only in reviewer-facing workflows.

Candidate evidence summaries must be labeled clearly:

```text
Candidate only.
Not approved for runtime interpretation.
Requires human review.
Not for user-facing explanation.
```

The LLM must not present candidate evidence as established user-facing interpretation.

Reviewer-facing allowed example:

```text
This candidate record suggests a possible marker-trait association from a structured source, but the trait mapping, genotype pattern, effect direction, and safety boundary require human review before activation.
```

User-facing disallowed example:

```text
Your genotype means this trait applies to you.
```

## 23. LLM and Retrieval Boundary

The LLM Explanation Layer must not perform retrieval for runtime interpretation.

Disallowed runtime path:

```text
user query
→ retrieve top-k papers
→ LLM summarizes papers
→ final user-facing interpretation
```

Allowed reviewer path:

```text
candidate evidence search
→ reviewer workflow
→ candidate summary
→ human review
→ active EvidenceRecord
→ active RuleRecord
```

Allowed runtime path:

```text
matched active RuleRecord
→ bound active EvidenceRecord
→ LLM explanation
→ safety validation
```

## 24. LLM and Source Citation Boundary

The LLM may refer only to source references provided in context.

Allowed:

```text
Evidence reference: evidence_aldh2_rs671_001.
Source reference: source_aldh2_rs671_paper_001.
```

Disallowed:

```text
Inventing a PMID.
Inventing a DOI.
Inventing a source title.
Inventing a study population.
Inventing an effect size.
Inventing a guideline name.
```

If source metadata is missing, the LLM must say that detailed source metadata is not available in the provided context.

## 25. LLM and Evidence Strength Boundary

The LLM must not assign evidence strength.

Disallowed:

```text
This is strong evidence.
This is clinically proven.
This is definitive.
This guarantees...
```

Allowed if explicitly present in the EvidenceRecord:

```text
The evidence record is categorized as a curated educational association.
```

The LLM may only repeat evidence strength labels that are explicitly provided by active EvidenceRecords.

## 26. LLM and Population Claims Boundary

The LLM must not invent population-specific claims.

Allowed if provided:

```text
The evidence record notes that this association is especially relevant in East Asian populations.
```

Disallowed:

```text
This applies to all East Asian people.
This means East Asian users will have this trait.
This is rare/common in your ancestry.
```

Population notes must be framed as evidence context, not individual prediction.

## 27. LLM and Genotype Claims Boundary

The LLM must not infer genotype meaning outside matched rules.

Allowed:

```text
The provided genotype matched the active rule aldh2_rs671_alcohol_metabolism.
```

Disallowed:

```text
Because you have AG, you definitely have reduced enzyme function.
```

The LLM must preserve association language.

Preferred language:

```text
is associated with
has been linked to
the curated evidence describes an association
```

Avoid deterministic language:

```text
causes
proves
guarantees
means you will
determines
```

## 28. LLM and Advice Boundary

The LLM must not provide advice.

Disallowed advice categories:

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

The LLM may recommend consulting a qualified professional only in a generic safety context, without implying a specific action.

Allowed:

```text
For personal medical or medication questions, consult a licensed clinician or pharmacist.
```

Disallowed:

```text
Ask your doctor to change your medication.
Ask your doctor to prescribe a different drug.
Ask your dietitian to remove dairy.
```

## 29. LLM and Unsupported Inputs

If no active rule matched, the LLM must not infer.

Required unsupported explanation:

```text
The provided marker or genotype is not supported by the active v0.1 curated rule set. OpenPGx Copilot cannot generate an interpretation for this input.
```

The LLM must not say:

```text
Based on general knowledge...
This marker is probably related to...
I found that this SNP may...
```

Unsupported means unsupported.

## 30. LLM and Unmatched Genotypes

If a marker is supported but the genotype does not match an active rule, the LLM must not infer a negative or normal result.

Allowed:

```text
This marker is recognized by the active v0.1 rule set, but the provided genotype does not match an active interpretation rule. No interpretation was generated.
```

Disallowed:

```text
This means you have normal metabolism.
This means you do not have the trait.
```

Unless an explicit active rule exists for that genotype, the LLM must not infer it.

## 30a. LLM and Invalid, Conflicted, or Duplicate Inputs

For inputs the rule engine marked `invalid_input`, `conflicted_input`, or `duplicate_ignored`, the LLM must state the status plainly and must not turn them into an interpretation.

Allowed:

```text
One or more inputs were invalid and were not interpreted.
An rsID was provided with conflicting genotypes and was excluded from interpretation.
A duplicate input was ignored.
```

Disallowed:

```text
Inferring a trait for an invalid or conflicted input.
Guessing which conflicting genotype was intended.
Interpreting a duplicate as an additional finding.
```

`invalid_input`, `conflicted_input`, and `duplicate_ignored` are terminal: the LLM must never fill them in.

## 30b. LLM and the User Query

The user query informs only tone, response mode, and language. The LLM must not treat it as domain input.

Disallowed:

```text
Extracting markers, genotypes, or traits from the query.
Answering the query as an open medical or genetics question.
Preferring a genotype mentioned in the query over the structured genotypes[].
```

Allowed:

```text
Adjusting wording, language, and response mode to fit the query.
Following the assigned safety route when the query requests a blocked output.
```

Structured `genotypes[]` is the sole domain authority. If the query is ambiguous or its intent is unclear, the LLM must follow the fail-safe route (downgrade or refuse), never invent an interpretation.

## 31. LLM and Multi-Marker Results

For multi-marker rules, the LLM must reflect the rule engine result exactly.

If all required markers matched:

```text
The provided marker combination matched an active educational rule.
```

If markers were missing:

```text
The active rule requires additional markers, so no interpretation was generated.
```

The LLM must not provide partial interpretation unless the rule engine returned an explicit active partial rule.

## 32. Output Safety Validator Integration

The LLM output must be validated before user-facing return.

The OutputSafetyValidator should check:

```text
1. Required safety message exists.
2. Evidence reference IDs are present.
3. No medical advice.
4. No nutrition advice.
5. No fitness advice.
6. No supplement advice.
7. No medication advice.
8. No diagnosis.
9. No disease-risk prediction.
10. No deterministic overclaim.
11. No invented source references.
12. No candidate records used as active evidence.
13. Limitations are present.
14. Safety route is respected.
```

If validation fails, the system must:

```text
1. Regenerate with stricter prompt.
2. Downgrade to a safe deterministic template.
3. Refuse the request.
```

## 33. Deterministic Fallback Templates

The system should provide fallback templates that do not rely on LLM generation.

### 33.1 Matched Educational Fallback

```text
The provided genotype matched an active curated educational rule: {rule_id}.

The linked evidence describes an association with {trait}. Genotype is only one factor, and actual outcomes may depend on other genetic, environmental, lifestyle, and health-related factors.

Evidence reference: {evidence_refs}.

{required_safety_message}
```

### 33.2 Unsupported Input Fallback

```text
The provided marker or genotype is not supported by the active v0.1 curated rule set. OpenPGx Copilot cannot generate an interpretation for this input.

{required_safety_message}
```

### 33.3 Refusal Fallback

```text
OpenPGx Copilot v0.1 cannot provide medical, nutrition, fitness, supplement, medication, diagnosis, or disease-risk advice.

{required_safety_message}
```

### 33.4 Downgraded Educational Fallback

```text
OpenPGx Copilot v0.1 cannot answer the advice portion of this request.

For educational purposes only, the provided genotype matched an active curated rule: {rule_id}. The linked evidence describes an association with {trait}. Genotype is only one factor, and this result should not be used to make medical, nutrition, fitness, supplement, or medication decisions.

Evidence reference: {evidence_refs}.

{required_safety_message}
```

## 34. ExplanationRecord

The LLM output should be stored as an `ExplanationRecord`.

Example:

```yaml
id: explanation_req_001
request_id: req-001
language: en
response_mode: educational_explanation
safety_route: allowed
source_result_refs:
  - aldh2_rs671_alcohol_metabolism
evidence_refs:
  - evidence_aldh2_rs671_001
body: >
  The provided rs671 AG genotype matched an active curated educational rule
  related to ALDH2 and alcohol metabolism. The linked evidence describes an
  association between ALDH2 rs671 and reduced ALDH2 enzyme activity.
limitations:
  - "Genotype is only one factor."
  - "Actual response may be affected by health status, environment, lifestyle, and other genetic factors."
safety_message: >
  This explanation is for educational purposes only and should not be used as
  medical, nutrition, fitness, supplement, or medication advice.
validation_status: passed
generation:
  method: llm_assisted
  model: "..."
  prompt_template_id: matched_educational_v0_1
  generated_at: "2026-07-07"
```

The ExplanationRecord must include:

```text
1. request_id.
2. response_mode.
3. safety_route.
4. source rule refs.
5. evidence refs.
6. body.
7. limitations.
8. safety message.
9. validation status.
10. generation metadata.
```

## 35. Logging and Audit Requirements

The system should log:

```text
1. request_id.
2. response_mode.
3. safety_route.
4. rule IDs provided to LLM.
5. evidence IDs provided to LLM.
6. prompt template ID.
7. output validation result.
8. fallback usage if any.
```

The system should not log real patient data in v0.1.

Since v0.1 uses synthetic inputs only, logging should still avoid unnecessary sensitive information.

## 36. Testing Requirements

The LLM Explanation Layer must be tested using deterministic fixtures.

Required test categories:

```text
1. Matched educational explanation.
2. Evidence explanation.
3. Limitation explanation.
4. Unsupported input explanation.
5. Downgraded advice request.
6. Refusal for medical advice.
7. Refusal for nutrition advice.
8. Refusal for fitness advice.
9. Refusal for supplement advice.
10. Refusal for medication advice.
11. Refusal for disease-risk request.
12. Candidate evidence not used as active evidence.
13. Missing safety message detection.
14. Invented citation detection.
15. Deterministic overclaim detection.
16. Advice phrase detection.
17. Multi-marker insufficient input explanation.
18. Unmatched genotype explanation.
```

Critical tests:

```text
1. LLM output missing required safety message fails validation.
2. LLM output containing "you should stop drinking" fails validation.
3. LLM output containing disease-risk prediction fails validation.
4. LLM output inventing PMID or DOI fails validation.
5. LLM output using candidate evidence as active evidence fails validation.
6. LLM output changing result_code fails validation.
7. LLM output changing evidence_refs fails validation.
8. Unsupported input does not produce interpretation.
9. Unmatched genotype does not produce normal/negative interpretation.
10. Downgraded advice request does not answer the advice request.
```

## 37. Acceptance Criteria

The LLM Explanation Layer is acceptable for v0.1 if:

```text
1. It receives only bounded structured context.
2. It never performs rule matching.
3. It never creates or modifies active rules.
4. It never creates or modifies active evidence.
5. It never assigns evidence strength.
6. It never invents citations or source metadata.
7. It never provides medical, nutrition, fitness, supplement, medication, diagnosis, disease-risk, or treatment advice.
8. It preserves rule IDs and evidence IDs.
9. It includes required limitations.
10. It includes the required safety message.
11. It respects the safety route.
12. It passes OutputSafetyValidator before user-facing return.
13. It supports deterministic fallback templates.
14. It can explain unsupported inputs without inference.
15. It can support reviewer-facing candidate summaries without activating candidates.
```

## 38. Future PGx Extension

Future PGx modules may use the LLM Explanation Layer to explain PGx alerts, but the same boundary applies.

Future LLM may explain:

```text
1. Matched gene-drug rule.
2. Matched phenotype.
3. Guideline source metadata.
4. Recommendation strength if provided by curated PGx source.
5. Limitations and clinician-review requirements.
```

Future LLM must not:

```text
1. Decide medication changes.
2. Prescribe.
3. Change dosage.
4. Infer phenotype not provided by PGx rule engine.
5. Override CPIC / ClinPGx / PharmGKB / PharmCAT-derived records.
6. Invent PGx guideline claims.
7. Convert guideline explanation into autonomous patient instruction.
```

Future PGx output should likely include stronger clinician-facing disclaimers and workflow constraints.
