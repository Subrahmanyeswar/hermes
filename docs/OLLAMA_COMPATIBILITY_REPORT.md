# HERMES Ollama Compatibility Report
**Models Tested:** `deepseek-r1:8b` (Tier 1), `qwen3:8b` (Tier 2)  
**Provider:** Ollama Local Daemon (`http://127.0.0.1:11434`)  
**Scope:** Production-path compatibility verified for the tested non-streaming Ollama `/api/generate` execution path.  

## 1. Verified Model Execution Matrix

| Capability | `deepseek-r1:8b` (T1) | `qwen3:8b` (T2) | Verification Status |
|---|---|---|---|
| Ingestion of `<think>` tags | Normalized via `normalize_ollama_payload` | Direct output | PASS |
| Textual JSON Tool Call Parsing | Verified with concise reasoning prompt | Direct JSON generation | PASS |
| Memory Footprint (VRAM) | 5.2 GB Peak | 5.2 GB Peak | PASS (Fits within the available 6GB VRAM on the tested RTX 3050 Laptop GPU) |
| Model Residency Manager | Cold load ~8.6s, warm reload ~165ms | Cold load ~8.0s, warm reload ~240ms | PASS |
| Non-Streaming `/api/generate` | HTTP POST JSON payload | HTTP POST JSON payload | PASS |
| Fallback Code Extraction | Verified via `extract_code_block` | Not required (direct JSON) | PASS |

## 2. Explicit Scope Constraints & Declarations
- **Tool-Calling Mechanism:** HERMES production relies on **textual JSON tool-call generation** through `/api/generate` parsed by `ResponseParser`. It does NOT rely on native Ollama `/api/chat` structured tool calling.
- **Streaming:** Streaming was not required for the validated production execution path and was not used as a Phase-6 readiness dependency.
- **Hardware Residency:** Fits within the available 6GB VRAM on the tested NVIDIA RTX 3050 Laptop GPU (peak measured usage ~5600 MB).
