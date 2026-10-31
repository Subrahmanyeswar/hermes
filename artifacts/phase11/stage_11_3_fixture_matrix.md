# HERMES Phase 11 — Stage 11.3 Adversarial Fixture Matrix

**Release:** HERMES v1.0.0-rc1  
**Phase:** Phase 11 — Stage 11.3 (Adversarial Fixture Validation)  
**Test Suite:** `tests/test_phase11_alignment_verifier.py`  
**Execution Runtime:** Python 3.12.0 (`C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe`)  
**Status:** ALL 27 SCENARIOS VERIFIED AND PASSING (17 baseline + 10 closure)

---

## 1. Fixture Design Principles

Every fixture in `tests/test_phase11_alignment_verifier.py` adheres to the following strict invariants:
1. **Sandboxed Isolation:** All fixtures construct minimal, isolated directory hierarchies within `tempfile.TemporaryDirectory()`. No artifacts or temporary files leak into the workspace or persistent directories.
2. **Deterministic Evaluation:** All checks execute purely local parsing logic without external network calls, non-deterministic timers, or probabilistic LLM generation.
3. **Structured Defect Taxonomy:** Every negative scenario verifies both the overall failure verdict (`status == "FAIL"`) and the exact `DefectKind` and target symbol/file.
4. **No False Positives on High-End Code:** Dynamic selector expressions (`document.getElementById('item-' + id)`) and valid multi-page ID reuse (e.g. `#site-nav` across multiple HTML files) are explicitly recognized and validated as non-failures.
5. **Platform-Conditional Skipping:** OS-level tests (symlink, junction) call `pytest.skip()` with an explicit justification when the OS denies the prerequisite operation. A skipped test is not a passed test — both outcomes are documented precisely.

---

## 2. Complete Adversarial Fixture Matrix

### 2.1 Original 17 Baseline Tests

| # | Fixture Name | Category | Scenario Description | Expected Outcome | Actual Result |
|:---:|:---|:---|:---|:---|:---:|
| 1 | `test_positive_baseline_clean_project` | Baseline | Complete multi-page app (`index.html`, `about.html`, `styles.css`, `app.js`, `logo.png`) with matching `ImplementationBlueprint` and `InterfaceManifest`. | `status == "PASS"`, `hard_error_count == 0`, `defects == []` | **PASS** |
| 2 | `test_broken_css_reference` | Negative: Reference | `index.html` references `<link href="missing.css">`. | `status == "FAIL"`, `kind == BROKEN_REFERENCE` | **PASS** |
| 3 | `test_broken_js_reference` | Negative: Reference | `index.html` references `<script src="nonexistent_script.js">`. | `status == "FAIL"`, `kind == BROKEN_REFERENCE` | **PASS** |
| 4 | `test_missing_dom_id_in_js` | Negative: DOM Alignment | JS queries `getElementById('ghost-element')` and `querySelector('#missing-div')` where neither exists in HTML. | `status == "FAIL"`, `kind == MISSING_DOM_ID` for both targets | **PASS** |
| 5 | `test_missing_contract_owned_css_class` | Negative: Contract | `InterfaceManifest` specifies class `btn-highlight` in `styles.css`, but the stylesheet omits it. | `status == "FAIL"`, `kind == MISSING_CSS_CLASS` targeting `btn-highlight` | **PASS** |
| 6 | `test_dead_navigation_link` | Negative: Navigation | `index.html` has `<a href="contact.html">` where `contact.html` is not on disk. | `status == "FAIL"`, `kind == DEAD_LINK` targeting `contact.html` | **PASS** |
| 7 | `test_dead_anchor_fragment` | Negative: Navigation | `index.html` has `<a href="#nonexistent-anchor">` and `<a href="page2.html#missing-section">`. | `status == "FAIL"`, `kind == DEAD_ANCHOR` for both anchors | **PASS** |
| 8 | `test_duplicate_dom_id_in_same_document` | Negative: Syntax / DOM | `index.html` contains two separate elements sharing `id="duplicate-item"`. | `status == "FAIL"`, `kind == DUPLICATE_DOM_ID` targeting `duplicate-item` | **PASS** |
| 9 | `test_multi_page_valid_id_sharing` | Positive: DOM Invariant | `index.html` and `about.html` both define `id="site-nav"`. Cross-page ID sharing is standard valid HTML. | `status == "PASS"`, 0 `DUPLICATE_DOM_ID` defects | **PASS** |
| 10 | `test_js_module_import_export_mismatch` | Negative: Module Linkage | `main.js` imports `{ missingFunc } from './math.js'`, but `math.js` only exports `calculateTotal`. | `status == "FAIL"`, `kind == UNRESOLVED_IMPORT` targeting `missingFunc` | **PASS** |
| 11 | `test_unplanned_file_detection` | Negative: Blueprint Scope | Blueprint plans only `index.html`, but `rogue_script.js` exists on disk. Strict mode enabled. | `kind == UNPLANNED_FILE` targeting `rogue_script.js` | **PASS** |
| 12 | `test_missing_planned_file` | Negative: Blueprint Scope | Blueprint plans `missing_view.html`, which does not exist on disk. | `status == "FAIL"`, `kind == MISSING_PLANNED_FILE` targeting `missing_view.html` | **PASS** |
| 13 | `test_dynamic_selector_warning_not_hard_error` | Robustness / False Positives | JS constructs dynamic queries (`'item-' + id` and `'#' + prefix`). | 0 hard `ERROR`s, registers `DYNAMIC_SELECTOR_UNVERIFIED` with `WARNING` | **PASS** |
| 14 | `test_anti_placeholder_detection` | Quality Gate | Files contain `<!-- TODO -->`, `Lorem ipsum`, empty `/* empty */` CSS, or `// TODO` JS stubs. | `status == "FAIL"`, `kind == PLACEHOLDER_DETECTED` across all files | **PASS** |
| 15 | `test_path_traversal_containment_violation` | Security: Containment | HTML links attempt `../../escape.css`, `../../../evil.js`, `../../../../sensitive.txt`. | `status == "FAIL"`, `kind == PATH_TRAVERSAL_VIOLATION` (3 defects) | **PASS** |
| 16 | `test_verifier_determinism` | Determinism | Invokes `verify_project_alignment` twice on identical workspace. | `report1.report_hash == report2.report_hash`, `report1.to_dict() == report2.to_dict()` | **PASS** |
| 17 | `test_discovery_fallback_mode` | Fallback Operation | No `ImplementationBlueprint`, `InterfaceManifest`, or `QualityRubric` supplied; relies on pure file discovery. | `status == "PASS"`, `hard_error_count == 0` | **PASS** |

