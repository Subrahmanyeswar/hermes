# HERMES Phase 11 — Interface Manifest Schema Specification

**Release:** HERMES v1.0.0-rc1  
**Phase:** 11 — High-End Code Generation, Cross-File Alignment, Architectural Coherence & Quality-Enforced Execution  
**Schema Version:** 1.0.0  
**Authoritative Module:** `core/contracts/manifest.py`  

---

## 1. Overview and Invariant

The `InterfaceManifest` is the authoritative specification describing **how the project's files connect** across markup, styling, scripting, navigation, assets, state, and API boundaries.

### Key Invariants:
1. **Source of Truth for Bindings:** DOM IDs, CSS classes, event listeners, form names, and links are registered here before consumers reference them.
2. **Cross-File Coherence:** No file is permitted to reference an element ID, class, or route that is not registered in the manifest.
3. **No Unplanned File Ownership:** Every contract item (element ID, CSS class, hook, form) must be explicitly owned by a file declared in the `ImplementationBlueprint`.
4. **Deterministic Contract Hashing:** Computes a SHA-256 fingerprint over sorted contract keys. Any mutation increments `revision` and triggers contract revalidation.

---

## 2. Manifest Schema Fields

| Field Name | Type | Description |
|---|---|---|
| `schema_version` | `str` | Semantic schema version (default: `"1.0.0"`). |
| `manifest_id` | `str` | Unique identifier formatted as `mnf_<8-char-hex>`. |
| `revision` | `int` | Monotonic integer incremented on each contract mutation. |
| `mission_id` | `str` | Associated HERMES mission ID. |
| `project_root` | `str` | Relative project root (default: `"."`). |
| `html_entrypoints` | `List[str]` | List of HTML entrypoints (e.g. `["index.html"]`). |
| `css_tokens` | `Dict[str, str]` | Shared CSS custom properties (`--primary: #2563eb`, `--bg: #f8fafc`). |
| `css_breakpoints` | `Dict[str, str]` | Responsive breakpoints (`mobile: 480px`, `tablet: 768px`, `desktop: 1024px`). |
| `element_ids` | `Dict[str, ElementContract]` | Declared DOM IDs with owning files, tags, and expected event listeners. |
| `css_classes` | `Dict[str, CssContract]` | Declared CSS classes with owning stylesheet files and target elements. |
| `js_hooks` | `Dict[str, JsHookContract]` | Declared DOM event listeners and interaction bindings. |
| `js_modules` | `Dict[str, JsModuleContract]` | Declared JavaScript module imports/exports or script load order. |
| `navigation_links` | `List[NavLinkContract]` | Declared internal and external navigation links. |
| `asset_references` | `List[AssetContract]` | Declared static assets (images, icons, fonts). |
| `state_schemas` | `Dict[str, StateContract]` | Declared local storage keys and state data schemas. |
| `forms` | `Dict[str, FormContract]` | Declared interactive forms, fields, and submit handlers. |
| `api_endpoints` | `Dict[str, ApiEndpointContract]` | Declared API endpoints, methods, and payload schemas. |
| `contract_hash` | `str` | Canonical SHA-256 fingerprint of the manifest. |

---

## 3. Sub-Contract Specifications

### 3.1 `ElementContract`
```python
@dataclass
class ElementContract:
    dom_id: str                              # Element ID (e.g., "task-form", "user-table")
    tag: str                                 # HTML tag (e.g., "form", "table", "button")
    owning_file: str                         # File containing this element (e.g., "index.html")
    purpose: str = ""                        # Role of this element in the UI
    event_listeners: List[str]               # Events listened to (e.g., ["submit", "click"])
    required: bool = True                    # Whether this element is mandatory for validation
```

### 3.2 `CssContract`
```python
@dataclass
class CssContract:
    class_name: str                          # CSS class name without dot (e.g., "data-table")
    owning_file: str                         # Stylesheet file (e.g., "styles.css")
    target_elements: List[str]               # Tags/components styled by this class
    styles_summary: str = ""                 # Brief summary of styling rules
    is_utility: bool = False                 # Whether this is a reusable utility class
```

### 3.3 `JsHookContract`
```python
@dataclass
class JsHookContract:
    hook_name: str                           # Selector or data attribute (e.g., "#filter-btn")
    event_type: str                          # DOM event ("click", "input", "submit")
    handler_name: str                        # Function name in JS
    owning_file: str                         # Script file containing the handler (e.g., "app.js")
    target_id: Optional[str] = None          # Bound DOM ID in ElementContract
    purpose: str = ""
```

### 3.4 `NavLinkContract`
```python
@dataclass
class NavLinkContract:
    source_file: str                         # Page containing the link (e.g., "index.html")
    target_href: str                         # Link destination (e.g., "about.html", "#features")
    label: str = ""                          # Anchor text
    link_type: str = "internal"              # "internal", "external", "anchor"
    is_tested: bool = False
```

---

## 4. Cross-Contract Validation Invariants

The `ContractValidator.validate_manifest()` and `validate_coherence()` methods enforce:
1. **DOM ID Syntax & Uniqueness:** All IDs must match `^[A-Za-z0-9_\-]+$`. No duplicate IDs may be declared for the same file.
2. **File Ownership Coherence:** Every owning file referenced by an element, class, form, or hook must be declared in the blueprint's `planned_files`.
3. **Internal Link Verification:** Every internal navigation link (`target_href`) must point to a file present in `planned_files` or a defined anchor target.
4. **JS Hook DOM ID Binding:** Any JS hook targeting an element ID must correspond to an ID declared in `element_ids`.
