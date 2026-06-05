# Hermes Behavior Parity Analysis

This report compares Hermes runtime behaviour with four reference agents **Claude Code**, **Codex**, **Cursor Agent**, and **OpenHands** across key dimensions.

| Dimension | Hermes | Claude Code | Codex | Cursor Agent | OpenHands |
|-----------|--------|-------------|-------|--------------|-----------|
| **Planning strategy** | Uses a structured multi‑step plan with explicit Pydantic schemas, prompt‑driven decomposition, and automatic verification after each step. | Generates single‑prompt plans, limited decomposition, no formal schema enforcement. | Relies on single‑shot prompts, minimal planning, no explicit verification. | Interactive, user‑driven planning with UI assistance; less automated verification. | Hybrid approach; uses planner modules but fewer formal checks than Hermes. |
| **Execution visibility** | Real‑time UI panels (StatusBar, ToolTrace, TaskQueue, MemoryView) that reflect backend events; each tool emits state updates. | Console‑only logs; limited UI feedback. | Minimal console output; no structured UI. | UI shows task list but lacks granular tool‑level tracing. | Provides a web dashboard with basic logging, but missing fine‑grained tool traces. |
| **Task decomposition** | Automatic function‑per‑prompt decomposition; each logical unit is a separate prompt with its own test. | Coarse‑grained tasks, often a single prompt per feature. | Single prompts for larger tasks. | User manually splits tasks; no automatic decomposition. | Uses modular executors but not as fine‑grained as Hermes. |
| **Tool execution handling** | Centralised `BaseTool` registry, permission gating, async execution with explicit waiting, automatic retries. | Direct shell commands, no permission gating. | Direct API calls, limited error handling. | UI‑triggered commands, manual error handling. | Uses tool wrappers with basic retry, but lacks permission model. |
| **Verification mechanisms** | Tier‑2 and Tier‑3 verifiers with test assertions, JSON schema validation, and result comparison. | No automated verification; relies on user inspection. | Limited unit tests, no runtime verification. | Manual verification by the user. | Provides some test harnesses, but not integrated into runtime. |
| **Failure handling** | Structured exception capture, UI alerts, automatic retry policies, graceful degradation, and detailed error reporting. | Crashes on unhandled exceptions, minimal reporting. | Throws exceptions, limited traceback. | Shows generic error dialogs; no retry logic. | Logs errors; occasional graceful fallback, but lacks UI alerts. |

## Summary & Recommendations

* **Strengths** – Hermes excels in structured planning, fine‑grained UI visibility, and robust verification/failure handling.
* **Opportunities** – Improve parity with Claude Code and Codex in terms of raw code generation speed, and adopt some of Cursor Agent’s intuitive UI shortcuts for task creation.
* **Next steps** – Add optional performance metrics (latency, token usage) and expand the Dashboard to visualize them alongside existing panels.
