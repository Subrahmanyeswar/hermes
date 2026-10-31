# HERMES — GREENFIELD PROJECT CLASSIFICATION & PREFLIGHT VALIDATION FIX REPORT

**Date:** 2026-10-30  
**Repository:** `C:\Users\SUBBU\Downloads\hermes`  
**Python Environment:** `C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe` (Python 3.12.0)  
**Backend:** `http://127.0.0.1:8765`  
**Status:** **REPAIRED & VERIFIED**

---

## 1. Executive Summary

During execution of the FocusFlow web application build mission (`m_38517a56`) in an empty workspace (`C:\Users\SUBBU\Downloads\testing 2`), HERMES immediately failed during preflight validation with:
```
failure_code: EMPTY_WORKSPACE_EXISTING_APPLICATION
error: Workspace 'C:\Users\SUBBU\Downloads\testing 2' contains 0 existing application files, but the mission requested modifying an existing application...
```

The user requested:
> *"Build a polished, fully functional, responsive web application called FocusFlow."*

This was an explicit request for a **new application created from scratch** in an empty workspace. However, the preflight classifier categorized it as `CONTINUATION_OR_MODIFICATION` and aborted execution.

We forensically investigated the classifier, identified two critical flaws, implemented the required three-way mission classification (`GREENFIELD_CREATE`, `EXISTING_PROJECT_MODIFY`, `EXISTING_PROJECT_EXTEND`), added backward-compatibility aliases, created a comprehensive 15-test regression suite (`tests/test_greenfield_classification.py`), and verified that both the exact verification prompt and the full FocusFlow mission prompt evaluate to `GREENFIELD_CREATE` and pass preflight with `allowed=True` in an empty workspace.

---

## 2. Forensic Diagnosis & Root Cause Analysis

### Forensic Inspection of Mission `m_38517a56`
Inspection of the persisted mission record in `C:\Users\SUBBU\Downloads\testing 2\.artifacts\missions\m_38517a56\progress.json` and execution trace revealed:

1. **Root Cause 1: Overly Broad Continuation Pattern Triggered by In-App CRUD Domain Features**  
   In `core/agent_loop/preflight.py`, the continuation pattern was:
   ```python
   continuation_patterns = [
       ...
       r"\b(?:modify|update|refactor|fix|extend|patch|change|edit)\s+(?:the\s+)?existing\b",
       ...
   ]
   ```
   In the user prompt, section 3 ("Task management functionality") specified:
   > *"Users must be able to edit existing tasks."*  
   > *"Test 5 — Edit and delete: Edit an existing task."*

   Because the pattern matched any `edit existing <word>` without anchoring to a codebase/project noun (`project|app|website|codebase|repo`), the in-app task management requirement (`edit existing tasks`) caused HERMES to falsely conclude the entire mission was intended to modify an existing codebase!

2. **Root Cause 2: Narrow Greenfield Patterns Rejected Natural Adjectives**  
   The previous greenfield patterns required specific hardcoded adjectives immediately after the verb:
   ```python
   r"\bbuild\s+(?:a|an)\s+(?:complete|interactive|entire|fully-featured|responsive|new)\b.*?\b(?:website|app|application|game|tool|dashboard|portal)\b"
   ```
   The prompt began:
   > *"Build a polished, fully functional, responsive web application called FocusFlow."*

   Because "polished" was not in the hardcoded adjective list, the pattern failed to match and fell through to the flawed `edit existing` continuation pattern.

3. **Root Cause 3: Inadequate Negative/Preservation Filtering on Single Lines**  
   When prompts contained negative assertions like:
   > *"Create a brand-new responsive web application called FocusFlow from scratch. Create index.html, style.css and main.js. No existing application is being modified."*

   The phrase `"No existing application is being modified"` needed deterministic neutralization so it could never be misinterpreted as a request to modify an existing application.

---

## 3. Architecture & Implementation of the Fix

