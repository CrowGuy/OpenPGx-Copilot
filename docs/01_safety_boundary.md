# 01 Safety Boundary

## 1. Purpose

This document defines the safety boundary for OpenPGx Copilot v0.1.

OpenPGx Copilot is a genetic interpretation and pharmacogenomics decision-support prototype. In v0.1, the system is limited to a wellness-first educational proof of concept using synthetic rsID-genotype inputs and curated low-risk genetic trait rules.

The purpose of this safety boundary is to ensure that v0.1 remains educational, evidence-bound, and non-clinical.

## 2. v0.1 Safety Classification

OpenPGx Copilot v0.1 is:

```text
An educational genetic trait interpretation prototype.
```

OpenPGx Copilot v0.1 is not:

```text
A diagnostic system
A prescribing system
A treatment recommendation system
A nutrition recommendation system
A fitness coaching system
A supplement recommendation system
A disease-risk prediction system
A replacement for licensed clinicians, pharmacists, dietitians, fitness professionals, or other qualified professionals
```

## 3. Core Safety Principle

v0.1 may explain curated genetic trait associations in educational language.

v0.1 must not convert genetic associations into personalized recommendations, clinical claims, medication guidance, disease-risk predictions, diagnosis, or treatment suggestions.

The system must maintain the following distinction:

```text
Allowed:
"This genotype is associated with a trait in the curated evidence."

Not allowed:
"You should change your medication, diet, exercise, supplement use, sleep, drinking behavior, or medical care because of this genotype."
```

## 4. Required Safety Message

Every user-facing v0.1 interpretation must include the following safety message:

```text
This explanation is for educational purposes only and should not be used as medical, nutrition, fitness, supplement, or medication advice.
```

For Chinese-language output, the message should be:

```text
本說明僅供教育用途，不應作為醫療、營養、運動訓練、補充劑或用藥建議。
```

The safety message must not be removed by the explanation layer or LLM.

## 5. Allowed v0.1 Behaviors

OpenPGx Copilot v0.1 may:

```text
1. Accept synthetic rsID-genotype inputs.
2. Validate supported rsID and genotype formats.
3. Match supported rsID-genotype patterns against curated wellness trait rules.
4. Identify that a genotype is associated with a supported educational genetic trait.
5. Display matched trait rules.
6. Display evidence references and source metadata.
7. Explain the genetic trait association in educational language.
8. State that genotype is only one factor among many.
9. State limitations of the interpretation.
10. Return unsupported-input warnings.
11. Refuse or downgrade requests when evidence is missing or insufficient.
12. Explain that the result is not medical, nutrition, fitness, supplement, or medication advice.
13. Generate candidate evidence/rule records for reviewer workflows, if clearly marked non-active.
```

## 6. Disallowed v0.1 Behaviors

OpenPGx Copilot v0.1 must not:

```text
1. Diagnose diseases.
2. Predict disease risk.
3. Prescribe medication.
4. Recommend starting medication.
5. Recommend stopping medication.
6. Recommend replacing medication.
7. Recommend changing medication dosage.
8. Recommend a diet plan.
9. Recommend supplements.
10. Recommend an exercise plan.
11. Recommend a sleep intervention.
12. Recommend a weight management plan.
13. Claim that genotype determines actual behavior, health status, or outcome.
14. Infer unsupported genotypes, traits, phenotypes, symptoms, diseases, or medical conditions.
15. Generate claims without evidence references.
16. Use LLM-generated text as source of rule logic.
17. Allow the LLM to upgrade or downgrade interpretation strength.
18. Invent evidence references, source versions, effect sizes, population claims, or clinical claims.
19. Process real patient data in v0.1.
20. Answer open-ended medical questions outside supported educational trait interpretation scope.
21. Activate uncertified or untrusted compiler output.
22. Use literature extraction as a direct active-rule creation mechanism.
23. Activate any rule or evidence record that lacks certified-compiler and trusted-source provenance.
24. Release an active bundle while any diff exception (DiffReport entry) remains unresolved by an ExceptionReview.
```

## 7. Advice Categories That Must Be Blocked

v0.1 must block or downgrade requests that ask for:

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

Examples of blocked requests include:

```text
Should I stop drinking because of rs671 AG?
Should I take supplements because of this genotype?
Should I avoid milk?
How many cups of coffee should I drink per day?
Does this mean I have cancer risk?
Should I change my medication?
Can I use this result to adjust my dose?
What disease do I have?
```

The system may respond with an educational downgrade when appropriate, but it must not answer the advice request directly.

## 8. Educational Downgrade Behavior

When a user asks for advice that is outside v0.1 scope, the system may downgrade the response to an educational explanation.

Example:

User asks:

```text
I have rs671 AG. Should I stop drinking alcohol?
```

Allowed response direction:

