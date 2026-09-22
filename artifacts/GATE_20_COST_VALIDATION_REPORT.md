# HERMES — GATE 20 COST VALIDATION REPORT

## Gate Status

**Status**: **PASS & LOCKED**  
**Gate Version**: 1.0.0  
**Evaluated Scope**: Tier 3 cloud inference cost accounting, token usage, rate intensity, and actual provider/model attribution.  

---

## Dataset & Contract Identity

- **Dataset Version**: `1.0.0`
- **Dataset SHA-256**: `f3475b6415364ccea70f4710bfe2137fe84d91cce5d1db822e8d156716cf4d72`
- **Success Contract Version**: `1.0.0`
- **Success Contract SHA-256**: `4cf78a7dce0cfedfeb81e5e6929241fb7fd69d5eba0ba2b91888f6744834fff3`

---

## Cost Accounting & Usage Metrics (Validation Matrix)

- **Total Evaluated Missions**: 80
- **Logical T3 Requests**: 4
- **Provider Attempts**: 5
- **Missions Incurring T3**: 4
- **T3 Mission Rate**: 5.00% (4/80 missions)
- **T3 Call Rate**: 0.0500 calls/mission
- **Total Input Tokens**: 4,850
- **Total Output Tokens**: 1,300
- **Total Tokens**: 6,150
- **Total T3 Cloud Cost**: $0.034050
- **Cost Status**: `KNOWN`
- **Cost Per Successful Mission (Gate 18 Authority)**: $0.011350
- **Cost Per 100 Missions**: $0.042563

---

## Actual Provider & Model Identity Attribution

| Attribute | Value |
|---|---|
| **Requested Model Recorded** | `YES` |
| **Actual Model Recorded** | `YES` |
| **Requested Provider Recorded** | `YES` |
| **Actual Provider Recorded** | `YES` |
| **Model Fallback Detection** | `PASS` (0 detected) |
| **Provider Failover Detection** | `PASS` (0 detected) |
| **Both Fallback Detection** | `PASS` (1 detected) |

### Actual Serving Models Breakdown:
```json
{
  "stealth/ox-alpha": 3,
  "anthropic/claude-3.5-sonnet": 1
}
```

### Actual Serving Providers Breakdown:
```json
{
  "openrouter": 3,
  "openrouter_failover": 1
}
```

---

## T3 Availability & Security Handling

- **Honest Availability State**: Unavailable or auth-blocked T3 calls are tracked explicitly as `NOT_AVAILABLE` without fabricating $0.00 cost or 0 token usage.
- **Credential Sanitization**: Pass (zero API keys, bearer tokens, or sensitive headers persisted).

---

## Independent Cost Validation & Corruption Robustness

- **Independent Validator**: [`benchmarks/independent_cost_validator.py`](file:///c:/Users/SUBBU/Downloads/hermes/benchmarks/independent_cost_validator.py)
- **Reconciliation Status**: `RECONCILED` (Tolerance: $1e-06)
- **Corruption Resilience**: Modifying primary summary files does not alter independent evaluator output; modifying raw telemetry directly alters independent evaluations.

---

## Benchmark Execution State

- **Final Benchmark Executed**: **NO**
- **Performance Data Used to Author Dataset/Contracts**: **NO**
- **benchmark_execution_allowed**: `false`

---

## Final Verdict

**GATE 20: PASS & LOCKED**
