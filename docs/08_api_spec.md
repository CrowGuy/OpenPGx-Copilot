# 08 API Spec

## 1. Purpose

This document defines the v0.1 API specification for OpenPGx Copilot.

OpenPGx Copilot v0.1 is a wellness-first educational proof of concept with PGx-ready architecture.

The v0.1 API is intentionally small.

Supported endpoints:

```text
POST /pgx/check
GET  /pgx/rules
GET  /pgx/evidence/{evidence_id}
GET  /health
```

The core endpoint is:

```text
POST /pgx/check
```

This endpoint accepts synthetic rsID-genotype inputs and returns safe, evidence-linked, educational trait interpretations based on active curated rules.

## 2. API Design Principles

The v0.1 API follows these principles:

```text
1. Keep the API small.
2. Make POST /pgx/check the primary runtime endpoint.
3. Use synthetic inputs only.
4. Return structured, machine-readable results.
5. Return evidence references for every interpretation.
6. Include limitations and safety messages in every interpretation.
7. Never expose candidate rules or candidate evidence as runtime results.
8. Never use runtime top-k literature retrieval to decide user-facing interpretation.
9. Never let LLM output override rule engine or evidence store results.
10. Keep future PGx expansion possible without overbuilding v0.1.
```

## 3. v0.1 Endpoint Summary

```text
POST /pgx/check
  Runtime interpretation endpoint.
  Accepts synthetic rsID-genotype input.
  Returns educational interpretation results.

GET /pgx/rules
  Lists active v0.1 runtime rules.
  Does not expose candidate rules.

GET /pgx/evidence/{evidence_id}
  Returns an active evidence record by ID.
  Does not expose candidate evidence.

GET /health
  Returns service health and active rule/evidence set status.
```

## 4. Common API Conventions

### 4.1 Content Type

Request and response bodies use JSON.

```http
Content-Type: application/json
Accept: application/json
```

### 4.2 API Version

v0.1 may expose version in the response body.

Optional header:

```http
X-OpenPGx-Api-Version: 0.1
```

Recommended response field:

```json
{
  "api_version": "0.1"
}
```

### 4.3 Request ID

Every response should include a `request_id`.

If the client provides one, the service may preserve it.

If not provided, the service generates one.

### 4.4 Synthetic Input Only

v0.1 is for synthetic demo inputs only.

Every request must include:

```json
{
  "input_type": "synthetic"
}
```

`input_type` is required. If it is missing, or has any value other than `synthetic`, the service must reject the request with HTTP 400 and error code `invalid_input_type`. There is no default and local demo mode has no exception.

v0.1 must not process real patient data.

The realness of an rsID-genotype pair cannot be determined from its content: a synthetic and a real genotype are structurally identical. v0.1 therefore does not attempt to detect real data by inspecting genotype content. The synthetic-only boundary is enforced by (1) the declared `input_type`, (2) data minimization, and (3) non-retention and log redaction of free-text fields (see 4.5), not by content inspection.

### 4.5 Free-Text and Data Retention

`query` and `user_id` are the only free-text fields in v0.1. To keep the synthetic-only boundary testable even if a user pastes real data into them, the service must:

```text
1. Use free-text only for intent routing, response-mode selection, and safety classification.
2. Never pass free-text into the rule engine or into the LLM as domain interpretation input.
3. Never persist free-text (query, user_id) to durable storage in v0.1.
4. Redact free-text from logs and audit records.
```

`user_id`, if provided, must match the synthetic identifier pattern:

```text
^(demo|synthetic)-[A-Za-z0-9]{1,64}$
```

That is: a lowercase `demo-` or `synthetic-` prefix followed by 1 to 64 alphanumeric characters (for example `demo-001`, `synthetic-abc123`). The length cap keeps `user_id` from being used to smuggle free-text. A non-conforming `user_id` must be rejected with HTTP 400 and error code `invalid_user_id`.

## 5. Common Error Shape

Errors should be structured and machine-readable.

```json
{
  "request_id": "req-001",
  "api_version": "0.1",
  "status": "error",
  "error": {
    "code": "invalid_request",
    "message": "The request is invalid.",
    "details": []
  }
}
```

Error detail example:

```json
{
  "field": "genotypes[0].rsid",
  "code": "invalid_rsid_format",
  "message": "Invalid rsID format. Expected pattern: rs followed by digits."
}
```

## 6. Common Status Values

API-level status values:

