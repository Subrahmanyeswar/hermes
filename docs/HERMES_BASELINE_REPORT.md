# HERMES PHASE 1 — BASELINE PERFORMANCE REPORT

## 1. Architecture
HERMES follows a 12-stage pipeline orchestrated by `core/orchestrator.py`...

## 2. Request Flow
Standard sequential processing of stages...

## 3. Hardware
- CPU Usage: 41.5%
- RAM: 11297.80MB / 16091.90MB
- GPU: NVIDIA GeForce RTX 3050 6GB Laptop GPU (Util: 95.0%, VRAM: 4859.00MB / 6144.00MB)

## 4. Models
Primary models evaluated via Ollama.

## 5. Benchmark tasks
30 benchmark tasks across Categories A through E.

## 6. Raw Results
Processed 30 requests.

## 7. Averages
- Average Total Latency: 15.12s
- Success Rate: 4/30 (13.3%)

## 8. Cold vs Warm
Currently all requests are cold loads due to `keep_alive=0` in Ollama.

## 9. Model Performance
- Avg Load Duration: 5.97s
- Avg TTFT: 7.29s

## 10. Context
- Avg Context Size: 2392 tokens

## 11. Workspace
- Avg Workspace Scan: 0.0000s

## 12. Tool
Tool execution latencies tracked in spans.

## 13. KAIROS
KAIROS mission runner metrics...

## 14. Verification
- Avg Verification Latency: 0.0000s

## 15. TUI
TUI rendering metrics...

## 16. Resource Utilization
Peak VRAM 4859.0MB.

## 17. Latency Waterfall
Ollama Load -> Prompt Eval -> Gen -> Parse -> Tool

## 18. Top 10 Bottlenecks
1. Ollama keep_alive=0 causing massive load_duration on every request
2. Markdown parser falling back to empty dict `{}` causing Pydantic ValidationError.
3. Synchronous tool execution blocking pipeline.

## 19. RCA
Ollama reloading models repeatedly due to parameter config.
Parser fails to extract poorly formatted markdown.

## 20-28. Quality metrics, etc.
Metrics tracked during execution...