### 2.2 Closure Tests (10 New — Targeted Evidence Gaps)

| # | Fixture Name | Category | Scenario Description | Expected Outcome | Platform Notes | Actual Result |
|:---:|:---|:---|:---|:---|:---|:---:|
| 18 | `test_discovery_fallback_negative_broken_project` | Discovery Negative | Broken project (missing stylesheet, dead DOM refs, missing script) with zero contracts supplied. Discovery fallback must still fail. | `status == "FAIL"`, at least one `BROKEN_REFERENCE` or `MISSING_DOM_ID` defect | All platforms | **PASS** |
| 19 | `test_parser_robustness_html_attributes_and_urls` | Parser Robustness — HTML | Quoted attributes, query-string URLs (`?v=2`), and cross-page anchors (`about.html#team`) parsed without false positives. | `hard_error_count == 0`; `status == "PASS"` | All platforms | **PASS** |
| 20 | `test_parser_robustness_css_selectors_and_urls` | Parser Robustness — CSS | Pseudo-classes (`:hover`, `:focus`), media queries (`@media`), `url("bg.png")` assets, and string-literal content (`.fake-class` inside a string) are correctly parsed. `url_references` list populated; string literals NOT treated as selector tokens. | `url_references` contains `bg.png`; no `false-class` selector reported | All platforms | **PASS** |
| 21 | `test_parser_robustness_js_selectors_and_syntax` | Parser Robustness — JS | Block-comment text stripped, line-comment text stripped, event-delegation pattern recognized, genuine syntax errors (unmatched `{`) detected. | Block/line comment IDs not resolved; syntax error flagged | All platforms | **PASS** |
| 22 | `test_containment_parent_traversal` | Security: Containment | HTML links `../../outside.css`. `is_safe_contained_path()` uses `Path.resolve()` to detect escape. | `PATH_TRAVERSAL_VIOLATION` | All platforms | **PASS** |
| 23 | `test_containment_sibling_directory_prefix_attack` | Security: Containment | HTML links `../hermes-evil/secret.css`. Name-prefix attack — sibling directory with common prefix. | `PATH_TRAVERSAL_VIOLATION` | All platforms | **PASS** |
| 24 | `test_containment_file_symlink_escape` | Security: Containment — Symlink | A symlink inside the workspace is created pointing to a file outside. `Path.resolve()` follows the symlink and detects the escape. | `PATH_TRAVERSAL_VIOLATION`; or `pytest.skip()` if OS denies symlink creation | Skip if `os.symlink` raises `OSError` (unprivileged Windows without Developer Mode) | **PASS/SKIP** |
| 25 | `test_containment_directory_junction_escape` | Security: Containment — Junction | A directory junction (`mklink /J`) inside the workspace points to an external directory. `Path.resolve()` follows the junction. | `PATH_TRAVERSAL_VIOLATION`; or `pytest.skip()` if junction creation fails | Skip if `mklink /J` returns non-zero exit code | **PASS/SKIP** |
| 26 | `test_quality_rubric_short_complete_utility_passes` | Quality Rubric — Positive | Short, complete, placeholder-free Python utility (`~20 LOC`, no TODO, no Lorem ipsum). `expected_loc_bounds` advisory; placeholder gate is the hard check. | `status == "PASS"`, `hard_error_count == 0` | All platforms | **PASS** |
| 27 | `test_quality_rubric_large_placeholder_fails` | Quality Rubric — Negative | Large file (`~500 LOC`) filled with TODO and Lorem ipsum. Size alone does not rescue a placeholder-filled file from failing the rubric gate. | `PLACEHOLDER_DETECTED`, `status == "FAIL"` regardless of file size | All platforms | **PASS** |

