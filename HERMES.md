# HERMES Project Rules & Architecture Specification

> **Baseline Notice (HERMES 2.x / RC3 Freeze):**  
> This specification reflects the active runtime configuration as of the `v1.0.0-rc3` freeze and `hermes-2.x` development baseline.

---

## 1. Active Architecture & Model Hierarchy (Current / Verified)

HERMES operates a 3-tier model hierarchy with strictly defined routing and residency rules:

- **Tier 1 (Fast / Code Generation & Native Tool Calling):**
  - **Model:** `z-ai/glm-5.3-flash`
  - **Provider:** `nvidia_nim` (OpenAI-compatible REST API)
  - **Endpoint:** `https://integrate.api.nvidia.com/v1`
  - **Streaming:** Enabled (`STREAMING=true`)
  - **Latency Budget:** 300s (configured timeout: 360s)
  - **Residency / Keep-Alive:** 300s (`T1_KEEP_ALIVE=300`)
- **Tier 2 (Heavy / Semantic AST Review & Quality Verification):**
  - **Model:** `gpt-oss:120b-cloud`
  - **Provider:** `ollama` (Local/Cloud proxy)
  - **Endpoint:** `http://localhost:11434`
  - **Latency Budget:** 360s
  - **Residency / Keep-Alive:** 60s (`T2_KEEP_ALIVE=60`)
- **Tier 3 (Arbitration & Escalation):**
  - **Model:** `nemotron-3-ultra:cloud`
  - **Provider:** `ollama` (Local/Cloud proxy)
  - **Endpoint:** `http://localhost:11434`
  - **Latency Budget:** 360s
  - **Residency / Keep-Alive:** 300s

### Configuration Source of Truth
- **Runtime Configuration:** `config/model_config.py` and environment variables (`.env`).
- **Secrets:** API keys (`NVIDIA_API_KEY`, etc.) are sourced strictly from environment variables or `.env`. Never hardcode secrets.

---

## 2. Engineering & Code Standards

- **Python Runtime:** Python 3.10+ (tested on Python 3.10.0 64-bit; compatible with 3.10 and 3.11).
- **Type Annotations:** Type annotations required on all exported public functions and classes.
- **Data Validation:** All tool arguments validated via Pydantic v2 schemas prior to execution.
- **Exception Discipline:** No bare `except:` clauses. Always catch specific exception hierarchies (`HermesError`, `ToolExecutionError`, `OSError`, `ValidationError`).
- **Filesystem & State Integrity:**
  - Workspace boundaries are strictly enforced. All file operations must stay within the configured workspace root.
  - Memory facts are extracted asynchronously and committed only after confirmed tool exit.

---

## 3. Known Baseline Defects & Temporary Constraints (HERMES 2.x Baseline)

The following issues were identified during Prompt 1 forensics and verified in the `hermes-2.x` baseline:

1. **QualityVerifier Keyword Truncation (`agents/quality_verifier.py`):**
   - The verifier filters keywords with `len(kw) > 4`, incorrectly dropping short keywords (e.g., `card`, `form`, `grid`).
2. **TUI Consumer UnboundLocalError (`ui/app.py`):**
   - When consuming `structured_feedback` events, `Path` is referenced before being imported at the module level, terminating the UI consumer thread.
3. **Tool Name Propagation in TUI (`ui/app.py`):**
   - Pipeline stage updates currently drop `tool_name`, displaying `Tool: None` or `unknown_tool`.
4. **Workspace Path Discipline:**
   - Tools must standardize whether projects are generated in the workspace root or inside `generated_projects/<name>`.

---

## 4. Historical Context (Deprecated)

- *Legacy Local-Only Models:* Prior developmental milestones (RC1 / early gates) used local Ollama models (`qwen2.5-coder:7b`, `deepseek-r1:8b`) with `keep_alive:0` to fit within 8GB/12GB consumer VRAM. These are preserved only as historical fallback profiles in `config/model_config.py`.
- *Legacy Config:* `settings.yaml` is obsolete; all current settings reside in `config/model_config.py`.

---

## 5. Future / Planned Enhancements (HERMES 2.x Roadmap)

- Unification of `core/event_bus.py` and `core/mission_runner.py` into a single high-throughput event pipeline.
- Cross-platform path and shell execution abstraction (eliminating Unix-specific commands like `wc -l` in tests).
- Automated reconnect and retry policies for cloud SSE streams.