```text
OpenPGx Copilot v0.1 cannot provide drinking, medical, or health behavior advice.

For educational purposes only, the curated rule for rs671 AG is associated with reduced ALDH2 activity in some populations. Genotype is only one factor, and actual responses can depend on many non-genetic factors.

This explanation is for educational purposes only and should not be used as medical, nutrition, fitness, supplement, or medication advice.
```

Disallowed response direction:

```text
Yes, you should stop drinking.
```

## 9. Unsupported Input Behavior

If a user provides an unsupported marker, unsupported genotype, invalid genotype format, or marker without an active rule, the system must not infer an interpretation.

The system should return an unsupported-input response.

Example:

```text
The provided marker is not supported by the active v0.1 curated rule set. OpenPGx Copilot cannot generate an interpretation for this input.
```

The system must not use runtime literature retrieval or LLM reasoning to invent a result.

## 10. Evidence Safety Boundary

Every active user-facing interpretation must be backed by at least one valid evidence reference.

A rule must not be loaded as active if:

```text
1. evidence_refs is empty.
2. Any evidence_ref cannot be resolved.
3. The referenced evidence record is inactive.
4. The referenced evidence record does not allow educational explanation.
5. The referenced evidence record disallows the requested output type.
```

Evidence records must define allowed and disallowed uses.

Example:

```yaml
allowed_use:
  - educational_explanation

disallowed_use:
  - medical_advice
  - nutrition_advice
  - fitness_advice
  - supplement_advice
  - medication_advice
  - diagnosis
  - disease_risk_prediction
```

## 11. Rule Safety Boundary

Only curated active rules may produce user-facing interpretations.

Active rules must be:

```text
1. Backed by trusted-source provenance (TrustedSourceProfile) and certified-compiler provenance (CertifiedCompiler / CompilationRun), or hand-authored under the v0.1 bootstrap and held to the same validation and release approval.
2. Schema-valid.
3. Linked to valid evidence records.
4. Assigned an interpretation_level.
5. Assigned required safety messages.
6. Covered by passing safety validation (ValidationReport).
7. Included in an approved release manifest (RuntimeReleaseManifest with ReleaseApproval).
8. Covered by regression tests.
```

OpenPGx reviews the system, release diffs, and exceptions; it does not require per-rule manual review for every generated record. Per-record human review is required only for diff exceptions (DiffReport -> ExceptionReview), which must be resolved before release.

The system must not allow:

```text
1. LLM-generated active rules.
2. Runtime extraction of paper claims into active user-facing rules.
3. Rules without evidence references.
4. Rules that exceed the allowed use of their evidence.
5. Rules that imply advice, diagnosis, or disease-risk prediction in v0.1.
6. Candidate rules to be used as active rules.
```

## 12. Compiler Safety Boundary

The compiler framework may generate candidate records only.

Allowed compiler outputs include:

```text
SourceRecord
MarkerRecord
EvidenceCandidateRecord
RuleCandidateRecord
ReviewCard
DiffReport
```

Uncertified or untrusted compiler output can never be directly activated. Compiler outputs must not be used as active runtime interpretation logic unless they pass:

```text
1. Schema validation.
2. Trusted-source provenance (TrustedSourceProfile).
3. Certified-compiler provenance (CertifiedCompiler / CompilationRun).
4. Source reference validation.
5. Evidence reference validation.
6. Safety validation (ValidationReport).
7. Diff review with all exceptions resolved (DiffReport -> ExceptionReview).
8. Release approval (ReleaseApproval).
9. Regression testing.
10. Active rule set release pinned by an approved RuntimeReleaseManifest.
```

The compiler must not:

```text
1. Promote a candidate record into active status automatically.
2. Treat GWAS association as deterministic personal prediction.
3. Treat effect allele as sufficient to create genotype-level advice.
4. Infer lifestyle recommendations.
5. Generate active rules from LLM-extracted paper claims.
```

## 13. LLM Safety Boundary

The LLM is allowed only as an explanation layer.

The LLM may:

```text
1. Rewrite structured rule outputs into user-friendly educational text.
2. Summarize provided evidence snippets.
3. Explain limitations.
4. Explain unsupported inputs.
5. Produce language-specific explanations based only on supplied rule and evidence context.
6. Summarize candidate evidence for reviewer-facing workflows when clearly marked as non-active.
```

The LLM must not:

```text
1. Perform rule matching.
2. Create new active rules.
3. Infer unsupported traits from genotype data.
4. Create new evidence claims.
5. Invent citations.
6. Invent population-specific claims.
7. Invent effect sizes.
8. Provide medical advice.
9. Provide nutrition advice.
10. Provide fitness advice.
11. Provide supplement advice.
12. Provide medication advice.
13. Provide diagnosis.
14. Provide disease-risk prediction.
15. Remove required safety messages.
16. Convert educational association into personalized recommendation.
17. Approve candidate rules.
18. Decide evidence strength.
```

