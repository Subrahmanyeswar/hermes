# HERMES Pre-Benchmark Gate 15.9: Tool Reliability & Model-Output Boundary Audit

**Target:** HERMES Model-Output to Tool-Execution Pipeline  
**Date:** 2026-09-02  
**Purpose:** Map the exact functions, classes, and failure boundaries governing tool calls from raw model generation to execution and verification.

---

## 1. Complete End-to-End Tool Call Lifecycle

```text
1. MODEL RESPONSE
   ├── OllamaClient.generate() [models/ollama_client.py]
   └── OpenRouterClient.generate() [models/openrouter_client.py]
         │
         ▼
2. RESPONSE PARSING
   ├── ResponseParser.parse() [core/response_parser.py]
   │     ├── Strategy 1: _try_direct_parse (JSON standard)
   │     ├── Strategy 2: _try_strip_fences (Markdown code fences)
   │     ├── Strategy 3: _try_extract_json_object (Extract first { ... })
   │     ├── Strategy 4: _try_fix_single_quotes (Python-style dicts)
   │     ├── Strategy 5: _try_reconstruct (Fragment regex reconstruction)
   │     └── Strategy 6: _try_emergency_extraction (Regex fallback)
   └── Outcome: ParseSuccess(tool, parameters, reasoning) OR ParseFailure(reason)
         │
         ▼
3. TOOL VALIDATION & NORMALIZATION
   ├── ToolValidator.process_and_validate() [core/tool_validator.py]
   │     ├── Step 1: ToolValidator.normalize()
   │     │     ├── Parameter alias mapping (file_path -> path, cmd -> command, etc.)
   │     │     ├── Whitespace stripping
   │     │     └── Contextual path extraction (if missing from user prompt)
   │     ├── Step 2: ToolValidator.validate_schema()
   │     │     └── Tool.Input(**normalized_params) Pydantic validation
   │     ├── Step 3: Bounded T1 Model Repair Loop (max_repair_attempts=2)
   │     │     ├── Structured error diagnostic generation
   │     │     ├── Schema property definition injection
   │     │     └── Re-parsing & re-validation
   │     └── Step 4: Security Validation (POST-REPAIR)
   │           ├── ToolValidator.validate_security()
   │           ├── WorkspaceManager.validate_path() [core/workspace.py]
   │           └── tools.security.check_all_gates() [tools/security.py]
   └── Outcome: ToolValidationResult(is_valid, tool_name, normalized_params, validated_input, errors, security_passed)
         │
         ▼
4. TOOL DISPATCH & EXECUTION
   ├── tools.registry.get_tool(tool_name) [tools/registry.py]
   ├── Tool.execute() / Tool.execute_async() [tools/base.py]
   │     ├── ReadFileTool [tools/file_tools.py]
   │     ├── WriteFileTool [tools/file_tools.py]
   │     ├── DeleteFileTool [tools/file_tools.py]
   │     ├── BashExecTool [tools/shell_tools.py]
   │     └── GitTools [tools/git_tools.py]
   └── Outcome: ToolResult(success, output, error, exit_code, duration_seconds)
         │
         ▼
5. VERIFICATION & MISSION COMPLETION
   ├── Tier2Verifier.evaluate() [core/verifier.py]
   ├── VerificationGate.evaluate() [core/verification_gate.py]
   ├── CompletionLedger.record_evidence() [core/completion_ledger.py]
   └── EventBus.publish() [core/event_bus.py] -> TUI / Loguru
```

---

## 2. Component Responsibility & Exception Boundary Audit

| Pipeline Stage | Module / Function | Exception Handling & Boundaries | Fail-Closed Policy |
| :--- | :--- | :--- | :--- |
| **Response Parser** | `core.response_parser.ResponseParser.parse` | Never raises; returns `ParseSuccess` or `ParseFailure` with diagnostics. | Rejects malformed without throwing unhandled exceptions. |
| **Schema Normalization** | `core.tool_validator.ToolValidator.normalize` | Dict type check, alias substitution, fallback to `{}`. | Never raises on wrong types. |
| **Schema Validation** | `core.tool_validator.ToolValidator.validate_schema` | Caught `pydantic.ValidationError` and generic `Exception`; returns `(False, None, errors)`. | Unregistered tools and malformed params return `is_valid=False`. |
| **Repair Subsystem** | `core.tool_validator.ToolValidator.process_and_validate` | Bounded by `max_repair_attempts` (default 2); handles LLM timeout/disconnect exceptions. | Unrepaired calls fail safely; repaired calls MUST re-run schema and security checks. |
| **Security Validation** | `core.tool_validator.ToolValidator.validate_security` | Workspace path containment, forbidden command regexes, null-byte checks wrapped in `try...except`. | Exceptions default to `(False, SECURITY_ERROR)`. |
| **Tool Instantiation** | `tools.registry.get_tool` | Returns `None` if tool unregistered. | Handled via deterministic `UNKNOWN_TOOL` diagnostic. |
| **Tool Execution** | `tools.base.BaseTool.execute` | Base wrapper handles timeouts, IOErrors, OS exceptions; returns `ToolResult(success=False)`. | Execution exceptions do not kill the mission runner. |
| **Event Emission** | `core.event_bus.EventBus.publish` | Isolated subscriber try/except. | Consumer crashes cannot crash publisher. |
| **Completion Ledger** | `core.completion_ledger.CompletionLedger` | Evidence-based gating (`record_evidence`). | False completions without execution evidence are blocked. |

---

## 3. Potential Vulnerability & Fragility Focus Areas for Stress Testing

1. **Empty / Minimal JSON Payloads:**  
   `{}` was previously fixed, but we must verify that `{}` at the model response boundary transitions to `ParseFailure` $\rightarrow$ Repair / Structured Rejection $\rightarrow$ Mission continues cleanly without state corruption.
2. **Untrusted Model Repairs:**  
   If a model repair introduces a path traversal (`../../outside/OUTSIDE_SENTINEL.txt`) or a forbidden shell command (`rm -rf /`), it must be intercepted and denied by Step 4 security validation.
3. **Duplicate Tool Executions & Idempotency:**  
   Model retries must not result in duplicate destructive actions (e.g. double file deletion or duplicate Git commits) without validation.
4. **Wrong Argument Types & Truncated Responses:**  
   Integer/Null/Array types for string paths or commands must fail schema validation cleanly without triggering unhandled `AttributeError` or `TypeError`.
