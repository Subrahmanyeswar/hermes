# HERMES Phase 11 — Reconnaissance and Root-Cause Report

**Target Release:** HERMES v1.0.0-rc1  
**Phase:** Phase 11 — High-End Code Generation, Cross-File Alignment, Architectural Coherence & Quality-Enforced Execution  
**Platform:** Windows 11 / AMD64  
**Runtime:** Python 3.12.0 (`C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`)  
**Date:** 2026-10-13  
**Status:** Stage 11.0 Complete — Ready for Stage 11.1  

---

## 1. Executive Summary

A comprehensive architectural inspection and empirical baseline evaluation of the HERMES generation engine was performed in isolated disposable workspaces. The investigation confirmed that HERMES's current code-generation limitations (cross-file discrepancies, dead links, shallow scaffolds, and brittle execution) do not stem from a single flaw, but from a compound set of identifiable architectural root causes:

1. **Zero-LLM Fast-Path and Template Bypasses:** Low-risk website keywords bypass proper planning and force rigid 3-file templates (`web-basic-v1`), misclassifying rich prompts as zero-model scaffold requests or simple tasks.
2. **Blind Per-File Decomposition & Missing Contracts:** Multi-file requests are decomposed into isolated per-file tasks (`Write index.html`, `Write styles.css`) with zero shared schema (`ImplementationBlueprint`, `InterfaceManifest`).
3. **Context Starvation during Generation Turns:** The agent loop prompts the model with only a truncated workspace skeleton (`skeleton[:600]`) and recent observations, omitting the real contents of previously written files and shared identifier contracts.
4. **Superficial Verification Criteria:** The existing `TechnologyAwareBehavioralVerifier` only validates file existence and crude length thresholds (`len(html) > 50`, `len(css) > 20`), ignoring dead links, mismatched DOM IDs, missing CSS selectors, and non-functional controls.
5. **Model Streaming & Reasoning Token Depletion:** The Tier 1 model (`z-ai/glm-5.3-flash`) allocates substantial tokens to internal `reasoning_content` (100–200+ tokens). Under tight token budgets or aggressive timeouts (`MODEL_FIRST_TOKEN_TIMEOUT=15.0s`), turns abort or emit empty content (`content: null`, `finish_reason: "length"`).

---

## 2. Root-Cause Analysis Table

