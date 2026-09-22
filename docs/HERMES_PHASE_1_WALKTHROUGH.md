# HERMES PHASE 1 — WALKTHROUGH

## 1. Architecture
12-stage pipeline.

## 2. Execution Flow
From `core/orchestrator.py` through to KAIROS.

## 3. Instrumentation Points
- `core/telemetry.py` spans
- `models/ollama_client.py` payload extraction

## 4. Benchmark Results
30 tasks. 4 successes. Avg latency 15.12s.

## 5. Latency Waterfall
Dominated by 5.97s model load.

## 6. Known Problems
- keep_alive=0 in Ollama
- `strip_markdown_fences` parser failure

## 7. Baseline Numbers
- Avg Latency: 15.12s
- Model Latency: 14.93s
- Success: 4/30
