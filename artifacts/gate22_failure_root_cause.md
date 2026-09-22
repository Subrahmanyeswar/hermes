# HERMES — GATE 22 FAILURE ROOT CAUSE ANALYSIS

## Summary of 22 Failures

| Group | Count | Affected Components | Root Cause |
|---|---|---|---|
| **Group A: Tool Registry & Validator Normalization** | 13 | `tools/registry.py`, `core/tool_validator.py`, `core/orchestrator.py` | Historical tests and model outputs used `list_dir` alias, whereas canonical tool name is `list_directory`. ToolValidator did not resolve `list_dir` alias before validation, and `tools.registry` did not auto-populate default tool registrations if imported standalone. |
| **Group B: Tool Reliability Test Schemas** | 5 | `tests/test_tool_reliability.py`, `core/tool_validator.py` | Standalone validator tests executed without default tool modules imported into registry. |
| **Group C: Response Contract & Windows Encoding** | 4 | `models/provider.py`, `core/response_parser.py`, `core/prompt_builder.py`, `tests/test_phase3_complete.py` | 1) `NormalizedModelResponse` lacked string equality and string manipulation delegate methods (`strip`, `split`, `__eq__`), causing `.strip()` failures on response objects. 2) Prompt builder V1 omitted the JSON format template block expected by test assertion. 3) Windows `cp1252` encoding issue when printing `\u2713` in Textual test harness. |

---

## Minimal Fix Strategy

1. **`models/provider.py`**:
   - Add `__eq__`, `strip`, `split`, `startswith`, `endswith`, `lower`, `upper`, and string indexing to `NormalizedModelResponse` so callers expecting either `NormalizedModelResponse` or `str` operate seamlessly.
2. **`core/response_parser.py`**:
   - Safely unwrap `.text` if `response` is an instance of `NormalizedModelResponse` or has `.text`.
3. **`tools/registry.py` & `core/tool_validator.py`**:
   - Add `TOOL_ALIASES = {"list_dir": "list_directory"}` in `tools/registry.py` and ensure `get_tool` resolves aliases to the canonical tool class.
   - Ensure default tool packages are registered upon tool lookup.
4. **`core/prompt_builder.py`**:
   - Include the response format JSON block in `HERMES_ROLE` so V1 prompt contains the canonical tool schema.
5. **`tests/test_phase3_complete.py`**:
   - Replace non-cp1252 character `\u2713` with ASCII `[PASS]` in test 10 print statement.
