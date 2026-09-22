# HERMES — FINAL BENCHMARK EXECUTION PROTOCOL

## 1. Protocol Metadata & Version
- **Protocol Version**: `1.0.0`
- **Protocol Status**: `FROZEN & LOCKED`
- **Effective Gate**: Gate 23 (Final Pre-Benchmark Gate)
- **Target Workload**: Final 80-Task Comprehensive Benchmark Suite
- **Benchmark Execution Allowed**: `false` (Protocol Definition & Freeze Gate Only)

---

## 2. Locked Reference Gates & Invariants

| Gate | Name | Status | Key Cryptographic / Metric Invariant |
|---|---|---|---|
| **Gate 16** | Measurement Integrity | **LOCKED** | Monotonic boundaries (`time.perf_counter()`), raw telemetry authoritative |
| **Gate 17** | Final Dataset Freeze | **LOCKED** | SHA-256: `f3475b6415364ccea70f4710bfe2137fe84d91cce5d1db822e8d156716cf4d72` (80 tasks) |
| **Gate 18** | Objective Success Contract | **LOCKED** | SHA-256: `4cf78a7dce0cfedfeb81e5e6929241fb7fd69d5eba0ba2b91888f6744834fff3`, Evaluator authoritative |
| **Gate 19** | Reliability & Distribution | **LOCKED** | Percentile distribution (P50, P75, P90, P95, P99), false completion tracking |
| **Gate 20** | Tier 3 Cost Accounting | **LOCKED** | Actual model/provider attribution, OpenRouter fallback detection, token accounting |
| **Gate 21** | Sustained-Load & Thermal | **LOCKED** | Real hardware telemetry (temperature, clocks, power, VRAM), thermal degradation classification |
| **Gate 22** | Full Regression Suite | **LOCKED** | 945 collected, 945 passed, 0 failed, 0 errors, 0 skipped, 0 deselected |

---

## 3. Dataset & Task Execution Specification

### 3.1 Frozen Dataset
- **Version**: `1.0.0`
- **Task Count**: `80`
- **Category Breakdown (10 tasks each)**:
  - **A**: Simple Single-Step Tasks (A01–A10)
  - **B**: Standard Coding & Tool Use (B01–B10)
  - **C**: Multi-File Architectures (C01–C10)
  - **D**: Complex Logic & Full-Stack (D01–D10)
  - **E**: Debugging, Refactoring & Repair (E01–E10)
  - **F**: Workspace Understanding & Retrieval (F01–F10)
  - **G**: Adversarial, Edge-Case & Failure Handling (G01–G10)
  - **H**: Realistic User Ambiguity & Requirements (H01–H10)

### 3.2 Task Ordering
- **Execution Order**: Canonical Deterministic Order (`A01` through `H10`).
- **Randomization**: `false` (Deterministic sequential execution to ensure identical order across baseline and vNext runs).
- **Task Identity**: Original `task_id` remains immutable and primary across all telemetry and evaluation records.

---

## 4. System & Hardware Environment Freeze

- **Operating System**: Windows 11 / Windows NT
- **Python Runtime**: `3.10.0`
- **Pytest Version**: `9.0.3`
- **Primary GPU**: `NVIDIA GeForce RTX 3050 Laptop GPU` (6 GB VRAM)
- **Power State**: `AC_CONNECTED` (High Performance Power Profile locked)
- **Background Load**: `CONTROLLED_LOW_BACKGROUND_LOAD` (No concurrent GPU workloads)
- **Ollama Service**: Local residency on `http://127.0.0.1:11434`
- **Model Hierarchy**:
  - **Tier 1 (T1)**: `deepseek-r1:8b` (Primary local reasoning & tool synthesis)
  - **Tier 2 (T2)**: `qwen3:8b` (Verification, inspection & structured repair)
  - **Tier 3 (T3)**: `stealth/ox-alpha` via OpenRouter (Complex cloud escalation)

