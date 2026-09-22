# HERMES Tool Validation Policy
=================================

**Date:** September 1, 2026  
**Status:** ENFORCED  

---

## 1. Core Validation Principle

> **NEVER TRUST MODEL-GENERATED TOOL ARGUMENTS.**  
> Every tool call produced by any LLM (Tier 1, Tier 2, or Tier 3) is untrusted input and must pass through deterministic normalization, schema validation, and security verification before reaching `tool.execute()`.

---

## 2. Order of Pipeline Execution

```
MODEL GENERATED CALL
        ↓
1. Deterministic Normalization (Alias resolution: file_path ➔ path, whitespace trim, default injection)
        ↓
2. Schema & Argument Validation (Pydantic type checks, required argument presence, null/empty checks)
        ↓
3. Repair Engine (Deterministic derivation first; T1 structured retry with L1 budget if needed)
        ↓
4. Re-Validation of Repaired Parameters
        ↓
5. Security Gate (Workspace boundary check, path traversal ../ check, command blacklist)
        ↓
6. Tool Execution (Only validated parameters reach tool.execute)
```

---

## 3. Mandatory Invariants

1. **Zero Silent Execution of Malformed Arguments:**  
   An empty parameter dictionary `{}` must **never** reach a tool requiring parameters (e.g. `write_file`, `read_file`). It must trigger schema validation failure and structured repair.
2. **Deterministic Fast Path:**  
   Valid tool calls must evaluate in $< 0.1	ext{ ms}$ (measured at $0.0031	ext{ ms}$) without invoking secondary LLM validation.
3. **No Guessing of Semantic Values:**  
   Deterministic repair may only normalize aliases or fill explicit schema defaults. Missing content or code logic must never be fabricated.
4. **Security Revalidation:**  
   Any repaired parameter dictionary must undergo the exact same security inspection as original calls.
