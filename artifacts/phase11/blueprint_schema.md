# HERMES Phase 11 — Implementation Blueprint Schema Specification

**Release:** HERMES v1.0.0-rc1  
**Phase:** 11 — High-End Code Generation, Cross-File Alignment, Architectural Coherence & Quality-Enforced Execution  
**Schema Version:** 1.0.0  
**Authoritative Module:** `core/contracts/blueprint.py`  

---

## 1. Overview and Invariant

The `ImplementationBlueprint` is the authoritative specification describing **what the project must contain, its component architecture, planned files, and verifiable acceptance requirements** before code generation begins.

### Key Invariants:
1. **No Code Without Blueprint:** Every generated artifact must trace back to an entry in `planned_files`.
2. **Deterministic Hashing:** Every blueprint computes a canonical SHA-256 content hash across sorted keys.
3. **DAG Dependency Acyclicity:** File dependencies (`planned_files[].dependencies`) must form a strict directed acyclic graph. Circular dependencies are rejected during validation.
4. **Backward Compatibility:** All new fields serialize cleanly and deserialize safely with fallback defaults when loading legacy checkpoints.

---

## 2. Blueprint Schema Fields

| Field Name | Type | Description |
|---|---|---|
| `schema_version` | `str` | Semantic schema version (default: `"1.0.0"`). |
| `blueprint_id` | `str` | Unique identifier formatted as `bp_<8-char-hex>`. |
| `revision` | `int` | Monotonic integer incremented on each contract mutation. |
| `mission_id` | `str` | Associated HERMES mission ID. |
| `project_type` | `str` | Architectural type: `"vanilla_web"`, `"multi_page_web"`, `"dashboard"`, `"python_cli"`, `"api"`. |
| `delivery_mode` | `str` | Execution/serving mode: `"file_system"` (direct `file://`), `"served"` (HTTP daemon), `"static"`. |
| `user_requirements` | `List[str]` | Normalized user goals and functional requirements extracted from prompt. |
| `acceptance_criteria` | `List[str]` | Verifiable conditions that determine task completion. |
| `design_brief` | `Dict[str, Any]` | Typography, color palette, responsive breakpoints, layout grid, and visual design parameters. |
| `planned_files` | `List[FilePlan]` | List of planned files with paths, roles, dependencies, ordered sections, and feature assignments. |
| `component_tree` | `List[ComponentSpec]` | Hierarchical component specifications (parent, children, attributes, state bindings). |
| `routes` | `List[RouteSpec]` | Planned navigation routes/pages (path, title, file_path, entrypoint flag). |
| `data_models` | `List[DataModelSpec]` | Planned schemas for local data structures, storage keys, and validation rules. |
| `complexity_profile` | `str` | Project complexity level: `"TRIVIAL"`, `"SIMPLE"`, `"MEDIUM"`, `"COMPLEX"`, `"LARGE"`. |
| `quality_targets` | `Dict[str, Any]` | Project-specific targets (e.g. minimum lines of code, test coverage, animation support). |
| `content_hash` | `str` | Canonical SHA-256 fingerprint of the blueprint structure. |

---

## 3. Sub-Model Specifications

### 3.1 `FilePlan`
```python
@dataclass
class FilePlan:
    path: str                                # Relative file path (e.g., "index.html", "src/utils.py")
    purpose: str                             # Plain text summary of file responsibility
    role: str = "component"                  # "entrypoint", "style", "logic", "component", "config", "test"
    dependencies: List[str]                  # List of file paths this file depends on
    ordered_sections: List[str]              # Top-to-bottom sections for ordered generation
    features: List[str]                      # Specific feature tags implemented in this file
    min_lines: int = 10                      # Expected non-trivial LOC threshold
    target_exports: List[str]                # Functions, classes, or symbols exported by this file
```

### 3.2 `RouteSpec`
```python
@dataclass
class RouteSpec:
    path: str                                # Route path (e.g., "/", "/about.html")
    title: str                               # Page title
    file_path: str                           # Owning file path
    nav_label: str = ""                      # Text label in navigation menu
    is_entrypoint: bool = False              # True if this is the default landing page
    query_params: List[str]                  # Expected query parameter names
```

### 3.3 `ComponentSpec`
```python
@dataclass
class ComponentSpec:
    name: str                                # Component name (e.g., "AppHeader", "DataTable")
    role: str                                # Functional role description
    file_path: str                           # Owning file path
    parent_component: Optional[str] = None   # Parent component name
    child_components: List[str]              # Child component names
    attributes: Dict[str, Any]               # Tag attributes, classes, or props
    state_bindings: List[str]                # Bound state variables or models
```

---

## 4. Validation and Safety Guarantees

The `ContractValidator.validate_blueprint()` method enforces:
1. **Non-Empty Path Rules:** Every `FilePlan` must specify a non-empty relative path.
2. **Duplicate Path Prevention:** No two files may claim the same relative path.
3. **Graph Acyclicity:** Dependency relationships are analyzed via depth-first search cycle detection.
4. **Route File Integrity:** Every route must target a file declared in `planned_files`.
