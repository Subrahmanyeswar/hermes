# HERMES — PHASE 5 TELEMETRY RECONCILIATION REPORT
**Status**: PASS  
**Date**: 2026-09-04 08:39:47 UTC  

## 1. Preflight Telemetry Accounting

| Run | Model Latency | Tool Latency | Verification Latency | Total E2E Latency | Monotonic Order |
|---|---|---|---|---|---|
| **Real T1 E2E** | `17,701.9 ms` | `25.7 ms` | `0.1 ms` | `17,728.69 ms` | Verified |
| **Real T2 E2E** | `20,878.5 ms` | `23.1 ms` | `0.2 ms` | `20,902.53 ms` | Verified |

## 2. Invariants
- Total request latency strictly bounds sum of sub-stage spans.
- Timestamps recorded using high-resolution monotonic clocks (`time.perf_counter()`).
- Zero negative durations and zero simulated telemetry records.
