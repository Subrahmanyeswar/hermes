# Stage 11.2 Reconnaissance: Deterministic Cross-File Alignment Verification

## 1. Context and Objective

Phase 11 Stage 11.0 proved that HERMES's code-generation quality regressions were driven by:
1. Fast-path stubbing that bypassed deep execution loops.
2. Cross-file divergence between HTML, CSS, and JS (broken references, mismatched DOM IDs, missing CSS classes, dead navigation links).
3. Lack of a deterministic verification engine that validates project files against agreed architectural contracts before mission completion.

Stage 11.1 established the three core versioned contracts:
- `ImplementationBlueprint` (`core/contracts/blueprint.py`)
- `InterfaceManifest` (`core/contracts/manifest.py`)
- `QualityRubric` (`core/contracts/rubric.py`)

Stage 11.2 builds the **Deterministic Cross-File Alignment Verification Engine** (`core/alignment_verifier.py`).
Stage 11.3 creates the adversarial fixture test suite (`tests/test_phase11_alignment_verifier.py`) validating the verifier against clean projects and at least 13 distinct negative failure modes.

---

## 2. Existing Verifier Assessment

HERMES currently possesses several verification utilities:

1. `TechnologyAwareBehavioralVerifier` (`core/agent_loop/behavioral_verifier.py`):
   - Uses basic regex parsing to detect `<link>` and `<script>` tags in `index.html`.
   - Checks balance of `{}`, `()`, `[]` in JS files.
   - Looks for basic interactivity indicators (`addEventListener`, form tags).
   - *Limitations*:
     - Only inspects `index.html`, ignoring multi-page sites (e.g. `about.html`, `dashboard.html`).
     - Regex-based CSS/JS parsing is naive to comments, strings, template literals, and regex literals.
     - Lacks cross-file DOM ID verification (e.g., verifying `document.getElementById('save-btn')` actually exists in HTML).
     - Lacks CSS class resolution (e.g., verifying classes used in HTML exist in CSS or vice versa).
     - Lacks anchor tag (`#hash`) verification.
     - Does not understand `InterfaceManifest` or `ImplementationBlueprint` contracts.

2. `ProgressiveVerifier` (`core/progressive_verifier.py`):
   - Tracks verification stages across execution.
   - Delegates to static checks and subprocess test runners.
   - Does not perform AST or deep structural cross-file alignment.

3. `QualityVerifier` (`core/quality_verifier.py`):
   - High-level metric aggregation.
   - Does not analyze DOM trees, stylesheet rules, or module linkages.

---

## 3. Design Requirements for `core/alignment_verifier.py`

### 3.1 Contract-Driven & Discovery Fallback Verification
The verifier must operate in two modes:
1. **Contract-Aware Mode**: When `ImplementationBlueprint`, `InterfaceManifest`, and/or `QualityRubric` are supplied, the verifier validates that:
   - Planned files exist on disk.
   - Manifest `element_ids` exist in their specified `owning_file`.
   - Manifest `css_classes` exist in their stylesheets and match HTML usage.
   - Manifest `js_hooks` and `js_modules` have valid bindings and matching exports/imports.
   - Manifest `navigation_links` resolve to real files or in-page anchors.
   - Rubric anti-placeholder rules pass.
2. **Discovery Fallback Mode**: If contracts are absent or partial, the verifier scans all HTML, CSS, and JS files on disk within the workspace root, extracting tags, IDs, classes, scripts, stylesheets, and anchors, verifying cross-file integrity deterministically.

### 3.2 Parsing Strategy
1. **HTML**: Standard library `html.parser.HTMLParser` supplemented with targeted element inspection:
   - Extracts all DOM `id` attributes with line numbers.
   - Detects intra-document duplicate IDs (flagged as hard error).
   - Allows inter-document identical IDs (different HTML pages having `#header` or `#nav` is standard and valid).
   - Extracts class attributes, splitting into class tokens.
   - Extracts `<link rel="stylesheet">`, `<script src="...">`, `<img>`, `<video>`, `<audio>`, `<source>`, `<a href="...">`.
2. **CSS**:
   - Comment-safe scanner stripping `/* ... */` comments.
   - Extracts CSS selectors (`.class-name`, `#id`, `@keyframes`, custom properties `--var`).
   - Reconciles class names with HTML usage.
3. **JavaScript**:
   - Comment-safe scanner stripping `// ...` and `/* ... */` comments.
   - Extracts DOM references:
     - `document.getElementById('...')`
     - `document.querySelector('#...')`, `document.querySelector('.class')`
     - `document.querySelectorAll(...)`
   - **Dynamic Selectors**: When JS constructs dynamic IDs (e.g., `document.getElementById('item-' + id)` or `document.querySelector('#' + prefix)`), it must NOT produce a false-positive hard error. It must be classified as `DYNAMIC_SELECTOR_UNVERIFIED` with severity `WARNING` / `INFO`.
   - Extracts ES module `import` and `export` statements, verifying symbol correspondence across files.
   - Checks balance of braces, parentheses, and brackets.
4. **Navigation & Anchors**:
   - Validates internal links (`page.html`, `./sub/page.html`).
   - Validates internal anchors (`#section-id`, `page.html#section-id`).
   - Ignores or validates external links (`http://`, `https://`, `mailto:`, `tel:`, `#` no-op placeholder).
5. **Security & Workspace Containment**:
   - All relative links and paths must be resolved strictly inside `workspace_root`.
   - Any path attempting `../` path traversal outside `workspace_root` triggers a `PATH_TRAVERSAL_VIOLATION` error.
6. **Anti-Placeholder Quality Gate**:
   - Rejects `// TODO`, `/* TODO */`, `<!-- TODO -->`, `Lorem ipsum`, empty event listeners, and 1-line stubs.

---

## 4. Architectural Boundaries
- Stages 11.2 & 11.3 build and verify `core/alignment_verifier.py` and `tests/test_phase11_alignment_verifier.py`.
- They do **NOT** modify the agent execution loop or wire into loop completion policy (which is Stage 11.4).
- Deterministic behavior: running the verifier twice on the same filesystem state produces identical outputs and checksums.
