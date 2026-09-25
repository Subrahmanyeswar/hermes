# HERMES — Hierarchical Execution and Reasoning with Memory-Evolving Supervision

**Release: `v1.0.0-rc2`**

[![Version](https://img.shields.io/badge/version-v1.0.0--rc2-blue.svg)](https://github.com/Subrahmanyeswar/hermes)
[![Status](https://img.shields.io/badge/status-frozen-success.svg)](https://github.com/Subrahmanyeswar/hermes)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**HERMES** is a production-grade, local-first autonomous software engineering runtime. It features a tri-tier model architecture, progressive multi-level verification, deterministic AST and runtime contract checking, background asynchronous memory synthesis, and workspace sandbox isolation.

---

## 1. Model Stack Architecture

HERMES enforces a strict separation of concerns across three specialized model tiers:

| Tier | Role | Provider | Model ID | Primary Responsibility |
|:---:|:---:|:---:|:---:|:---|
| **Tier 1** | **Generation & Tool Calling** | NVIDIA NIM | `z-ai/glm-5.3-flash` | Fast reasoning, planning, code generation, and native tool calling |
| **Tier 2** | **Verification Gate** | Ollama Cloud | `gpt-oss:120b-cloud` | Semantic AST code review, risk evaluation, and quality verification |
| **Tier 3** | **Arbitration & Escalation** | Ollama Cloud | `nemotron-3-ultra:cloud` | Disagreement arbitration, architectural escalation, and high-risk review |

---

## 2. 12-Stage Execution Lifecycle

HERMES runs every user task through a deterministic 12-stage pipeline:

```
[User Request]
       │
       ▼
 Stage 1: Security & Sanitization ────── (Block traversal, destructive commands, credential exfiltration)
       │
 Stage 2: Planning & DAG Generation ─── (Decompose request, assess complexity, register task in KAIROS)
       │
 Stage 3: Skill & Context Assembly ──── (Load project memories from MEMORY.md, match engineering skills)
       │
 Stage 4: T1 Generation & Reasoning ─── (NVIDIA NIM SSE streaming, task-aware token budget, tool call synthesis)
       │
 Stage 5: Tool Validation & Security ── (ToolValidator, parameter schema check, workspace boundary lock)
       │
 Stage 6: Tool Execution ────────────── (Atomic filesystem operations, command execution, sandbox isolation)
       │
 Stage 7: Progressive Verification ──── (Level 0 Deterministic -> Level 1 AST/pytest -> Level 2 T2 Semantic)
       │
 Stage 8: Disagreement Routing ──────── (Calibrated threshold routing: ACCEPT, REPAIR, or ESCALATE)
       │
 Stage 9: Tier 3 Arbitration ────────── (Nemotron-3-ultra resolves disagreements or approves high-risk actions)
       │
 Stage 10: Post-Plan Continuation ───── (Mandatory artifact creation check; tool surface isolation for repairs)
       │
 Stage 11: Memory Evolution ─────────── (Non-blocking background extraction of project facts to MEMORY.md)
       │
 Stage 12: Mission Completion Gate ──── (Physical disk artifact verification, test pass check, report synthesis)
       │
       ▼
 [Final Output]
```

---

## 3. Installation Guide

### Prerequisites
- **Python**: 3.10 or 3.11 (Windows, Linux, or macOS)
- **Git**: Installed and available on system `PATH`
- **Ollama**: Installed and running (`ollama serve`) on `http://127.0.0.1:11434`
- **NVIDIA NIM API Key**: Free or commercial key from [NVIDIA build](https://build.nvidia.com)

### Quick Start
```bash
# 1. Clone the repository
git clone https://github.com/Subrahmanyeswar/hermes.git
cd hermes

# 2. Create and activate a clean virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# 3. Install production dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and insert your NVIDIA_API_KEY
```

---

## 4. Configuration Reference

All settings can be configured via environment variables or inside the `.env` file:

### Core Provider Settings
| Variable | Default | Description |
|:---|:---|:---|
| `NVIDIA_API_KEY` | *(Required)* | NVIDIA NIM API Bearer token for Tier 1 inference |
| `TIER1_PROVIDER` | `nvidia_nim` | Provider for primary code generation |
| `TIER1_MODEL` | `z-ai/glm-5.3-flash` | Tier 1 reasoning model identifier |
| `TIER1_BASE_URL` | `https://integrate.api.nvidia.com/v1` | NVIDIA NIM OpenAI-compatible endpoint |
| `TIER2_PROVIDER` | `ollama` | Provider for semantic verification |
| `TIER2_MODEL` | `gpt-oss:120b-cloud` | Tier 2 verification model |
| `TIER3_PROVIDER` | `ollama` | Provider for architectural arbitration |
| `TIER3_MODEL` | `nemotron-3-ultra:cloud` | Tier 3 escalation and arbitration model |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local Ollama gateway address |

### Timeouts & Buffers
| Variable | Default | Description |
|:---|:---|:---|
| `MODEL_TIMEOUT_SECONDS` | `360` | Hard timeout (seconds) for streaming cloud model calls |
| `VERIFICATION_TIMEOUT_SECONDS` | `30` | Timeout for local verification checks and test execution |
| `MEMORY_EXTRACTION_TIMEOUT_SECONDS` | `60` | Timeout for background memory summarization jobs |
| `MODEL_KEEP_ALIVE` | `300s` | Model residency keep-alive duration in Ollama |

---

## 5. CLI Usage & Operations

HERMES exposes a unified Typer CLI via `main.py`:

```bash
# Display version and model freeze status
python main.py version

# Perform full system and provider diagnostics
python main.py diagnostics

# Display active runtime configuration and loaded skills
python main.py info

# Run a single task through the full 12-stage pipeline
python main.py test-pipeline "Create a Flask healthcheck server in generated_projects/app.py"

# Start the interactive terminal conversation loop
python main.py run --mode auto

# Launch the full Textual TUI interface
python main.py ui

# Search structured session logs and execution traces
python main.py logs "write_file"
python main.py trace <trace_id>
```

---

## 6. Workspace Safety & Sandbox Isolation

HERMES is designed to operate safely inside local codebases:
1. **Workspace Root Lock**: The active workspace directory is locked upon startup. File read, write, and command execution operations are restricted to paths strictly beneath the workspace root.
2. **Path Traversal Prevention**: Absolute path escape attempts (e.g. `../../etc/passwd` or `C:\Windows\System32`) are rejected at Stage 1 before model invocation.
3. **Protected Credentials Shield**: Direct access to `.env`, `~/.ssh`, `~/.aws`, and private keys is permanently blocked.
4. **Dangerous Command Filter**: High-risk shell commands (e.g. `rm -rf /`, `:(){ :|:& };:`, `LD_PRELOAD`, `crontab`, `mkfs`) are intercepted by security gates and rejected.

---

## 7. Performance & Latency Characteristics

### Local Runtime Overhead
HERMES internal local orchestration overhead (AST parsing, intent classification, memory extraction queueing, prompt construction, and routing) is measured at:
- **Local Engine Overhead**: **~67 ms** per pipeline execution.

### Remote Cloud Model Latency
*Note: Remote inference latency depends on network transit and NVIDIA NIM / Ollama Cloud queueing.*
- **Tier 1 (NVIDIA NIM GLM-5.3-flash)**: TTFT typically ~30s–50s under standard load. Total generation duration scales with output size (~60s to ~240s for large multi-kilobyte files).
- **Tier 2 (Ollama Cloud GPT-OSS-120B)**: Latency typically ~3.5s–5.5s per verification call.
- **Tier 3 (Ollama Cloud Nemotron-3-Ultra)**: Latency typically ~8s–15s per arbitration call.

---

## 8. Verification & Qualification Evidence

### Qualification Matrix (100% Live Inference)
- **10/10 Missions Passed (100%)**
- **24 Live Cloud Model Invocations** (0 mocks, 0 synthetic responses)
- Documented in `artifacts/live_cloud_qualification_results.json`

### Unit & Regression Matrix
- **Core Unit Test Suite**: 48/48 passed
- **Security & Sandbox Isolation**: 68/68 passed
- **TUI Component & Interaction Suite**: 40/40 passed
- **Failure Recovery & Chaos Suite**: 59/59 passed
- **Closure Regression Suite**: 6/6 passed

---

## 9. License

HERMES is open-source software licensed under the [MIT License](LICENSE).