## 14. Output Safety Validation

Every user-facing output must pass safety validation before being returned.

The output safety validator should check for:

```text
1. Required safety message exists.
2. Evidence references are present for every interpretation.
3. No blocked advice category is present.
4. No disease-risk prediction is present.
5. No diagnosis is present.
6. No medication recommendation is present.
7. No nutrition, supplement, fitness, sleep, or weight management recommendation is present.
8. No unsupported trait claim is present.
9. No invented evidence reference is present.
10. Limitations are included.
11. Candidate-only records are not presented as active interpretation.
```

If the output fails validation, the system must not return the LLM output. v0.1 uses a fixed fallback order with no LLM retry:

```text
1. Use the deterministic safe template for the response mode.
2. If no interpretation should be produced, use the refusal template.
3. The returned output must itself pass validation.
```

The concrete error codes, allowed reference set, result schema, and fallback policy are defined in 07_llm_explanation_layer.md section 32.

## 15. Runtime Safety Routes

v0.1 should support the following safety routes:

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

The safety route may be assigned by the request adapter or future router, but OpenPGx Copilot must validate it before execution.

## 16. OpenPGx Copilot Must Not Blindly Trust a Router

Even if a future Gene Domain Intent Router provides a RoutingDecision, OpenPGx Copilot must perform its own domain-level validation.

OpenPGx Copilot must reject, downgrade, or mark unsupported if:

```text
1. target_system is not openpgx_copilot.
2. target_module is unsupported.
3. response_mode is unsupported.
4. safety_route is incompatible with the requested output.
5. Required structured entities are missing.
6. Markers are unsupported.
7. Genotype format is invalid.
8. The request asks for blocked output types.
9. No active rule matched.
10. Matched rules lack valid evidence references.
11. Evidence allowed_use does not support the requested response.
12. Matched record is candidate-only and not active.
```

## 17. v0.1 Data Safety Boundary

v0.1 must use synthetic inputs only.

v0.1 must not process:

```text
1. Real patient records.
2. Protected health information.
3. Clinical medication histories.
4. Diagnostic records.
5. Identifiable medical data.
```

v0.1 must enforce this boundary by system behavior, not by user discipline:

```text
1. input_type is required and must equal `synthetic`; other values are rejected.
2. user_id, if provided, must match a synthetic identifier pattern; other values are rejected.
3. Free-text fields (query, user_id) must never be persisted to durable storage.
4. Free-text fields must be redacted from logs and audit records.
5. Free-text fields must be used only for routing, never as domain interpretation input to the rule engine or LLM.
```

The realness of an rsID-genotype value cannot be determined from its content, so v0.1 does not attempt to detect real data by inspecting genotype content. The boundary is maintained by the rules above (declared input type, data minimization, and non-retention), which are enforced and testable, rather than by content inspection or by relying on the user to withhold real data.

## 18. Trait-Specific Safety Notes

| Trait | Allowed | Disallowed |
| --- | --- | --- |
| ALDH2 - Alcohol Metabolism | Educational explanation of curated rs671 association with ALDH2 activity. | Alcohol consumption advice; Disease-risk prediction; Cancer-risk interpretation; Medical advice |
| LCT / MCM6 - Lactose Tolerance | Educational explanation of curated lactase persistence or lactose tolerance association. | Diet plan; Nutrition advice; Diagnosis of lactose intolerance |
| CYP1A2 - Caffeine Metabolism | Educational explanation of curated caffeine metabolism association. | Daily coffee recommendation; Pregnancy advice; Medication interaction advice; Medical advice |
| ABCC11 - Earwax Type | Educational explanation of curated earwax type association. | Health status inference; Medical interpretation |
| TAS2R38 - Bitter Taste Perception | Educational explanation of curated bitter taste perception association. | Diet recommendation; Nutrition advice; Behavior prediction |

## 19. Safety Acceptance Criteria

v0.1 satisfies the safety boundary if:

```text
1. Every user-facing interpretation includes the required safety message.
2. Every interpretation has at least one valid evidence reference.
3. Unsupported inputs do not produce invented interpretations.
4. Unsafe advice requests are refused or downgraded.
5. LLM output does not contain blocked advice categories.
6. No disease-risk prediction is produced.
7. No diagnosis is produced.
8. No medication recommendation is produced.
9. No nutrition, supplement, fitness, sleep, or weight management recommendation is produced.
10. Rules without valid evidence references cannot be loaded as active rules.
11. Output safety validation is part of the runtime path.
12. The system remains educational-only in v0.1.
13. Compiler-generated records enter an active release only with certified-compiler and trusted-source provenance, passing validation, and an approved release manifest; uncertified or untrusted compiler output is never activated.
14. No active release is cut while any diff exception remains unresolved.
```
