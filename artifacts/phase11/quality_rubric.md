# HERMES Phase 11 — Quality Rubric and Completeness Gate Specification

**Release:** HERMES v1.0.0-rc1  
**Phase:** 11 — High-End Code Generation, Cross-File Alignment, Architectural Coherence & Quality-Enforced Execution  
**Schema Version:** 1.0.0  
**Authoritative Module:** `core/contracts/rubric.py`  

---

## 1. Overview and Invariant

The `QualityRubric` is the authoritative specification describing **how to judge completeness and quality** of generated projects. It decouples task requirements into:
1. **Hard Requirements:** Deterministic binary requirements (syntax validity, zero dead links, cross-file alignment, non-empty files) that MUST pass.
2. **Advisory Quality Dimensions:** Multi-dimensional quality assessments (visual depth, responsive design, interactive state handling, code depth) scaled to project complexity.
3. **Anti-Placeholder Rules:** Explicit rejections of empty stubs, TODO comments, and generic boilerplate.

### Key Invariant:
**No Toy Outputs:** A project cannot pass verification simply because tools succeeded or files were written. It must pass all hard requirements and meet the quality dimension thresholds appropriate for its complexity profile.

---

## 2. Rubric Schema Fields

| Field Name | Type | Description |
|---|---|---|
| `schema_version` | `str` | Semantic schema version (default: `"1.0.0"`). |
| `rubric_id` | `str` | Unique identifier formatted as `rbc_<8-char-hex>`. |
| `mission_id` | `str` | Associated HERMES mission ID. |
| `task_type` | `str` | Task archetype: `"vanilla_web"`, `"dashboard"`, `"landing_page"`, `"python_cli"`, `"api"`. |
| `complexity_profile` | `str` | Project complexity level: `"TRIVIAL"`, `"SIMPLE"`, `"MEDIUM"`, `"COMPLEX"`, `"LARGE"`. |
| `hard_requirements` | `List[RubricRequirement]` | Mandatory pass/fail requirements that block completion if failed. |
| `quality_dimensions` | `Dict[str, QualityDimension]` | Weighted quality dimensions scored from 0.0 to 1.0 against quality thresholds. |
| `anti_placeholder_rules` | `List[str]` | Prohibited patterns (e.g. `"no_todo_comments"`, `"no_lorem_ipsum"`). |
| `expected_loc_bounds` | `Dict[str, Dict[str, int]]` | Expected minimum and maximum lines of code per file path. |
| `evaluation_verdict` | `str` | Current evaluation verdict: `"PENDING"`, `"PASS"`, `"NEEDS_IMPROVEMENT"`, `"FAIL"`. |
| `rubric_hash` | `str` | Canonical SHA-256 fingerprint of the quality rubric. |

---

## 3. Hard Requirements vs. Advisory Dimensions

### 3.1 Hard Requirements (`RubricRequirement`)
Hard requirements are non-negotiable correctness gates:
- **`HR_SYNTAX_VALID`:** All HTML, CSS, JS, and Python files must be syntactically valid with balanced braces and tags.
- **`HR_NO_DEAD_LINKS`:** All internal `<a href="...">` anchors and references must resolve to real files on disk.
- **`HR_CROSS_FILE_ALIGNMENT`:** All DOM IDs referenced in JavaScript must exist in HTML. All CSS classes must be present in markup or declared utility sets.
- **`HR_NON_TRIVIAL_CONTENT`:** Files must exceed the minimum line and byte bounds defined in `expected_loc_bounds`.
- **`HR_NO_PLACEHOLDERS`:** Zero occurrences of `"// TODO"`, `"/* logic here */"`, `"Lorem ipsum"`, or empty event listener callbacks.

### 3.2 Advisory Quality Dimensions (`QualityDimension`)
Dimensions scored across high-end output categories:
- **`visual_depth` (Weight 1.5):** Coherent color palette (CSS custom properties), typography hierarchy, shadows, borders, card elevation, and visual rhythm.
- **`responsive_layout` (Weight 1.2):** Explicit `@media` query breakpoints (mobile, tablet, desktop), flexible grids/flexbox, touch-friendly touch targets.
- **`interactivity` (Weight 1.5):** Form submissions with validation, dynamic DOM rendering, search/filter logic, active/hover/focus states, local persistence.
- **`motion_animation` (Weight 1.0):** Smooth CSS transitions (`transition: all 0.2s ease`), keyframe animations (`@keyframes`), interactive feedback.
- **`code_depth` (Weight 1.0):** Complete, production-ready implementation logic without truncated sections or simulated mock stubs.

---

## 4. Complexity-Scaled Thresholds

| Complexity Profile | Target LOC (Web App) | Required Quality Dimensions | Min Dimension Threshold |
|---|---|---|---|
| **TRIVIAL** | 10–50 LOC | Syntax only | 0.50 |
| **SIMPLE** | 50–150 LOC | Syntax, basic styling, responsive layout | 0.65 |
| **MEDIUM** | 150–500 LOC | Full visual depth, responsive layout, DOM interactivity, persistence | 0.75 |
| **COMPLEX** | 500–1500+ LOC | Full design system, state machine, modals, data table, search/filter, full motion | 0.85 |
| **LARGE** | 1500+ LOC | Multi-tier architecture, API contracts, modular styling, component hierarchy | 0.90 |