```text
ok
error
```

Interpretation-level status values:

```text
matched
unsupported_marker
unmatched_genotype
insufficient_markers
invalid_input
blocked_by_safety
out_of_scope
```

Rule/evidence set status values:

```text
active
inactive
degraded
unavailable
```

## 7. POST /pgx/check

### 7.1 Purpose

`POST /pgx/check` is the primary v0.1 runtime endpoint.

It accepts synthetic rsID-genotype inputs and returns safe, evidence-linked, educational wellness trait interpretations.

Runtime path:

```text
request
→ request validation
→ lightweight request adapter / safety route
→ rule engine
→ rule-bound evidence lookup
→ explanation layer
→ output safety validation
→ response
```

This endpoint must not:

```text
1. Provide medical advice.
2. Provide nutrition advice.
3. Provide fitness advice.
4. Provide supplement advice.
5. Provide medication advice.
6. Provide diagnosis.
7. Predict disease risk.
8. Use top-k literature retrieval to decide interpretation.
9. Use LLMs to perform rule matching.
10. Use candidate rules or candidate evidence.
```

### 7.2 Request

```http
POST /pgx/check
Content-Type: application/json
```

Minimum request:

```json
{
  "user_id": "demo-001",
  "input_type": "synthetic",
  "module": "wellness_traits",
  "genotypes": [
    {
      "rsid": "rs671",
      "genotype": "AG"
    }
  ]
}
```

Request with optional query:

```json
{
  "request_id": "req-001",
  "user_id": "demo-001",
  "input_type": "synthetic",
  "module": "wellness_traits",
  "query": "I have rs671 AG. What does it mean?",
  "genotypes": [
    {
      "rsid": "rs671",
      "genotype": "AG"
    }
  ],
  "response_mode": "educational_explanation",
  "language": "en"
}
```

Chinese example:

```json
{
  "request_id": "req-zh-001",
  "user_id": "demo-001",
  "input_type": "synthetic",
  "module": "wellness_traits",
  "query": "我的 rs671 是 AG，這代表什麼？",
  "genotypes": [
    {
      "rsid": "rs671",
      "genotype": "AG"
    }
  ],
  "response_mode": "educational_explanation",
  "language": "zh-TW"
}
```

### 7.3 Request Fields

| Field           |   Type |    Required | Description                                                                        |
| --------------- | -----: | ----------: | ---------------------------------------------------------------------------------- |
| `request_id`    | string |          no | Client-provided request ID. Generated if missing.                                  |
| `user_id`       | string |          no | Synthetic user identifier. If provided, must match `^(demo\|synthetic)-[A-Za-z0-9]{1,64}$`; else 400 `invalid_user_id`. Never persisted or logged in cleartext. |
| `input_type`    | string |         yes | Must be `synthetic`. Rejected with 400 `invalid_input_type` if missing or any other value. |
| `module`        | string |         yes | v0.1 supports `wellness_traits`.                                                   |
| `query`         | string |          no | Optional simple user query for response mode and safety routing. Not domain logic. Never persisted or logged in cleartext. |
| `genotypes`     |  array |         yes | List of rsID-genotype inputs.                                                      |
| `response_mode` | string |          no | Defaults to `educational_explanation`.                                             |
| `language`      | string |          no | Suggested output language. Examples: `en`, `zh-TW`.                                |

Each genotype object:

| Field      |   Type | Required | Description                                          |
| ---------- | -----: | -------: | ---------------------------------------------------- |
| `rsid`     | string |      yes | rsID such as `rs671`.                                |
| `genotype` | string |      yes | Diploid genotype such as `AG`, `A/G`, `GA`, or `AA`. |

### 7.4 Supported v0.1 Module

```text
wellness_traits
```

Unsupported modules must return an error or out-of-scope response.

### 7.5 Supported v0.1 Response Modes

```text
educational_explanation
evidence_explanation
limitation_explanation
unsupported_input_explanation
downgraded_educational_explanation
safe_refusal
```

Default:

```text
educational_explanation
```

### 7.6 Request Validation

The service must validate:

```text
1. Request body is valid JSON.
2. module is supported.
3. input_type is present and equals `synthetic` (else 400 invalid_input_type).
4. user_id, if present, matches the synthetic identifier pattern (else 400 invalid_user_id).
5. genotypes is present and non-empty.
6. rsID format is valid.
7. genotype format is valid.
8. response_mode is supported.
9. query does not require blocked outputs.
```

