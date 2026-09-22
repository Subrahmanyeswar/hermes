# HERMES — Excluded Benchmark Results & Methodology Justification

This document details the datasets and experimental runs explicitly excluded from general capability claims in the research paper, conforming to scientific rigor and reproducibility standards.

---

## 1. Historical 80-Task Benchmark Run (`final_benchmark_20260905_140302`, 1/80 = 1.25%)

- **Recorded Outcome**: 1/80 tasks passed (1.25% objective success rate).
- **Classification**: **`INVALID BENCHMARK RESULT`** (Forensic Reference Only).
- **Reason for Exclusion**:
  1. **Provider Ingestion Defect**: Forensic audit (detailed in `artifacts/PHASE_2_OLLAMA_INGESTION_FIX_REPORT.md` and `artifacts/GATE_24_TASK_FORENSICS.md`) revealed that the Ollama client dropped DeepSeek-R1 `<think>` reasoning tags, passing empty text strings (`""`) to the `ResponseParser`.
  2. **Pipeline Short-Circuit**: Stage 4 failed on 78 of 80 tasks before tool execution could even be attempted. As a consequence, zero tool calls were executed across those missions.
  3. **Execution-Path Contamination**: The runner utilized a single-turn legacy orchestrator path rather than the certified `MissionPlanner -> MissionRunner` architecture.
- **Scientific Treatment in Paper**: Must **NOT** be cited as the system's true agentic capability. It serves solely in the system engineering / problem statement section as physical proof of the fragility of local model parsing contracts prior to the architectural repair.

---

## 2. Incomplete 80-Task Benchmark Run (`final_benchmark_20260908_083303`, Tasks 1–26)

- **Recorded Outcome**: 1/26 tasks completed (`A04` passed).
- **Classification**: **`INVALID BENCHMARK RESULT`** (Incomplete & Confounded).
- **Reason for Exclusion**:
  1. **Run Interruption**: Execution was terminated after Task C06 to prevent excessive GPU thermal strain and prioritize project submission deadlines. An incomplete benchmark run violates frozen benchmark protocol requirements.
  2. **Prompt-to-Contract Specification Mismatch**: Forensic inspection of the 25 failing tasks revealed that the benchmark prompts asked the model to implement specific source modules (e.g., `"Implement helper in utils/string_helpers.py"`), while the frozen success contract evaluated `pytest tests/test_string_helpers.py`. The local 8B model correctly generated the source file with valid AST, but did not autonomously create an unprompted secondary test file, triggering exit code 4 (usage error) in pytest.
- **Scientific Treatment in Paper**: Excluded from capability tables. Citable only in discussion sections addressing evaluation contract alignment between single-action prompts and multi-artifact acceptance verifiers.

---

## 3. Pre-Repair Exploratory Baseline (`performance/baseline_results.json`, N=30)

- **Recorded Outcome**: 73.33% claimed completion rate, 16.67% false completions.
- **Classification**: **`FORENSIC / DIAGNOSTIC RESULT`**.
- **Reason for Exclusion**:
  1. **Lack of Deterministic Objective Ground Truth**: The exploratory baseline relied heavily on self-reported agent status and unverified terminal outputs.
  2. **Incompatible Methodology**: Executed without the Gate 18 deterministic objective evaluator.
- **Scientific Treatment in Paper**: Kept as historical context illustrating the necessity of deterministic verification over self-reported agent claims.

---

## Summary of Authoritative Evidence Base

The research paper derives all core quantitative capability claims exclusively from:
1. **Gate 22 Full Regression Suite** (N = 945 deterministic tests, 100.0% passing).
2. **Controlled End-to-End Diagnostic Missions** (N = 4 live local model executions, 100.0% passing).
3. **Gate 21 Sustained-Load & Thermal Dataset** (N = 30 consecutive missions, 100.0% passing).
4. **Architectural Safety Gates** (Gates 10, 11, 12, 13, 15.6, 15.7, 15.9: N = 268 total tests, 100.0% passing).