| Symptom | Hypothesis | Status | Evidence | Consequence |
|---|---|---|---|---|
| **Dead internal links & missing pages** | Multi-page prompts are constrained by `WebsiteFastPathClassifier` to 3 files or generate links without building targets. | **PROVEN** | `core/website_fast_path.py` (lines 187–208) caps targets to `['index.html', 'styles.css', 'app.js']`. Baseline A generated `index.html` and `about.html` with links to `contact.html` and `services.html` that were never created (4 dead link defects). | Broken navigation, 404 targets, and unfulfilled multi-page requirements. |
| **Cross-file ID & class mismatches** | Files are generated independently without a shared `InterfaceManifest` or dependency context injection. | **PROVEN** | `core/mission_planner.py` (lines 860–869) decomposes tasks into independent `Write <file>` tasks. `core/agent_loop/loop.py` (lines 1209, 1262) passes only `skeleton[:600]` and last 4 observations to model. Model has no access to real HTML content when writing CSS/JS. | JavaScript event listeners target non-existent DOM IDs; CSS classes don't match markup. |
| **Premature template bypass of complex landing pages** | `WebsiteFastPathClassifier` keyword heuristics misclassify complex design prompts as zero-model scaffolds. | **PROVEN** | `core/website_fast_path.py` (lines 221–224) checks `custom_indicators`. For Baseline C ("meaningful motion"), "motion" was absent, evaluating `model_required=False`. It rendered a static 20-line boilerplate template (`web-basic-v1`) with 0 model calls. | User requests for polished, animated landing pages receive generic blank skeletons. |
| **First-token stream timeout aborts** | `MODEL_FIRST_TOKEN_TIMEOUT` (15.0s) is too aggressive for reasoning models under load. | **PROVEN** | `config/model_config.py` (line 25), `models/nvidia_client.py` (lines 118, 542). Direct diagnostic proved `z-ai/glm-5.3-flash` spent 173 reasoning tokens taking 41.62s to respond. 15.0s limit caused `NvidiaTimeoutError: NVIDIA NIM first token timed out after 15.4s`. | Legitimate deep model generation is prematurely killed and recorded as an outage/failure. |
| **Empty content on reasoning budget exhaustion** | When `max_tokens` is small, `z-ai/glm-5.3-flash` consumes the entire budget on reasoning tokens, producing `content: null`. | **PROVEN** | `scratch/test_glm_response.py` at `max_tokens=100` resulted in `completion_tokens=100`, `reasoning_tokens=100`, `content=null`, `finish_reason='length'`. Hardcoded `num_ctx=4096` in `loop.py` (line 1298) restricts budget. | Agent receives empty turn response, causing parse failures and consecutive failure escalation. |
| **Superficial behavioral verification false positives** | Verifier checks only trivial file existence and basic character counts, approving non-functional apps. | **PROVEN** | `core/agent_loop/behavioral_verifier.py` (lines 166, 177) only enforces `len(html) >= 50` and `len(css) >= 20`. Lacks DOM ID matching, dead link checks, CSS selector resolution, and responsiveness verification. | Skeletal apps with broken links and unstyled classes pass verification as "COMPLETE". |
| **Exploratory command stalls in AgentLoop** | Models spend turns issuing `bash_exec` / `find` / `list_directory` because current workspace state is not in context. | **PROVEN** | In Baseline A trace, Turns 2 & 3 executed `find . -type f` and `list_directory` because the model was unaware of files written in Turn 1. On Windows, `find` failed, triggering stall detection and circuit breaker trip. | Turns and wall-time budgets are wasted on basic inventory discovery rather than code generation. |
| **Ollama circuit breaker cascade failure** | When T1 encounters repeated exploratory errors, adaptive routing fails over to Ollama which may be offline. | **PROVEN** | Baseline A trace (line 205) triggered `T1 circuit is OPEN_CIRCUIT. Zero-wait failover to T2 (gpt-oss:120b-cloud)` which failed with connection error, cascading to T3, and terminating the mission. | Single provider transient errors collapse the entire pipeline when local Ollama daemon is offline. |

---

## 3. Measured Baseline Results (Stage 11.0)

Executed on 2026-10-13 using `scratch/run_stage0_baselines.py` in isolated temporary workspaces with the existing HERMES runtime and frozen model stack (`z-ai/glm-5.3-flash`):

```
====================================================================================================
Baseline A: Multi-page Informational Website
Prompt: "Build a multi-page informational website with common navigation, shared styling, page-specific content, and working internal links."
----------------------------------------------------------------------------------------------------
- Workspace: C:\Users\SUBBU\AppData\Local\Temp\hermes_baseline_a_3j3upx34
- Complexity: SIMPLE (Misclassified)
- Fast-Path Candidate: True (eligible_simple_website_request) | Model Required: True
- Elapsed Time: 551.55s | Exit Code: 1
- Files Created (3):
  * about.html: 1,557 bytes, 44 lines, sha256: 9bfc3a718b37
  * index.html: 2,091 bytes, 60 lines, sha256: f0b6b3b5768d
  * styles.css: 2,674 bytes, 123 lines, sha256: 46b1c6c92656
- Alignment Defects (4 CRITICAL):
  * Dead link in about.html: 'contact.html' points to missing file 'contact.html'
  * Dead link in index.html: 'contact.html' points to missing file 'contact.html'
  * Dead link in about.html: 'services.html' points to missing file 'services.html'
  * Dead link in index.html: 'services.html' points to missing file 'services.html'
- Behavioral Verifier: FAILED
  * Issues: No JavaScript file found, No interactive controls, Missing event handlers, No dynamic DOM.
----------------------------------------------------------------------------------------------------

Baseline B: Administrative Dashboard Application
Prompt: "Build a realistic administrative dashboard with a data table, filtering/search, forms, modal interactions, state changes, and responsive layout."
----------------------------------------------------------------------------------------------------
- Workspace: C:\Users\SUBBU\AppData\Local\Temp\hermes_baseline_b_a8mvpxfk
- Complexity: SIMPLE (Misclassified — should be COMPLEX/MEDIUM)
- Fast-Path Candidate: False (no_website_intent_detected)
- Elapsed Time: 24.69s | Exit Code: 1
- Files Created: 0 files in workspace root
- Behavioral Verifier: FAILED (No files created)
----------------------------------------------------------------------------------------------------

Baseline C: Animated Landing Page
Prompt: "Build a polished landing page with structured sections, consistent typography, visual depth, responsive styling, and meaningful motion."
----------------------------------------------------------------------------------------------------
- Workspace: C:\Users\SUBBU\AppData\Local\Temp\hermes_baseline_c_w2gka38f
- Complexity: SIMPLE (Misclassified)
- Fast-Path Candidate: True (eligible_simple_website_request) | Model Required: False (Keyword defect)
- Elapsed Time: 24.05s | Exit Code: 1
- Files Created: 0 files in workspace root
- Behavioral Verifier: FAILED (No files created)
====================================================================================================
```

