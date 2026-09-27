# PROVIDER LIFECYCLE 2.x — ADAPTERS, HEALTH & FAULT ISOLATION

## 1. Provider Tiering & Separation
HERMES 2.x uses distinct provider tiers:
- **Tier 1 (Execution)**: Primary agent generation model (default: `nvidia_nim` with `z-ai/glm-5.3-flash`).
- **Tier 2 (Critic)**: Verification, evaluation, and second-opinion model (default: `ollama` with `gpt-oss:120b-cloud`).
- **Tier 3 (Judge)**: Adjudication and final escalation arbiter (default: `ollama` with `nemotron-3-ultra:cloud`).

Each provider is managed as an independent failure domain. Failures in Tier 1 do not alter Tier 2/3 health state, and Ollama connection refused errors are never labeled as NVIDIA NIM errors.

---

## 2. Provider Capabilities Contract
Each provider adapter declares its concrete capabilities via `ProviderCapabilities`:
- `streaming: bool` (default: True)
- `non_streaming_fallback: bool` (True for both NVIDIA and Ollama)
- `server_health_check: bool` (Readiness probes enabled)
- `cancellation_supported: bool` (Immediate socket abort on cancel)
- `resumable_stream: bool` (False; stream restarts with fresh connection)
- `tool_call_streaming: bool` (True for NVIDIA NIM; JSON parsing for Ollama)
- `keep_alive_param: bool` (True for Ollama to force immediate VRAM release via `keep_alive: 0`)
- `requires_api_key: bool` (True for NVIDIA NIM, False for local Ollama)

---

## 3. Circuit Breaker Mechanics
`ProviderHealthState` tracks provider metrics:
- **Failure Threshold**: Default 3 consecutive failures trips circuit from `CLOSED` to `OPEN`.
- **Fast Fail**: While `OPEN`, any request to that provider fails immediately with `PROVIDER_UNAVAILABLE` without network delay.
- **Cooldown & Hysteresis**: After 10s cooldown, circuit enters `HALF_OPEN`. A single probe or request is permitted. If successful for `recovery_threshold` (default 2) times, transitions to `CLOSED`. If probe fails, immediately trips back to `OPEN`.

---

## 4. Bounded Health Probes
Readiness probes (`check_health()`) are wrapped in `bounded_health_probe` with a 2.0s hard timeout. If an endpoint hangs or deadlocks on TCP connection, the probe aborts and reports `False` without blocking callers.