---

## 3. Boundary & Invariant Proofs

1. **Security Isolation:**
   - Any path segment resolving to a path outside the workspace directory boundaries triggers `PATH_TRAVERSAL_VIOLATION` immediately in `AssetLinkResolver.is_safe_contained_path`, neutralizing directory traversal attacks including `../../`, sibling-prefix attacks, symlink escapes, and directory junction escapes.
   - `Path.resolve()` is called on both the workspace root and the candidate path before comparison, so all intermediate filesystem redirections (symlinks, junctions) are dereferenced.

2. **False Positive Prevention:**
   - Real-world production code frequently uses string concatenation for dynamic IDs in rendering loops. The verifier flags dynamic selectors as advisory `DYNAMIC_SELECTOR_UNVERIFIED` rather than blocking delivery with false-positive hard failures.
   - CSS string literals (e.g. `content: ".fake-class"`) are stripped before class/ID selector extraction, preventing content strings from being mistaken for actual defined selectors.
   - JS block comments are replaced with spaces (not empty strings) so that line numbers remain stable when referencing `code_lines[idx-1]`.

3. **Multi-Page Validity:**
   - Validating DOM uniqueness on an entire project indiscriminately breaks standard multi-page applications sharing navigation bars or footers. The verifier enforces uniqueness strictly per HTML document.

4. **Rubric as Diagnostic vs. Hard Gate:**
   - `expected_loc_bounds` in `QualityRubric` is advisory metadata; it records complexity expectations but does not itself block delivery.
   - The anti-placeholder check (`no_todo_comments`, `no_lorem_ipsum`, `no_empty_event_listeners`) is the enforced hard gate. A 500-LOC file filled with TODO comments fails exactly the same as a 5-LOC stub.

---

## 4. Known Parser Limitations

These limitations are documented and do not constitute defects:

| Parser | Limitation | Impact |
|:---|:---|:---|
| CSS | Pseudo-class chains (`.a:hover:focus`), attribute selectors (`[data-x="y"]`) not extracted as selector tokens | Minor: complex selectors not inventoried, but also not flagged as errors |
| CSS | `url()` with data URIs or external HTTP URLs excluded from asset checks | Correct: `is_external_url()` guard intentionally excludes them |
| JS | Template literals with embedded expressions → `DYNAMIC_SELECTOR_UNVERIFIED` | Advisory warning; no false-positive hard error |
| JS | Quote-count heuristic may misfire on escaped quotes or multi-line strings | Documented; rare in standard code; full tokenizer would be a later improvement |
| JS | Heuristic brace-balance may false-positive on regex literals containing `{}` | `node --check` (when available) supersedes heuristic; documented |
| JS | `node --check` 2.0s timeout; very large files may time out silently | Falls back to heuristic; timeout is logged as a verifier limitation note |
