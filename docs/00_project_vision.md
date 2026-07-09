# 00 Project Vision

## 1. Project Name

```text
OpenPGx Copilot
```

## 2. Project Positioning

OpenPGx Copilot is a public-data-driven genetic interpretation and pharmacogenomics decision-support prototype.

The long-term direction of the project is pharmacogenomics decision support, especially helping bridge the gap between genetic test results and safe, evidence-linked, context-aware interpretation.

However, version 0.1 does not implement medication alerts or pharmacogenomics treatment recommendations. Instead, v0.1 starts with a wellness-first proof of concept using low-risk genetic trait examples.

The purpose of v0.1 is to validate the core architecture before expanding toward pharmacogenomics medication alert workflows.

## 3. Long-Term Problem Statement

OpenPGx Copilot does not aim to solve sequencing speed, read mapping speed, variant calling speed, or bioinformatics compute bottlenecks.

The core long-term problem is the report-to-action gap.

After genetic or pharmacogenomics-related information has been produced, the result often remains inside a static report, PDF, table, or isolated data system. It may not be converted into a safe, explainable, auditable, and timely interpretation that can support downstream human decision-making.

In a future pharmacogenomics setting, the system may help connect:

```text
genotype / haplotype / diplotype / phenotype
+ medication context
→ gene-drug alert
→ evidence trace
→ clinician / patient explanation
→ questions to ask a licensed physician or pharmacist
```

Version 0.1 does not implement this full pharmacogenomics path. It establishes the foundation.

## 4. v0.1 Strategy

The v0.1 strategy is:

```text
Wellness-first POC,
PGx-ready architecture.
```

This means v0.1 uses low-risk wellness genetic traits to validate the core architecture:

```text
synthetic rsID-genotype input
→ marker-level curated rule matching
→ rule-bound evidence lookup
→ educational trait interpretation
→ limitation-aware explanation
→ safety validation
```

The v0.1 wellness-first scope is not the final product direction. It is a low-risk sandbox for testing the architecture.

The long-term repo direction remains pharmacogenomics decision support.

## 5. Why v0.1 Starts with Wellness Traits

The project begins with wellness traits because the initial project constraints make full pharmacogenomics medication alert support too risky for v0.1.

Current constraints include:

```text
- Public data sources only
- No dedicated clinical domain expert
- Only limited sponsor-level domain guidance
- Need to avoid early medical or medication advice risk
- Need to validate architecture before handling higher-risk clinical workflows
```

Wellness-first v0.1 allows the system to test:

```text
- Rule loading
- Rule validation
- Evidence linking
- Evidence traceability
- Explanation generation
- Safety boundaries
- Unsupported input handling
- Regression testing
- Candidate evidence/rule compiler framework
```

without claiming to provide medical, nutritional, fitness, supplement, diagnostic, or medication guidance.

## 6. v0.1 Product Definition

OpenPGx Copilot v0.1 is an educational genetic trait interpretation prototype.

It accepts synthetic rsID-genotype inputs and produces safe, evidence-linked, educational explanations for a small curated set of wellness traits.

v0.1 supports manually curated active rules and evidence records.

v0.1 may also include an ingestion/compiler prototype that generates candidate evidence records and candidate rule records from public structured or semi-structured sources, but compiler-generated records must not become active without review and validation.

v0.1 does not process real patient data.

v0.1 does not provide personalized health recommendations.

v0.1 does not make clinical claims.

## 7. v0.1 Supported Trait Direction

The initial v0.1 trait examples are selected for relatively low risk, clear explanation boundaries, and usefulness for validating the architecture.

Supported v0.1 trait candidates include:

```text
1. ALDH2 - alcohol metabolism
2. LCT / MCM6 - lactose tolerance
3. CYP1A2 - caffeine metabolism
4. ABCC11 - earwax type
5. TAS2R38 - bitter taste perception
```

These traits are used to test rule and evidence modeling, not to provide lifestyle recommendations.

## 8. Explicitly Deferred Trait Areas

The following trait areas are deferred from v0.1:

```text
1. ACTN3 - exercise trait association
2. FTO - weight management association
3. VDR - vitamin D metabolism association
4. PER3 / CLOCK - sleep pattern association
```

These areas are deferred because they are more likely to be overinterpreted as personalized exercise, nutrition, supplement, weight management, or sleep advice.

## 9. What v0.1 Does

v0.1 does:

```text
1. Accept synthetic rsID-genotype inputs.
2. Validate supported marker and genotype formats.
3. Match supported inputs against a curated rule set.
4. Resolve rule-bound evidence references.
5. Produce structured educational trait interpretation results.
6. Generate user-facing educational explanations from rule and evidence outputs.
7. Include limitations and required safety messages.
8. Reject or downgrade unsupported, unsafe, or insufficiently evidenced requests.
9. Establish reusable architecture for future pharmacogenomics modules.
10. Optionally generate candidate evidence/rule records from structured public sources for review.
```