v0.1 rsID format:

```text
rs followed by digits
```

Examples:

```text
Valid:
rs671
RS671

Invalid:
671
rsABC
ALDH2
chr12:111803962
```

v0.1 genotype normalization:

```text
A/G → AG
g/a → AG
GA  → AG
A A → AA
```

Invalid genotype examples:

```text
A
ABC
1/2
unknown
not available
```

### 7.7 Safety Routing

`POST /pgx/check` may assign or receive a safety route internally.

Supported safety routes:

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

Only these routes may produce normal educational interpretation:

```text
allowed
downgrade_to_educational
```

Refusal routes must not produce advice.

### 7.8 Successful Matched Response

Example:

```json
{
  "request_id": "req-001",
  "api_version": "0.1",
  "status": "ok",
  "module": "wellness_traits",
  "input_type": "synthetic",
  "rule_set": {
    "rule_set_id": "wellness_rules_v0_1_2026_07",
    "status": "active"
  },
  "evidence_set": {
    "evidence_set_id": "wellness_evidence_v0_1_2026_07",
    "status": "active"
  },
  "safety": {
    "route": "allowed",
    "blocked_outputs": [
      "medical_advice",
      "nutrition_advice",
      "fitness_advice",
      "supplement_advice",
      "medication_advice",
      "diagnosis",
      "disease_risk_prediction"
    ]
  },
  "results": [
    {
      "status": "matched",
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
      "summary": "The provided rs671 AG genotype matches a curated educational rule related to ALDH2 and alcohol metabolism.",
      "explanation": "The linked evidence describes an association between ALDH2 rs671 and reduced ALDH2 enzyme activity, which can affect acetaldehyde metabolism.",
      "limitations": [
        "Genotype is only one factor.",
        "Actual response may be affected by health status, environment, lifestyle, ancestry, and other genetic factors."
      ],
      "evidence_refs": [
        "evidence_aldh2_rs671_001"
      ],
      "source_refs": [
        "source_aldh2_rs671_paper_001"
      ],
      "safety_message": "This explanation is for educational purposes only and should not be used as medical, nutrition, fitness, supplement, or medication advice."
    }
  ],
  "unsupported_inputs": [],
  "warnings": []
}
```

### 7.9 Chinese Matched Response

Same structure as the matched response in 7.8; localized text with `language: zh-TW` and `safety_message` set verbatim to:

```text
本說明僅供教育用途，不應作為醫療、營養、運動訓練、補充劑或用藥建議。
```

### 7.10 Unsupported Marker Response

Example:

```json
{
  "request_id": "req-unsupported-001",
  "api_version": "0.1",
  "status": "ok",
  "module": "wellness_traits",
  "input_type": "synthetic",
  "safety": {
    "route": "unsupported_input",
    "blocked_outputs": [
      "medical_advice",
      "nutrition_advice",
      "fitness_advice",
      "supplement_advice",
      "medication_advice",
      "diagnosis",
      "disease_risk_prediction"
    ]
  },
  "results": [],
  "unsupported_inputs": [
    {
      "rsid": "rs999999",
      "genotype": "AG",
      "reason": "No active v0.1 curated rule supports this marker."
    }
  ],
  "explanation": "The provided marker is not supported by the active v0.1 curated rule set. OpenPGx Copilot cannot generate an interpretation for this input.",
  "safety_message": "This explanation is for educational purposes only and should not be used as medical, nutrition, fitness, supplement, or medication advice.",
  "warnings": [
    "Unsupported markers must not be interpreted."
  ]
}
```

### 7.11 Unmatched Genotype Response

Example:

```json
{
  "request_id": "req-unmatched-001",
  "api_version": "0.1",
  "status": "ok",
  "module": "wellness_traits",
  "input_type": "synthetic",
  "safety": {
    "route": "unsupported_input",
    "blocked_outputs": [
      "medical_advice",
      "nutrition_advice",
      "fitness_advice",
      "supplement_advice",
      "medication_advice",
      "diagnosis",
      "disease_risk_prediction"
    ]
  },
  "results": [],
  "unsupported_inputs": [
    {
      "rsid": "rs671",
      "genotype": "GG",
      "reason": "Marker is recognized, but this genotype does not match an active v0.1 interpretation rule."
    }
  ],
  "explanation": "The marker is recognized by the active v0.1 rule set, but the provided genotype does not match an active interpretation rule. No interpretation was generated.",
  "safety_message": "This explanation is for educational purposes only and should not be used as medical, nutrition, fitness, supplement, or medication advice.",
  "warnings": [
    "The system must not infer a negative, normal, or alternative interpretation without an explicit active rule."
  ]
}
```