---

## 4. Phase 9 Performance Audit Reconciliation

Inspection of Phase 9 performance optimizations (`core/checkpoints/file_snapshot.py`, `core/persistence/database.py`, `core/event_bus.py`, `core/server/checks_service.py`) confirms:

- **No Degraded Persisted Guarantees:** Phase 9 micro-batching of journal events and CAS deduplication in `BlobStore` did **not** introduce generation quality regressions.
- **Identified Latency Bottlenecks:** The primary generation delays are model reasoning latency (40–70s per turn on `z-ai/glm-5.3-flash`), exploratory command turns (`find`, `list_directory`), and repeated stalls.
- **Safety Invariant Preserved:** Path containment, session databases, checkpoint snapshots, and GUI event subscriptions remain 100% compliant with Phases 0–10.

---

## 5. Implementation Roadmap Based on Evidence

To permanently eliminate Problem A (cross-file incoherence) and Problem B (toy-level code generation), Phase 11 will be executed in the following strict order:

1. **Stage 11.1 — Versioned Contracts (`core/contracts/`):**
   - Implement `ImplementationBlueprint` (target files, component roles, routing, data models, state schema).
   - Implement `InterfaceManifest` (DOM IDs, classes, exports/imports, routes, storage keys, public functions).
   - Implement `QualityRubric` (semantic dimensions: responsive design, visual depth, accessibility, anti-placeholder rules).
   - Wire contract serialization and schema migrations into SQLite and Checkpoint serializers.

2. **Stage 11.2 & 11.3 — Alignment Verification Engine (`core/alignment_verifier.py`):**
   - Extend verifier with AST and DOM/regex parsing for HTML, CSS, and JS cross-references.
   - Detect dead internal links, missing CSS classes/IDs, unresolved DOM references in JS, unbundled `import`/`export` mismatches.
   - Verify against negative fixtures (deliberately broken test cases).

3. **Stage 11.4 & 11.5 — Context Injection, Budgets & Truncation Handling:**
   - In `AgentLoop`, inject Blueprint, Manifest, and real contents of dependency files into model prompts.
   - Expand `num_ctx` and per-turn generation budgets to prevent reasoning exhaustion.
   - Calibrate `MODEL_FIRST_TOKEN_TIMEOUT` to accommodate legitimate thinking time without stalling.
   - Implement syntax-aware truncation detection and repair before tool commit.

4. **Stage 11.6 — Bounded Repair Loop:**
   - Implement targeted patch/repair loop (max 3 bounded attempts per failure class) passing exact verification issues and full sibling file context.

5. **Stage 11.7 & 11.8 — GUI Integration & Backward Compatibility:**
   - Connect Blueprint and Alignment verifier checks to GUI `Changes`, `Checks`, and `Outcome` panels.
   - Preserve 100% backwards compatibility with pause, resume, stop, and recovery protocols.

6. **Stage 11.9 & 11.10 — Golden Projects (G1–G8) & Final Acceptance Gate:**
   - Validate all golden projects in isolated temporary workspaces.
   - Verify 150-test canonical regression suite and GUI production build.
