# HERMES Architecture & Capability Parity Analysis

**Status:** Technical Baseline Assessment (`hermes-2.x`)  
**Evaluation Date:** 2026-09-25  
**Taxonomy Classifications:**
- `PRESENT IN HERMES` — Fully implemented and verified in current codebase.
- `PARTIAL / DIFFERENT IMPLEMENTATION` — Present with known architectural variations, gaps, or limitations.
- `NOT YET IMPLEMENTED` — Planned or standard in other systems, but not currently available in Hermes.
- `UNKNOWN / NOT VERIFIED` — Insufficient empirical data to determine parity status.

---

## 1. Capability Matrix

| Architecture Dimension | Hermes Status | Hermes Implementation | Industry Reference Systems (Claude Code / OpenHands / Cursor) |
| :--- | :--- | :--- | :--- |
| **Multi-Tier Model Routing** | `PRESENT IN HERMES` | Tri-tier architecture (T1 fast generation via NVIDIA NIM, T2 semantic verification via Ollama Cloud, T3 arbitration). | Most reference systems use a single primary frontier model (e.g. Claude 3.7 Sonnet) with optional fast model routing for simple sub-tasks. |
| **Tool Execution Gating & Security** | `PRESENT IN HERMES` | Stage 1 & Stage 5 parameter schema checks via Pydantic v2, path traversal guards, and command blocklists. | Standard bash permission dialogs (Claude Code) or Docker sandbox isolation containers (OpenHands). |
| **Interactive Terminal UI (TUI)** | `PARTIAL / DIFFERENT IMPLEMENTATION` | Full Textual TUI (`HermesApp`) with ChatPanel, ToolMatrix, and StatusBar. *Known baseline defect:* UI event consumer thread can crash on unhandled `UnboundLocalError` (`ui/app.py`). | Claude Code uses a streamlined CLI with direct stream rendering; Cursor uses a native desktop IDE UI; OpenHands uses a web dashboard. |
| **Tool-Level Tracing & Telemetry** | `PARTIAL / DIFFERENT IMPLEMENTATION` | Audit logger records structured traces to disk (`artifacts/performance/traces/`). *Known baseline defect:* UI stage updates drop `tool_name` parameter (`Tool: None`). | Reference agents provide fine-grained stdout stream reporting or IDE notification feeds for each invoked tool. |
| **Deterministic & Semantic Verification Gate** | `PRESENT IN HERMES` | 12-stage pipeline with Level 0 syntax/AST checks, Level 1 pytest execution, and Level 2 T2 semantic review. *Known defect:* `len(kw) > 4` keyword drop in `QualityVerifier`. | Reference systems rely primarily on tool return codes and direct compiler/linter error feedback loops rather than standalone multi-tier verification gates. |
| **Autonomous Failure Recovery** | `PRESENT IN HERMES` | Configured retry policies, error repair loops, and disagreement routing (ACCEPT / REPAIR / ESCALATE). | Common pattern across autonomous agents: feed stderr back into the next agent prompt iteration until tests pass or iteration limit is reached. |
| **Long-Term Memory Synthesis** | `PRESENT IN HERMES` | Background asynchronous memory extraction committing summarized facts to `MEMORY.md`. | Reference systems employ CLAUDE.md / project-specific memory markdown files, vector indexing, or session summaries. |
| **Cross-Platform Portability** | `PARTIAL / DIFFERENT IMPLEMENTATION` | Core engine operates on Windows/macOS/Linux. *Known baseline defect:* Several tests and shell operations assume Unix utilities (e.g., `wc -l`). | Production agents generally abstract OS commands using language-native APIs (e.g., Python `os`/`pathlib` or Node.js runtime). |
| **Sub-agent Orchestration** | `NOT YET IMPLEMENTED` | Tasks are decomposed linearly or into sequential stages; concurrent sub-agent swarms are not currently active in core loop. | OpenHands and advanced agent architectures support multi-agent collaboration and delegated subagents. |
| **Dual Event System Unification** | `PARTIAL / DIFFERENT IMPLEMENTATION` | Event telemetry exists in two parallel implementations (`core/event_bus.py` vs `core/mission_runner.py`). | Production systems generally route all telemetry through a unified single pub/sub bus. |

---

## 2. Empirical Strengths & Verified Gaps

### Measured Strengths
1. **Separation of Concerns:** Distinct separation between generation (T1), review (T2), and arbitration (T3) provides defense-in-depth against silent code regressions.
2. **Local Sandbox Isolation:** Strict path checks prevent operations outside the configured workspace root.
3. **Structured Verification:** AST syntax checking and unit test execution occur automatically as part of the verification lifecycle.

### Verified Baseline Gaps (To Address in HERMES 2.x)
1. **TUI Consumer Resilience:** Ensure `_consume_mission_events` handles missing or out-of-order events without crashing the display thread.
2. **Verification Accuracy:** Correct keyword extraction in `QualityVerifier` to prevent false-negative evaluations on short tokens.
3. **Windows Shell Portability:** Replace hardcoded Unix shell pipelines with cross-platform Python implementations.
4. **Tool Identity Display:** Preserve and render active tool names throughout the pipeline progress lifecycle.