### File Modified
- `core/agent_loop/preflight.py` (backed up to `core/agent_loop/preflight.py.bak_20261030`)

### Key Enhancements

1. **Expanded Intent Enum with Backward Compatibility:**
   ```python
   class MissionIntent(str, Enum):
       GREENFIELD_CREATE = "GREENFIELD_CREATE"
       EXISTING_PROJECT_MODIFY = "EXISTING_PROJECT_MODIFY"
       EXISTING_PROJECT_EXTEND = "EXISTING_PROJECT_EXTEND"
       INSPECTION = "INSPECTION"
       VERIFICATION_ONLY = "VERIFICATION_ONLY"

       # Backward-compatible aliases
       NEW_PROJECT = "GREENFIELD_CREATE"
       CONTINUATION_OR_MODIFICATION = "EXISTING_PROJECT_MODIFY"
   ```

2. **Anchored Codebase Target Nouns:**
   Codebase modifications and extensions now strictly require explicit codebase nouns (`project|app|application|website|site|codebase|repo|repository|code|system|solution|software`), preventing in-app domain objects (`tasks`, `todos`, `records`, `data`, `entries`, `notes`, `users`) from triggering codebase modification logic.

3. **Inline Neutralization of Preservation Clauses:**
   ```python
   preservation_patterns = [
       r"\bdo\s+not\s+(?:overwrite|modify|change|delete|touch)\b.*?\bexisting\b.*?(?=[.;\n]|$)",
       r"\bif\s+(?:any\s+)?existing\b.*?\b(?:do\s+not|report|preserve|skip|wait|halt)\b.*?(?=[.;\n]|$)",
       r"\bpreserve\s+(?:the\s+)?(?:existing|working|original|all)\b.*?(?=[.;\n]|$)",
       r"\bwithout\s+(?:overwriting|modifying|changing|deleting)\s+(?:the\s+)?existing\b.*?(?=[.;\n]|$)",
       r"\bdo\s+not\s+modify\s+(?:hermes|other\s+projects|source\s+repository|rocket\s+application|existing\s+application)\b.*?(?=[.;\n]|$)",
       r"\bno\s+existing\s+(?:application|app|project|website|codebase|repo)\s+(?:is\s+being\s+)?(?:modified|changed|updated|touched)\b.*?(?=[.;\n]|$)",
       r"\bnot\s+modifying\s+(?:any\s+)?(?:existing\s+)?(?:application|app|project|website|codebase)\b.*?(?=[.;\n]|$)",
   ]
   ```

4. **Expanded Greenfield Matching:**
   Accepts any descriptive adjectives (`polished`, `clean`, `modern`, `minimal`, `responsive`, `multi-page`, `complete`, etc.) and detects explicit target file declarations (`create index.html, style.css and main.js`).

5. **Distinct `EXISTING_PROJECT_EXTEND` vs `EXISTING_PROJECT_MODIFY`:**
   - **`EXISTING_PROJECT_EXTEND`**: Matches `"add a feature to the existing project"`, `"integrate a new chart into the current project"`.
   - **`EXISTING_PROJECT_MODIFY`**: Matches `"modify my existing website"`, `"fix the bug in the existing application"`, `"update an existing React app"`.

6. **Preflight Gating Rules:**
   - **`GREENFIELD_CREATE`**: `allowed = True` when workspace has 0 files (empty workspace is valid).
   - **`EXISTING_PROJECT_MODIFY` / `EXISTING_PROJECT_EXTEND`**: `allowed = False` with `EMPTY_WORKSPACE_EXISTING_APPLICATION` when workspace has 0 files; `allowed = True` when application files exist.

---

## 4. Test Suite & Validation Evidence

### Regression Test Suite: `tests/test_greenfield_classification.py`
We implemented a dedicated test file covering all 8 specification cases, preflight gating, complex in-app domain text, and enum compatibility.

