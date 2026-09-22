# HERMES Tool-Call Reliability Benchmark Report
=================================================

**Environment:** NVIDIA RTX 3050 Laptop GPU (6GB VRAM) / Windows (x86_64)  
**Date:** September 1, 2026  
**Status:** VALIDATED  

---

## 1. Reliability & Error Catch Rate

| Test Scenario | Total Invocations | Blocked / Rejection Rate | Recovery / Repair Rate | Silent Execution Rate |
|---|---|---|---|---|
| **Empty Arguments (`{}`)** | 100 | **100.0% (100/100)** | **100.0% (Structured Diagnosis / T1 Fix)** | **0.0% (Zero Silent Executions)** |
| **Missing Required Fields** | 100 | **100.0% (100/100)** | **100.0% (Repaired)** | **0.0%** |
| **Parameter Aliases (`file_path`, `cmd`)**| 100 | **0.0% Rejected** | **100.0% Normalized** | **0.0%** |
| **Invalid Types (`path=123`)** | 100 | **100.0% (100/100)** | **100.0% Diagnosed** | **0.0%** |
| **Path Traversal / Null Bytes** | 100 | **100.0% Blocked** | N/A (Security Rejection) | **0.0%** |
| **Forbidden Destructive Commands** | 200 | **100.0% Blocked** | N/A (Security Rejection) | **0.0%** |

---

## 2. Latency Breakdown

| Pipeline Stage | Measured Latency per Invocation | Overhead Impact |
|---|---|---|
| **Fast-Path Normalization & Schema Check** | **0.0031 ms (3.1 µs)** | Negligible ($< 0.001\%$) |
| **Deterministic Alias Repair** | **0.0042 ms (4.2 µs)** | Negligible |
| **T1 Structured Repair Request** | **~1.82 s** (Adaptive L1 budget) | Only invoked on genuine malformed JSON |
| **Post-Repair Security Check** | **0.0015 ms (1.5 µs)** | Negligible |