### 7.12 Downgraded Advice Request Response

Example request:

```json
{
  "request_id": "req-advice-001",
  "user_id": "demo-001",
  "input_type": "synthetic",
  "module": "wellness_traits",
  "query": "I have rs671 AG. Should I stop drinking alcohol?",
  "genotypes": [
    {
      "rsid": "rs671",
      "genotype": "AG"
    }
  ],
  "language": "en"
}
```

Example response:

```json
{
  "request_id": "req-advice-001",
  "api_version": "0.1",
  "status": "ok",
  "module": "wellness_traits",
  "input_type": "synthetic",
  "safety": {
    "route": "downgrade_to_educational",
    "blocked_outputs": [
      "medical_advice",
      "nutrition_advice",
      "fitness_advice",
      "supplement_advice",
      "medication_advice",
      "diagnosis",
      "disease_risk_prediction"
    ]
  },
  "results": [
    {
      "status": "matched",
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
      "summary": "OpenPGx Copilot v0.1 cannot answer the advice portion of this request. For educational purposes only, the provided genotype matched an active curated rule related to ALDH2 and alcohol metabolism.",
      "explanation": "The linked evidence describes an association between ALDH2 rs671 and reduced ALDH2 enzyme activity. This should not be used to make medical, nutrition, fitness, supplement, medication, or lifestyle decisions.",
      "limitations": [
        "Genotype is only one factor.",
        "Actual response may be affected by health status, environment, lifestyle, ancestry, and other genetic factors."
      ],
      "evidence_refs": [
        "evidence_aldh2_rs671_001"
      ],
      "source_refs": [
        "source_aldh2_rs671_paper_001"
      ],
      "safety_message": "This explanation is for educational purposes only and should not be used as medical, nutrition, fitness, supplement, or medication advice."
    }
  ],
  "unsupported_inputs": [],
  "warnings": [
    "The user asked for advice. The response was downgraded to educational explanation."
  ]
}
```

### 7.13 Safe Refusal Response

Example request:

```json
{
  "request_id": "req-risk-001",
  "user_id": "demo-001",
  "input_type": "synthetic",
  "module": "wellness_traits",
  "query": "Does rs671 AG mean I have cancer risk?",
  "genotypes": [
    {
      "rsid": "rs671",
      "genotype": "AG"
    }
  ],
  "language": "en"
}
```

Example response:

```json
{
  "request_id": "req-risk-001",
  "api_version": "0.1",
  "status": "ok",
  "module": "wellness_traits",
  "input_type": "synthetic",
  "safety": {
    "route": "refuse_disease_risk",
    "blocked_outputs": [
      "medical_advice",
      "nutrition_advice",
      "fitness_advice",
      "supplement_advice",
      "medication_advice",
      "diagnosis",
      "disease_risk_prediction"
    ]
  },
  "results": [],
  "explanation": "OpenPGx Copilot v0.1 cannot provide disease-risk prediction, diagnosis, or medical advice.",
  "safety_message": "This explanation is for educational purposes only and should not be used as medical, nutrition, fitness, supplement, or medication advice.",
  "warnings": [
    "Disease-risk prediction is outside v0.1 scope."
  ]
}
```

### 7.14 Invalid Request Response

Invalid rsID example:

```json
{
  "request_id": "req-invalid-001",
  "api_version": "0.1",
  "status": "error",
  "error": {
    "code": "invalid_request",
    "message": "The request contains invalid input.",
    "details": [
      {
        "field": "genotypes[0].rsid",
        "code": "invalid_rsid_format",
        "message": "Invalid rsID format. Expected pattern: rs followed by digits."
      }
    ]
  }
}
```

Invalid genotype example:

```json
{
  "request_id": "req-invalid-002",
  "api_version": "0.1",
  "status": "error",
  "error": {
    "code": "invalid_request",
    "message": "The request contains invalid input.",
    "details": [
      {
        "field": "genotypes[0].genotype",
        "code": "invalid_genotype_format",
        "message": "Invalid genotype format for v0.1 diploid marker input."
      }
    ]
  }
}
```

## 8. GET /pgx/rules

### 8.1 Purpose

