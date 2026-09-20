# iAI research pilot evaluation

- executed_at: 2026-09-20T15:17:04+08:00
- provider: iai
- status: completed
- planned_model_calls: 12
- actual_model_calls: 12
- hard_call_limit: 12
- weather_fail_closed_cases: 4
- weather_provider_calls: 0
- full_evaluation_minimum_gate: not_passed

## Category calls

| category | calls |
| --- | ---: |
| conservation | 4 |
| site_basic | 4 |
| edna_history | 4 |

## Outcomes

| outcome | count |
| --- | ---: |
| accepted | 0 |
| rejected | 0 |
| timeout | 0 |
| provider_error | 12 |
| quota_error | 0 |

## Validator rejection codes

- none

## Case outcomes

- `conservation-001`: `provider_service_error`
- `conservation-004`: `provider_service_error`
- `conservation-008`: `provider_service_error`
- `conservation-012`: `provider_service_error`
- `site-001`: `provider_service_error`
- `site-004`: `provider_service_error`
- `site-008`: `provider_service_error`
- `site-010`: `provider_service_error`
- `edna-001`: `provider_service_error`
- `edna-004`: `provider_service_error`
- `edna-008`: `provider_service_error`
- `edna-012`: `provider_service_error`

## Scope

This report contains aggregate outcomes and stable case IDs only. It does not retain model output, controlled context, settings, secrets, source text, or local paths.
Passing this small pilot does not authorize a full evaluation, public chat endpoint, UI, or deployment.