---

## 5. Codebase & System Identities

### 5.1 Baseline ("BEFORE")
- **Definition**: Established baseline architecture / baseline execution artifacts before multi-tier model residency, intelligent routing, context engine packing, and progressive verification hardening.
- **Rule**: If baseline cannot be re-executed under identical runtime conditions, recorded as `BASELINE_UNAVAILABLE` or referenced from validated historical baseline runs without fabrication.

### 5.2 HERMES vNext ("AFTER")
- **Repository Commit**: `be1a563bd73830efa0dff2400788ffe89d2ebc96`
- **Working Tree State**: Documented Dirty (Pre-benchmark gate artifacts staged/tracked)
- **Gate 22 Validation**: Verified 945/945 regression pass against current working tree.

---

## 6. Execution Isolation & State Management

### 6.1 Workspace Isolation
For every benchmark task:
1. Snapshot baseline workspace directory.
2. Purge task-generated output files from prior runs.
3. Reset modified files to initial test state.
4. Clear task-specific SQLite database tables (`tasks.db`).
5. Reset in-memory session and context states.
6. Verify clean filesystem state before launching mission.

### 6.2 Database & Memory Policy
- **Database**: Task-isolated execution database with clean transaction boundary per task.
- **Memory Policy**: Task-isolated episodic memory for standard evaluation tasks (cross-task memory tested strictly within designated memory tasks F01–F10).
- **Cache Policy**: Model weights remain warm in VRAM per `ModelResidencyManager` lifecycle rules; application caches reset between tasks.

---

## 7. Runtime Policies

### 7.1 Model Residency & Warm State Policy
- Production-like warm model residency maintained where possible.
- Each model call logs `lifecycle_state`: `WARM`, `COLD`, or `SWITCH_RELOAD`.
- Switch reload times tracked explicitly without conflating with inference generation latency.

### 7.2 Routing Policy
- Real autonomous routing via `IntelligentRouter` / `ComplexityClassifier`.
- No forced tier overrides; actual requested tier and selected tier recorded per mission.
- T3 requests record both requested model/provider and actual answering model/provider.

### 7.3 Retry, Repair & Timeout Policy
- **Retries**: Production retry budget enforced (max 3 retries). Attempt numbers tracked separately (First attempt vs Retry/Repair).
- **Timeouts**: Gate 14 timeout hierarchy: Effective deadline = `min(child_timeout, parent_remaining)`.
- **Cancellation**: Gate 13 cancellation semantics: Cancelled tasks marked `CANCELLED` (zero zombie execution permitted).
- **Crash Recovery**: Gate 15 crash-recovery semantics: Process crashes marked `PROCESS_CRASH` and recovered if checkpoint exists.

---

## 8. Measurement Boundaries & Telemetry Semantics (Gate 16 Compliant)

1. **E2E Mission Latency**: Measured from mission launch (`start_mission`) to final completion event via `time.perf_counter()`. Never calculated by summing subcomponent durations.
2. **TTFT (Time-To-First-Token)**: Measured from generation request start to arrival of first streaming chunk.
3. **Generation Latency**: Measured from first token arrival to final completion token.
4. **Tokens / Second**: `completion_tokens / generation_duration_seconds`.
5. **Tool Execution Latency**: Measured strictly across tool execution boundary (excluding LLM generation time).
6. **Verification Latency**: Measured strictly across Tier 2 verification call boundary.
7. **Hardware Telemetry**: Background polling every 100ms for GPU temperature, GPU clock, VRAM allocated/reserved, GPU utilization, and CPU load.

---

## 9. Objective Evaluation & Authority Hierarchy

### 9.1 Evaluation Authority
```
OBJECTIVE EVALUATOR (Gate 18 Contract)
    ↓
RAW AUTHORITATIVE TELEMETRY (Gate 16 Telemetry)
    ↓
STRUCTURED MISSION RECORDS (JSON Logs)
    ↓
PRIMARY AGGREGATE SUMMARY
    ↓
HERMES SELF-REPORTED COMPLETION (Zero Authority)
```

