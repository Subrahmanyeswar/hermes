# HERMES Phase 11 — Alignment Verifier Design

## 1. System Overview

The **Deterministic Cross-File Alignment Verification Engine** (`core/alignment_verifier.py`) is responsible for deterministically inspecting workspace codebases on disk, comparing files against versioned contracts (`ImplementationBlueprint`, `InterfaceManifest`, `QualityRubric`), and validating cross-file coherence.

```
       +-------------------------------------------------------------+
       |                  verify_project_alignment                   |
       |  (workspace_root, blueprint, interface_manifest, rubric)   |
       +-------------------------------------------------------------+
                                      |
         +----------------------------+----------------------------+
         |                            |                            |
         v                            v                            v
+------------------+         +------------------+         +------------------+
| HtmlAlignment    |         | CssAlignment     |         | JsAlignment      |
| Scanner          |         | Scanner          |         | Scanner          |
| - DOM IDs        |         | - Selectors      |         | - DOM queries    |
| - Duplicate IDs  |         | - Classes        |         | - Event hooks    |
| - Classes        |         | - Keyframes      |         | - Imports/Exports|
| - Links / Assets |         | - Custom Props   |         | - node --check   |
|                  |         | - url() assets   |         | - Syntax balance |
+------------------+         +------------------+         +------------------+
         |                            |                            |
         +----------------------------+----------------------------+
                                      |
                                      v
                     +----------------------------------+
                     |       AssetLinkResolver          |
                     | - Workspace Path Containment     |
                     |   (symlinks, junctions, ../)     |
                     | - Relative link resolution       |
                     | - Anchor hash verification       |
                     +----------------------------------+
                                      |
                                      v
                     +----------------------------------+
                     |     Cross-File Reconciler        |
                     | - HTML <-> CSS class alignment   |
                     | - HTML <-> JS DOM ID alignment   |
                     | - Contract-owned verification    |
                     | - Anti-placeholder rules         |
                     +----------------------------------+
                                      |
                                      v
                     +----------------------------------+
                     |        AlignmentReport           |
                     | status, hard_error_count, checks,|
                     | defects, files_examined, checksum|
                     +----------------------------------+
```

---

## 2. Data Models and Types

### 2.1 Defect Kind and Severity
```python
class DefectSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"

class DefectKind(str, Enum):
    BROKEN_REFERENCE = "BROKEN_REFERENCE"
    MISSING_DOM_ID = "MISSING_DOM_ID"
    MISSING_CSS_CLASS = "MISSING_CSS_CLASS"
    DUPLICATE_DOM_ID = "DUPLICATE_DOM_ID"
    DEAD_LINK = "DEAD_LINK"
    DEAD_ANCHOR = "DEAD_ANCHOR"
    UNRESOLVED_IMPORT = "UNRESOLVED_IMPORT"
    EXPORT_MISMATCH = "EXPORT_MISMATCH"
    UNPLANNED_FILE = "UNPLANNED_FILE"
    MISSING_PLANNED_FILE = "MISSING_PLANNED_FILE"
    PLACEHOLDER_DETECTED = "PLACEHOLDER_DETECTED"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    PATH_TRAVERSAL_VIOLATION = "PATH_TRAVERSAL_VIOLATION"
    DYNAMIC_SELECTOR_UNVERIFIED = "DYNAMIC_SELECTOR_UNVERIFIED"
```

### 2.2 AlignmentDefect, AlignmentCheck, AlignmentReport
```python
@dataclass
class AlignmentDefect:
    kind: DefectKind
    severity: DefectSeverity
    message: str
    file_path: str
    line_number: Optional[int] = None
    target: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AlignmentCheck:
    name: str
    status: str       # "PASS", "FAIL", "WARNING", "SKIPPED"
    message: str
    defects: List[AlignmentDefect] = field(default_factory=list)

@dataclass
class AlignmentReport:
    status: str       # "PASS", "FAIL", "WARNING"
    hard_error_count: int
    warning_count: int
    checks: List[AlignmentCheck]
    defects: List[AlignmentDefect]
    files_examined: List[str]
    limitations: List[str]
    report_hash: str
```

---

## 3. Parsing and Scanner Specifics

### 3.1 HTML Scanner (`HtmlAlignmentScanner`)
- Uses `html.parser.HTMLParser` to parse HTML line-by-line.
- **Duplicate ID Detection**: Tracks seen IDs per HTML document. If an ID is encountered more than once within the same file, records `DUPLICATE_DOM_ID` (ERROR).
- **Multi-Page Handling**: Different HTML documents are tracked separately; an ID present in both `index.html` and `about.html` is valid and expected.
- **Class Extraction**: Extracts classes from `class="..."`, splitting on whitespace.
- **Tag References**:
  - `<link rel="stylesheet" href="...">` -> linked CSS stylesheets.
  - `<script src="...">` -> linked JS scripts.
  - `<img src="...">`, `<video src="...">`, `<audio src="...">`, `<source src="...">` -> linked assets.
  - `<a href="...">` -> navigation links and anchor targets (with query-string and fragment handling).

### 3.2 CSS Scanner (`CssAlignmentScanner`)
- Strips comments (`/* ... */`) cleanly before rule parsing.
- **String-Literal Stripping**: Strips quoted string literals (`"..."`, `'...'`) before extracting selectors, preventing CSS `content: ".fake-class"` from registering as an active CSS class.
- Extracts class selectors (`.[a-zA-Z0-9_-]+`), ID selectors (`#[a-zA-Z0-9_-]+`), `@keyframes`, custom properties (`--[a-zA-Z0-9_-]+`).
- **`url(...)` Asset References**: Extracts local asset references within `url(...)` declarations (e.g. background images, fonts) and stores them in `url_references` for broken-asset reconciliation against disk.
- Validates brace balance `{}` across stylesheet rules.
- Flags empty rules or files containing only comments when anti-placeholder rules are active.

