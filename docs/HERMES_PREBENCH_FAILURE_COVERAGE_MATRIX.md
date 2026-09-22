# HERMES Pre-Benchmark Gate 15.2: Failure Coverage Matrix
========================================================

**Date:** September 2, 2026  
**Status:** VALIDATED  

---

| ID | Scenario / Injected Fault | Expected Behavior | Actual Runtime Result | Verdict |
|---|---|---|---|---|
| **A1** | T1 Model Unavailable | Provider error classified, router escalates to T2 | Escalated to T2 with reason logged | **CORRECTLY_ESCALATED** |
| **A2** | T2 Model Unavailable | Fallback to deterministic local verification | Accepted verified T1 outcome safely | **RECOVERED** |
| **A3** | T3 Model Unavailable | Disagreement without T3 triggers fail-safe halt | Fail-safe halt with diagnostic | **GRACEFULLY_FAILED** |
| **A4** | Ollama Disconnect | Connection refused classified cleanly without hang | Error structured in payload | **RECOVERED** |
| **A5** | Local Model Timeout | Inference deadline exceeded (>60s) classified | Bounded timeout raised | **RECOVERED** |
| **A6** | OpenRouter Timeout | HTTP client timeout detected | Non-hanging error classification | **RECOVERED** |
| **A7** | OpenRouter 429 Limit | HTTP 429 rate limit distinguished from fatal defect | Rate limit error flagged | **RECOVERED** |
| **B1** | Malformed JSON Output | Parser catches truncated/garbled JSON | Rejected before tool execution | **CORRECTLY_BLOCKED** |
| **B2** | Missing Tool Arguments | Empty argument `{}` rejected by schema validator | Rejected before tool execution | **CORRECTLY_BLOCKED** |
| **B3** | Invalid Argument Type | Type mismatch rejected by Pydantic validator | Rejected before tool execution | **CORRECTLY_BLOCKED** |
| **B4** | Unknown Tool Call | Nonexistent tool rejected with registry diagnostic | Rejected before tool execution | **CORRECTLY_BLOCKED** |
| **C1** | Filesystem Missing Output | Missing output file caught by structural check | Structural check failed cleanly | **GRACEFULLY_FAILED** |
| **C2** | Path Traversal Attack | `../../etc/passwd` path traversal blocked | Security gate blocked execution | **CORRECTLY_BLOCKED** |
| **D1** | Test Assertion Failure | Assertion failure extracted and classified | Triggers targeted repair cycle | **RECOVERED** |
| **D2** | Syntax Error in Code | AST syntax error short-circuits test suite | Short-circuited Level 2-4 tests | **RECOVERED** |
| **D3** | Verifier Timeout | Subprocess timeout classified as environment defect | Classified environment defect | **RECOVERED** |
| **E1** | External File Modification | Hash mismatch detected on index refresh | Refreshed index with new hash | **RECOVERED** |
| **E2** | Stale Workspace Index | Deleted files evicted on incremental re-index | Evicted stale file entries | **RECOVERED** |
| **F1** | KAIROS Task Failure | Task marked FAILED, dependent tasks BLOCKED | Dependent tasks kept BLOCKED | **CORRECTLY_BLOCKED** |
| **F2** | Blocked DAG Dependency | Mission completion rejected while tasks blocked | Denied completion verdict | **CORRECTLY_BLOCKED** |
| **F3** | KAIROS Retry Limit | Retries bounded at `max_retries = 2` | Reached terminal FAILED state | **GRACEFULLY_FAILED** |
| **G1** | Exhausted Repair Budget | Repair bounded at `max_repairs = 3` | Blocked further repair attempts | **GRACEFULLY_FAILED** |
| **G2** | Repair Adds Defect | Verifier catches secondary runtime assertion error | Caught secondary defect on re-test | **RECOVERED** |
| **H1** | TUI Presentation Crash | UI exception isolated from EventBus dispatch | EventBus continued uninterrupted | **RECOVERED** |
| **H2** | Crashing Subscriber | Broken subscriber does not crash state store | State store updated normally | **RECOVERED** |
| **H3** | Repeated Event Errors | Consecutive subscriber errors handled gracefully | No runtime crash or lockup | **RECOVERED** |
| **I1** | Process Interruption | State logged durably for post-mortem analysis | Event stream logged; resume gap noted | **KNOWN_GAP** |
| **J1** | T1 Down + T2 Escalation | Multi-fault combination handled cleanly | Escalated and finalized successfully | **RECOVERED** |