### 9.2 Key Correctness Classifications
- **OBJECTIVE_PASS**: Objective evaluator verifies all required artifacts and state transitions.
- **OBJECTIVE_FAIL**: Objective evaluator detects failed conditions or missing artifacts.
- **FALSE_COMPLETION**: HERMES claims success, but objective evaluator reports failure.
- **FALSE_NEGATIVE**: HERMES reports failure, but objective evaluator verifies success.
- **INCONCLUSIVE**: Telemetry corruption or environment invalidation (requires protocol re-run).

---

## 10. Final Comparison Dashboard Specification

The final benchmark report must produce the comprehensive BEFORE vs AFTER comparison:

| Metric | Before (Baseline) | After (HERMES vNext) | Absolute Delta | Delta % | Direction |
|---|---:|---:|---:|---:|:---:|
| **Objective Mission Success Rate** | — | — | — | — | Higher is Better |
| **False Completion Rate** | — | — | — | — | Lower is Better |
| **False Negative Rate** | — | — | — | — | Lower is Better |
| **First-Attempt Success Rate** | — | — | — | — | Higher is Better |
| **Repair Success Rate** | — | — | — | — | Higher is Better |
| **E2E Latency P50 (s)** | — | — | — | — | Lower is Better |
| **E2E Latency P75 (s)** | — | — | — | — | Lower is Better |
| **E2E Latency P90 (s)** | — | — | — | — | Lower is Better |
| **E2E Latency P95 (s)** | — | — | — | — | Lower is Better |
| **E2E Latency P99 (s)** | — | — | — | — | Lower is Better |
| **TTFT Average (s)** | — | — | — | — | Lower is Better |
| **Generation Tokens/sec** | — | — | — | — | Higher is Better |
| **Total LLM Invocations** | — | — | — | — | Lower is Better |
| **Tier 1 Only Resolution Rate** | — | — | — | — | Higher is Better |
| **Tier 2 Escalation Rate** | — | — | — | — | Lower is Better |
| **Tier 3 Cloud Request Rate** | — | — | — | — | Lower is Better |
| **Model Load / Switch Time (s)** | — | — | — | — | Lower is Better |
| **Context Assembly Latency (ms)** | — | — | — | — | Lower is Better |
| **Context Retrieval Accuracy (%)** | — | — | — | — | Higher is Better |
| **Tool Execution Failure Rate (%)** | — | — | — | — | Lower is Better |
| **Tool Failure Recovery Rate (%)** | — | — | — | — | Higher is Better |
| **Verification Latency Average (s)** | — | — | — | — | Lower is Better |
| **Peak VRAM Allocated (MB)** | — | — | — | — | Lower is Better |
| **Average GPU Utilization (%)** | — | — | — | — | Monitored |
| **Peak GPU Temperature (°C)** | — | — | — | — | Lower is Better |
| **Cloud Cost per Successful Mission ($)**| — | — | — | — | Lower is Better |
| **Security Boundary Violations** | 0 | 0 | 0 | 0.0% | Zero Tolerated |
| **Regression Test Pass Rate** | — | 945/945 (100%) | — | — | 100% Required |

---

## 11. Absolute Freeze & Execution Lock Rule

- **No Mid-Benchmark Tuning**: Modifying prompts, thresholds, timeouts, retries, model parameters, or code during benchmark execution is strictly prohibited.
- **Interruption Policy**: If execution is interrupted, the run must be explicitly resumed with preserved task checkpoints or restarted as a distinct run ID. Partial runs must never be silently merged.
- **Protocol Immutability**: Any modification to this protocol document increments the protocol version and invalidates Gate 23 lock.

**PROTOCOL FREEZE STATUS: LOCKED 🔒**