`GET /pgx/rules` lists active v0.1 runtime rules.

It is primarily for developer visibility, demos, and audit.

It must not expose candidate rules.

It must not expose internal reviewer-only candidate records.

### 8.2 Request

```http
GET /pgx/rules
```

Optional query parameters:

| Parameter |   Type | Required | Description                    |
| --------- | -----: | -------: | ------------------------------ |
| `module`  | string |       no | Defaults to `wellness_traits`. |
| `trait`   | string |       no | Filter by trait.               |
| `gene`    | string |       no | Filter by gene.                |
| `rsid`    | string |       no | Filter by marker.              |

Examples:

```http
GET /pgx/rules
GET /pgx/rules?module=wellness_traits
GET /pgx/rules?gene=ALDH2
GET /pgx/rules?rsid=rs671
```

### 8.3 Response

```json
{
  "api_version": "0.1",
  "status": "ok",
  "module": "wellness_traits",
  "rule_set": {
    "rule_set_id": "wellness_rules_v0_1_2026_07",
    "status": "active"
  },
  "rules": [
    {
      "rule_id": "aldh2_rs671_alcohol_metabolism",
      "status": "active",
      "domain": "wellness_trait",
      "gene": "ALDH2",
      "trait": "alcohol_metabolism",
      "markers": [
        {
          "rsid": "rs671",
          "genotype_pattern": "AG|AA"
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
}
```

### 8.4 Rules Endpoint Constraints

`GET /pgx/rules` must:

```text
1. Return active rules only.
2. Exclude candidate rules.
3. Exclude inactive or deprecated rules by default.
4. Include evidence_refs.
5. Include interpretation_level.
6. Not include internal reviewer notes unless explicitly approved for developer mode.
```

## 9. GET /pgx/evidence/{evidence_id}

### 9.1 Purpose

`GET /pgx/evidence/{evidence_id}` returns an active evidence record by ID.

It is used for traceability and developer/demo inspection.

It must not expose candidate evidence through this runtime endpoint.

### 9.2 Request

```http
GET /pgx/evidence/{evidence_id}
```

Example:

```http
GET /pgx/evidence/evidence_aldh2_rs671_001
```

### 9.3 Successful Response

```json
{
  "api_version": "0.1",
  "status": "ok",
  "evidence": {
    "id": "evidence_aldh2_rs671_001",
    "status": "active",
    "domain": "wellness_trait",
    "gene": "ALDH2",
    "markers": [
      "rs671"
    ],
    "trait": "alcohol_metabolism",
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
    ],
    "entities": {
      "genes": [
        "ALDH2"
      ],
      "markers": [
        "rs671"
      ],
      "traits": [
        "alcohol_metabolism"
      ],
      "drugs": [],
      "phenotypes": [],
      "populations": [
        "East Asian"
      ]
    }
  }
}
```

### 9.4 Not Found Response

```json
{
  "api_version": "0.1",
  "status": "error",
  "error": {
    "code": "evidence_not_found",
    "message": "No active evidence record was found for the provided evidence_id.",
    "details": [
      {
        "field": "evidence_id",
        "code": "not_found",
        "message": "Candidate, inactive, deprecated, or missing evidence is not available through this endpoint."
      }
    ]
  }
}
```

### 9.5 Evidence Endpoint Constraints

`GET /pgx/evidence/{evidence_id}` must:

```text
1. Return active evidence only.
2. Exclude candidate evidence.
3. Include allowed_use and disallowed_use.
4. Include limitations.
5. Include source_refs.
6. Avoid exposing raw full-text paper content.
7. Avoid presenting evidence as advice.
```

## 10. GET /health

### 10.1 Purpose

`GET /health` returns service health and active registry status.

It is intended for monitoring and deployment checks.

### 10.2 Request

```http
GET /health
```

### 10.3 Successful Response

```json
{
  "status": "ok",
  "api_version": "0.1",
  "service": "openpgx-copilot",
  "environment": "local",
  "rule_set": {
    "rule_set_id": "wellness_rules_v0_1_2026_07",
    "status": "active",
    "loaded_rule_count": 5
  },
  "evidence_set": {
    "evidence_set_id": "wellness_evidence_v0_1_2026_07",
    "status": "active",
    "loaded_evidence_count": 5
  },
  "checks": {
    "rule_engine": "ok",
    "evidence_store": "ok",
    "safety_validator": "ok"
  }
}
```

### 10.4 Degraded Response