## 10. What v0.1 Does Not Do

v0.1 does not:

```text
1. Diagnose diseases.
2. Predict disease risk.
3. Provide medical advice.
4. Provide nutrition advice.
5. Provide fitness advice.
6. Provide supplement advice.
7. Provide medication advice.
8. Recommend starting, stopping, replacing, or changing medication dosage.
9. Recommend diet plans.
10. Recommend exercise plans.
11. Recommend sleep interventions.
12. Recommend weight management plans.
13. Process real patient data.
14. Infer unsupported traits, symptoms, diseases, or outcomes.
15. Use LLM-generated content as rule logic.
16. Use runtime top-k literature retrieval to decide user-facing interpretations.
17. Automatically convert literature or public source records into active user-facing rules.
```

## 11. Core Architecture Principle

OpenPGx Copilot is not a RAG chatbot.

The core architecture is:

```text
curated genetic rule engine
+ evidence registry
+ safe explanation layer
```

The system must distinguish between decision logic and explanation.

```text
Rule engine = domain matching and interpretation logic
Evidence registry = curated evidence trace and allowed-use boundary
LLM = explanation, summarization, and communication layer only
```

User-facing interpretation must be generated from matched curated rules and their bound evidence references.

The runtime path is:

```text
structured input / routed request
→ validated request
→ matched curated rule
→ rule-bound evidence lookup
→ bounded explanation
→ safety validation
→ user-facing response
```

The user-facing interpretation must not be decided by:

```text
user query
→ top-k paper retrieval
→ LLM decides interpretation
```

## 12. Role of Retrieval

Retrieval is not the primary runtime interpretation mechanism in v0.1.

The primary v0.1 runtime path is rule-bound evidence lookup:

```text
matched_rule.evidence_refs
→ evidence_store.get(evidence_id)
→ explanation layer
```

RAG, search, BM25, hybrid retrieval, or graph retrieval may be used in future developer or reviewer workflows, such as:

```text
- Evidence discovery
- Candidate evidence review
- Source exploration
- Conflict analysis
- Evidence viewer search
```

But these retrieval workflows must not directly determine user-facing genetic interpretations in v0.1.

## 13. Role of Compiler Framework

v0.1 may include a lightweight evidence/rule compiler framework.

For wellness traits, the compiler framework may use structured or semi-structured public sources such as:

```text
- GWAS Catalog
- dbSNP / NCBI Variation Services
- PubMed metadata
```

The compiler may generate:

```text
- SourceRecord
- MarkerRecord
- EvidenceCandidateRecord
- RuleCandidateRecord
- ReviewCard
```

The compiler must not directly generate active user-facing rules.

The core rule is:

```text
Compiler output = candidate by default.
Human-reviewed and safety-validated output = active.
```

## 14. LLM Role

The LLM is an explanation layer, not a decision layer.

The LLM may:

```text
1. Rewrite rule engine outputs into user-friendly educational explanations.
2. Summarize provided evidence snippets.
3. Generate limitation-aware explanations.
4. Explain why unsupported inputs cannot be interpreted.
5. Produce structured text only from rule outputs and provided evidence records.
6. Help generate reviewer-facing summaries for candidate evidence, if clearly marked non-active.
```

The LLM must not:

```text
1. Perform rule matching.
2. Create genetic trait rules.
3. Infer unsupported traits.
4. Invent evidence claims.
5. Invent citations or source metadata.
6. Upgrade or downgrade evidence strength.
7. Convert educational associations into personalized recommendations.
8. Provide medical, nutrition, fitness, supplement, diagnosis, disease-risk, or medication advice.
9. Promote compiler-generated candidates into active rules.
```

## 15. Success Criteria for v0.1

v0.1 is successful if the system can:

```text
1. Accept synthetic rsID-genotype inputs.
2. Match supported inputs against a small curated wellness trait rule set.
3. Produce structured trait interpretation results.
4. Link every interpretation to explicit evidence references.
5. Generate limitation-aware educational explanations.
6. Include required safety messages.
7. Reject or downgrade when input is unsupported, evidence is missing, or request is unsafe.
8. Prevent the LLM from producing medical, nutrition, fitness, supplement, medication, diagnosis, or disease-risk advice.
9. Establish reusable rule, evidence, explanation, safety, and validation architecture for future PGx medication alert modules.
10. Optionally demonstrate candidate-only evidence/rule compiler output from public structured sources.
```

## 16. Long-Term Direction

Future versions may extend OpenPGx Copilot toward pharmacogenomics medication alert support.

The future PGx path may involve:

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

Future versions may also use PGx-specific public sources, including:

```text
- CPIC / ClinPGx
- PharmGKB
- PharmCAT allele definitions and output behavior
- PharmVar
- FDA drug labels / openFDA label data
- ClinVar as supporting metadata
- Possibly DPWG guidelines
```

This future direction is out of scope for v0.1 implementation but must remain compatible with the v0.1 architecture.