### 3.3 JS Scanner (`JsAlignmentScanner`)
- **Node.js Real Syntax Validation**: When `node` is available and the file path is accessible, invokes `node --check <file>` (with a 2.0s timeout) to run real compiler syntax verification.
- **Comment-Safe Line Processing**:
  - Block comments (`/* ... */`) are stripped by replacing their content with space characters, preserving line count and line indices so diagnostic line numbers accurately point to the original file.
  - Single-line comments (`// ...`) are stripped per line for selector scanning.
- **String-Literal Protection**: Uses a quote-count heuristic to ensure DOM query matches inside string literals are ignored.
- Extracts DOM queries:
  - `document.getElementById('id')`
  - `document.querySelector('#id')`
  - `document.querySelector('.class')`
  - `document.querySelectorAll(...)`
- **Dynamic Selectors**: If a query relies on string concatenation or template variables (e.g. `document.getElementById('task-' + id)` or `document.querySelector('#' + id)`), registers a `DYNAMIC_SELECTOR_UNVERIFIED` warning/info note rather than failing the check with a false positive.
- Extracts ES module imports and exports:
  - `import { a, b } from './module.js'`
  - `import defaultName from './module.js'`
  - `export function fn()`
  - `export const name`
  - `export class Cls`
  - `export { a, b }`
  - `export default ...`
- Syntax balance check: verifies matching counts of `{}`, `()`, `[]` as fallback if node syntax check is not available.

### 3.4 AssetLinkResolver & Path Containment
- Standardizes all link URLs: strips query parameters (`?query=1`) and extracts anchor fragments (`#section`).
- Resolves relative targets relative to the directory of the referencing file.
- **Path Containment Check (`is_safe_contained_path`)**:
  - Dereferences both workspace root and target path via canonical `Path.resolve()`.
  - Uses `resolved_target.is_relative_to(resolved_root)`.
  - Neutralizes parent-directory traversal (`../../`), sibling prefix collisions (`workspace-evil/`), symlinks pointing outside the workspace, and directory junctions/reparse points.
  - If containment is violated, raises `PATH_TRAVERSAL_VIOLATION` (ERROR).
- Verifies that target files exist on disk.
- If anchor fragment is present (e.g. `about.html#team` or `#faq`), verifies that target document contains element with matching DOM ID or `<a name="...">`.

---

## 4. Reconciliation and Contract Checking

### 4.1 Interface Manifest Checking
- `element_ids`: For each `ElementContract`, checks that `dom_id` exists in `owning_file`. If missing and `required=True`, flags `MISSING_DOM_ID`.
- `css_classes`: For each `CssContract`, checks that `class_name` is defined in `owning_file`.
- `js_hooks`: Checks that event hook targets exist and owning JS file contains the hook.
- `js_modules`: For each `JsModuleContract`, verifies that all imported symbols match exports in target modules.
- `navigation_links`: Checks that every `NavLinkContract` points to a reachable file or anchor.

### 4.2 Blueprint Checking
- `planned_files`: Verifies every file in `blueprint.planned_files` exists on disk.
- `strict_file_set`: If enabled, flags files found on disk that were not planned in the blueprint.

### 4.3 Rubric Checking & Complexity Sizing
- **LOC and Byte Sizes as Diagnostic Signals**: `expected_loc_bounds` in `QualityRubric` are diagnostic complexity metrics, not a universal hard failure gate. A short, complete utility without placeholders correctly passes.
- **Anti-Placeholder Rules (Hard Gate)**:
  - Detects placeholder comments (`// TODO`, `/* TODO */`, `<!-- TODO -->`, `FIXME`).
  - Detects placeholder dummy text (`Lorem ipsum`, `consectetur adipiscing elit`).
  - Detects stub handlers (e.g. empty event listener callbacks).
  - A large file filled with placeholder comments fails regardless of meeting size thresholds.

---

## 5. Parser Limitations and Disclosures

| Parser Component | Design Tradeoff / Limitation | Mitigation / Safety Guarantee |
|:---|:---|:---|
| CSS Selector Extraction | Pseudo-class chains (`:hover:focus`) and attribute selectors (`[attr="val"]`) are not tracked as distinct named classes | Selectors are not flagged as errors; verifier checks only manifest-declared or HTML-referenced classes |
| CSS `url()` Resolution | Data URIs (`data:...`) and external HTTP/HTTPS URLs are skipped | `is_external_url` ensures external references do not fail local file resolution |
| JS Dynamic Selectors | Dynamic expressions (`'item-' + id`) cannot be statically resolved without execution | Emits non-fatal `DYNAMIC_SELECTOR_UNVERIFIED` (WARNING/INFO), never a hard `ERROR` |
| JS String Literals | Quote-count heuristic used to detect inline queries within string literals | Documented as heuristic; complex multi-line escaped strings fall back gracefully |
| JS Syntax Validation | Node compiler validation runs with a 2.0s subprocess timeout; falls back to brace counter | If node is unavailable or times out, balance heuristic executes and limitation note is attached |
| Filesystem Containment | Symlinks and directory junctions require OS support/privileges on Windows | Tests skip cleanly with explicit justification when unprivileged Windows environment denies creation |