```json
{
  "status": "degraded",
  "api_version": "0.1",
  "service": "openpgx-copilot",
  "environment": "local",
  "rule_set": {
    "rule_set_id": "wellness_rules_v0_1_2026_07",
    "status": "degraded",
    "loaded_rule_count": 4
  },
  "evidence_set": {
    "evidence_set_id": "wellness_evidence_v0_1_2026_07",
    "status": "active",
    "loaded_evidence_count": 5
  },
  "checks": {
    "rule_engine": "degraded",
    "evidence_store": "ok",
    "safety_validator": "ok"
  },
  "warnings": [
    "One active rule failed validation and was not loaded."
  ]
}
```

For v0.1 strict mode, degraded rule set loading should usually fail startup rather than silently serving partial results. If degraded mode exists, it should be explicit.

## 11. HTTP Status Codes

Recommended HTTP status codes:

|  Code | Use                                                                                       |
| ----: | ----------------------------------------------------------------------------------------- |
| `200` | Successful request, including matched, unsupported, unmatched, or safe refusal responses. |
| `400` | Invalid request format, invalid rsID, invalid genotype, unsupported module.               |
| `404` | Active evidence ID not found.                                                             |
| `422` | Request is syntactically valid but cannot be processed due to validation constraints.     |
| `500` | Internal service error.                                                                   |
| `503` | Service unavailable, rule set unavailable, evidence set unavailable.                      |

Notes:

```text
Unsupported marker is usually 200 with structured unsupported result.
Invalid rsID format is 400.
Advice refusal is usually 200 with safe refusal payload.
Missing active evidence record by ID is 404.
Rule set unavailable is 503.
```

## 12. Safety Requirements

All endpoints must respect v0.1 safety boundaries.

`POST /pgx/check` must never return:

```text
1. Medical advice.
2. Nutrition advice.
3. Fitness advice.
4. Supplement advice.
5. Medication advice.
6. Diagnosis.
7. Disease-risk prediction.
8. Treatment recommendation.
9. Lifestyle recommendation.
```

Every interpretation response must include:

```text
This explanation is for educational purposes only and should not be used as medical, nutrition, fitness, supplement, or medication advice.
```

Chinese:

```text
本說明僅供教育用途，不應作為醫療、營養、運動訓練、補充劑或用藥建議。
```

## 13. Candidate Record API Boundary

v0.1 runtime API must not expose candidate records through these endpoints.

Specifically:

```text
POST /pgx/check
  Must use active RuleRecords and active EvidenceRecords only.

GET /pgx/rules
  Must return active rules only.

GET /pgx/evidence/{evidence_id}
  Must return active evidence only.

GET /health
  May report candidate storage availability only if needed, but should not expose candidate content.
```

Candidate APIs may be added later for reviewer workflows, but they are not part of the v0.1 public runtime API.

## 14. Runtime Retrieval Boundary

`POST /pgx/check` must not perform runtime top-k literature retrieval to decide interpretation.

Allowed runtime evidence path:

```text
matched_rule.evidence_refs
→ evidence_store.get(evidence_id)
→ explanation layer
```

Disallowed runtime path:

```text
user query
→ literature search
→ top-k papers
→ LLM decides genetic interpretation
```

Evidence viewer or reviewer retrieval may be added later but is not part of this v0.1 API.

## 15. LLM Boundary in API Behavior

The API may return text generated by the LLM Explanation Layer, but the LLM output must be bounded by:

```text
1. RuleEngineResult.
2. Active EvidenceRecords.
3. SourceRecord metadata.
4. Required safety message.
5. Safety route.
6. Blocked output categories.
```

The API must not return LLM-created:

```text
1. Rule IDs.
2. Evidence IDs.
3. Source IDs.
4. PMIDs.
5. DOIs.
6. Effect sizes.
7. Population claims.
8. Advice.
9. Disease-risk predictions.
```

Every LLM-assisted output must pass OutputSafetyValidator before being returned.

## 16. Minimal OpenAPI Sketch

This is a simplified sketch, not a full OpenAPI document.

