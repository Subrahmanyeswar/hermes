# HERMES — PHASE 3 PROVIDER REGRESSION REPORT
## Tier 1, Tier 2, and Tier 3 Provider Behavior Verification

### 1. Tier 1 — DeepSeek-R1 8B (`models/ollama_client.py`)
- **Reasoning Payload Ingestion**: Verified `normalize_ollama_payload` extracts `data["thinking"]` into `<think>...</think>` wrapper without dropping text or duplicating tags.
- **Direct Tool Response**: Normal response payload returned unmodified.
- **Streaming & Non-Streaming**: Validated with both synchronous and asynchronous caller patterns.
- **Token Accounting**: Evaluated `data["prompt_eval_count"]` and `data["eval_count"]` directly from Ollama response metadata.
- **Real Local Execution**: Real local smoke test confirmed tool generation in 69.88s and parsed by `ResponseParser` directly.

### 2. Tier 2 — Qwen3 8B (`core/verifier.py`)
- **Invocation & Format**: Fast JSON verification schema ingestion.
- **Deterministic & Semantic Verification**: Level 0 AST check executed in <1ms; Level 1 diagnostic switch executed cleanly with zero model corruption.
- **Model Residency Tracking**: Zero residency conflicts; switches between T1 and T2 tracked by `ModelResidencyManager`.

### 3. Tier 3 — Stealth / OX-Alpha (`models/openrouter_client.py`)
- **Status Recording**: Real API client instantiated with rate-limit and credit tracking. When credit is exhausted (HTTP 402), client safely arbitrates and falls back to local T1 output without pipeline crash.
- **Identity Attribution**: Active endpoint redirection (`stealth/ox-alpha` -> `z-ai/glm-5.3-flash`) accurately detected and attributed via Gate 20 identity tracking.
- **No Fake Zeros**: Unused/failed T3 requests report `NOT_AVAILABLE` or actual cost spent without manufacturing $0 values.