**Test Run Results:**
```
============================= test session starts =============================
platform win32 -- Python 3.12.0, pytest-9.1.1 -- C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe
collected 15 items

tests/test_greenfield_classification.py::test_case_1_build_polished_responsive_web_app PASSED [  6%]
tests/test_greenfield_classification.py::test_case_2_create_brand_new_from_scratch_with_negative_clause PASSED [ 13%]
tests/test_greenfield_classification.py::test_case_3_develop_new_website_in_empty_workspace PASSED [ 20%]
tests/test_case_4_create_clean_dashboard PASSED                                [ 26%]
tests/test_case_5_modify_existing_website PASSED                               [ 33%]
tests/test_case_6_fix_bug_in_existing_application PASSED                       [ 40%]
tests/test_case_7_add_feature_to_existing_project PASSED                       [ 46%]
tests/test_case_8_integrate_new_chart_into_current_project PASSED              [ 53%]
tests/test_greenfield_accepted_in_empty_workspace PASSED                       [ 60%]
tests/test_modify_rejected_in_empty_workspace PASSED                           [ 66%]
tests/test_extend_rejected_in_empty_workspace PASSED                           [ 73%]
tests/test_modify_accepted_in_non_empty_workspace PASSED                       [ 80%]
tests/test_extend_accepted_in_non_empty_workspace PASSED                       [ 86%]
tests/test_full_focusflow_prompt_with_in_app_edit_existing_tasks PASSED        [ 93%]
tests/test_mission_intent_enum_backward_compatibility PASSED                  [100%]

============================= 15 passed in 1.00s ==============================
```

### Preflight Suite Regression Check (`tests/test_write_file_preflight_and_planner_hotfix.py`):
```
tests/test_1_new_project_in_empty_workspace_accepted PASSED [ 16%]
tests/test_2_continuation_of_existing_project_with_files_accepted PASSED [ 33%]
tests/test_3_continuation_requiring_missing_files_rejected PASSED [ 50%]
tests/test_4_explicit_target_path_mismatch_rejected PASSED [ 66%]
tests/test_5_new_project_mentioning_preservation_classified_as_new PASSED [ 83%]
tests/test_6_workspace_files_unchanged_when_mission_rejected PASSED [100%]
====================== 6 passed in 0.99s =======================
```

---

## 5. Live Verification Against Empty Workspace (`C:\Users\SUBBU\Downloads\testing 2`)

We verified both test prompts directly against the actual empty workspace `C:\Users\SUBBU\Downloads\testing 2`:

### Test 1: Specified Verification Prompt
**Prompt:**
> `"Create a brand-new responsive web application called FocusFlow from scratch. Create index.html, style.css and main.js. No existing application is being modified."`

**Output:**
```
Intent: MissionIntent.GREENFIELD_CREATE
Reason: explicit_greenfield:\b(?:from\s+scratch|greenfield|brand-new|brand\s+new)\b
Allowed: True
Failure Code: None
App Files Count: 0
```

### Test 2: Actual Full FocusFlow Mission Prompt (`m_38517a56`)
**Prompt:** (1,450-word complete prompt containing "Users must be able to edit existing tasks" and "Do not modify the existing rocket application")

**Output:**
```
Intent: MissionIntent.GREENFIELD_CREATE
Reason: explicit_greenfield:\bcreate\s+(?:an?\s+isolated\s+project|index\.html|style\.css|main\.js|package\.json)\b
Allowed: True
Failure Code: None
App Files Count: 0
```

Both prompts evaluate deterministically to `MissionIntent.GREENFIELD_CREATE` and pass preflight validation with `allowed=True`.

---

## 6. Current Server Status

- Clean backend uvicorn server restarted and running on PID 26984 (`http://127.0.0.1:8765`).
- In accordance with non-negotiable instructions, the full FocusFlow building mission was **NOT** launched. The system is stopped and fully primed for the user to execute the mission.