```yaml
openapi: 3.1.0
info:
  title: OpenPGx Copilot API
  version: "0.1"
paths:
  /pgx/check:
    post:
      summary: Check synthetic rsID-genotype input against active curated wellness rules.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/PGxCheckRequest"
      responses:
        "200":
          description: Matched, unsupported, downgraded, or refused response.
        "400":
          description: Invalid request.
        "503":
          description: Rule or evidence set unavailable.

  /pgx/rules:
    get:
      summary: List active v0.1 runtime rules.
      responses:
        "200":
          description: Active rules list.

  /pgx/evidence/{evidence_id}:
    get:
      summary: Get active evidence record by ID.
      parameters:
        - name: evidence_id
          in: path
          required: true
          schema:
            type: string
      responses:
        "200":
          description: Active evidence record.
        "404":
          description: Evidence not found.

  /health:
    get:
      summary: Service health and active registry status.
      responses:
        "200":
          description: Service health.
        "503":
          description: Service unavailable.

components:
  schemas:
    PGxCheckRequest:
      type: object
      required:
        - module
        - genotypes
      properties:
        request_id:
          type: string
        user_id:
          type: string
        input_type:
          type: string
          enum:
            - synthetic
        module:
          type: string
          enum:
            - wellness_traits
        query:
          type: string
        response_mode:
          type: string
          enum:
            - educational_explanation
            - evidence_explanation
            - limitation_explanation
            - unsupported_input_explanation
            - downgraded_educational_explanation
            - safe_refusal
        language:
          type: string
        genotypes:
          type: array
          items:
            $ref: "#/components/schemas/GenotypeInput"

    GenotypeInput:
      type: object
      required:
        - rsid
        - genotype
      properties:
        rsid:
          type: string
          example: rs671
        genotype:
          type: string
          example: AG
```

## 17. Example cURL Commands

### 17.1 Matched Check

```bash
curl -X POST http://localhost:8000/pgx/check \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "demo-001",
    "input_type": "synthetic",
    "module": "wellness_traits",
    "genotypes": [
      {
        "rsid": "rs671",
        "genotype": "AG"
      }
    ]
  }'
```

### 17.2 Unsupported Marker

```bash
curl -X POST http://localhost:8000/pgx/check \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "demo-001",
    "input_type": "synthetic",
    "module": "wellness_traits",
    "genotypes": [
      {
        "rsid": "rs999999",
        "genotype": "AG"
      }
    ]
  }'
```

### 17.3 List Active Rules

```bash
curl http://localhost:8000/pgx/rules
```

### 17.4 Get Evidence

```bash
curl http://localhost:8000/pgx/evidence/evidence_aldh2_rs671_001
```

### 17.5 Health

```bash
curl http://localhost:8000/health
```

## 18. API Tests

Required API tests:

```text
1. POST /pgx/check returns matched result for supported active rule.
2. POST /pgx/check returns unsupported_marker for unsupported rsID.
3. POST /pgx/check returns unmatched_genotype when marker is supported but genotype has no active rule.
4. POST /pgx/check rejects invalid rsID format.
5. POST /pgx/check rejects invalid genotype format.
6. POST /pgx/check downgrades advice requests.
7. POST /pgx/check refuses disease-risk requests.
8. POST /pgx/check includes evidence_refs for every matched result.
9. POST /pgx/check includes limitations.
10. POST /pgx/check includes required safety message.
11. POST /pgx/check does not return medical, nutrition, fitness, supplement, medication, diagnosis, or disease-risk advice.
12. GET /pgx/rules returns active rules only.
13. GET /pgx/rules does not return candidate rules.
14. GET /pgx/evidence/{evidence_id} returns active evidence only.
15. GET /pgx/evidence/{evidence_id} does not return candidate evidence.
16. GET /health returns active rule/evidence set status.
```

## 19. v0.1 API Acceptance Criteria

The v0.1 API is acceptable if:

```text
1. It exposes only the four defined endpoints.
2. POST /pgx/check is the only runtime interpretation endpoint.
3. POST /pgx/check accepts synthetic rsID-genotype input.
4. POST /pgx/check returns structured, evidence-linked educational results.
5. Every matched result includes evidence_refs.
6. Every matched result includes limitations.
7. Every matched result includes the required safety message.
8. Unsupported markers do not produce invented interpretation.
9. Unmatched genotypes do not produce inferred normal or negative interpretation.
10. Advice requests are refused or downgraded.
11. Candidate records are never returned as active runtime results.
12. Runtime top-k literature retrieval is not used.
13. LLM output does not override rule/evidence/safety outputs.
14. GET /pgx/rules exposes active rules only.
15. GET /pgx/evidence/{evidence_id} exposes active evidence only.
16. GET /health reports service and registry health.
```
