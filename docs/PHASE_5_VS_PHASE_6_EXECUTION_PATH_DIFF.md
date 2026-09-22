# Phase 5 Preflight vs Phase 6 Benchmark Execution Path Diff
**Comparison:** Preflight Runner vs 80-Task Benchmark Runner  

## 1. Execution Path Differences

| Component | Phase 5 Preflight Harness | Phase 6 Benchmark Runner (Initial) | Repaired Production Path |
|---|---|---|---|
| Prompt Formulation | Custom test prompts with explicit one-shot JSON enforcement | Generic `ContextEngine` assembly without reasoning budget prompt instructions | Unified `ContextEngine` + `HERMES_ROLE` with explicit reasoning bounds |
| Model Token Budget | Fixed `num_predict=1024` with direct JSON prompts | Dynamic `ReasoningBudgetManager` with long prompts triggering excessive `<think>` | Balanced `num_predict` with concise thinking instructions |
| Response Parsing | Direct JSON evaluation | 6 standard strategies (no code block fallback) | 7 strategies including `extract_code_block` fallback |
| Tool Invocation | Simulated & isolated single-turn tool calls | Real orchestrator loop | Real orchestrator loop with verified tool execution |
| Tier 2 Verification | Mocked / targeted unit verification | Full `Tier2Verifier` with `qwen3:8b` | Full `Tier2Verifier` with `qwen3:8b` live |

## 2. Forensic Conclusion
Phase 5 preflight passed because its synthetic test cases provided clear, compact formatting prompts. When Phase 6 ran with full 80-task realistic prompts, the unbounded reasoning monologue of DeepSeek-R1 triggered parser starvation. The surgical repair aligns prompt constraints across all execution paths.
