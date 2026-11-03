import re

with open('core/project_contract.py', 'r', encoding='utf-8') as f:
    text = f.read()

sub = '''@dataclass
class ApiEndpointContract:
    path: str
    method: str = "GET"
    request_fields: List[str] = field(default_factory=list)
    response_fields: List[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ApiEndpointContract":
        if not d:
            return cls(path="")
        return cls(
            path=d.get("path", ""),
            method=d.get("method", "GET"),
            request_fields=list(d.get("request_fields", [])),
            response_fields=list(d.get("response_fields", [])),
            description=d.get("description", ""),
        )


@dataclass
class DeclaredInterfaces:
    """Intended application contract: what HERMES intends to build (Section 5.2)."""
    dom_ids: List[str] = field(default_factory=list)
    views: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    css_variables: List[str] = field(default_factory=list)
    api_routes: List[Dict[str, Any]] = field(default_factory=list)
    database_tables: Dict[str, List[str]] = field(default_factory=dict)
    storage_keys: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DeclaredInterfaces":
        if not d:
            return cls()
        return cls(
            dom_ids=list(d.get("dom_ids", [])),
            views=list(d.get("views", [])),
            classes=list(d.get("classes", [])),
            css_variables=list(d.get("css_variables", [])),
            api_routes=list(d.get("api_routes", [])),
            database_tables=dict(d.get("database_tables", {})),
            storage_keys=dict(d.get("storage_keys", {})),
        )


@dataclass
class ObservedInterfaces:
    """Observed application state: what the physical generated files currently contain (Section 5.2)."""
    html_ids: List[str] = field(default_factory=list)
    html_classes: List[str] = field(default_factory=list)
    form_names: List[str] = field(default_factory=list)
    css_selectors: List[str] = field(default_factory=list)
    css_variables: List[str] = field(default_factory=list)
    js_references: List[str] = field(default_factory=list)
    backend_routes: Dict[str, List[str]] = field(default_factory=dict)
    database_tables: Dict[str, List[str]] = field(default_factory=dict)
    artifact_hashes: Dict[str, str] = field(default_factory=dict)
    observed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ObservedInterfaces":
        if not d:
            return cls()
        return cls(
            html_ids=list(d.get("html_ids", [])),
            html_classes=list(d.get("html_classes", [])),
            form_names=list(d.get("form_names", [])),
            css_selectors=list(d.get("css_selectors", [])),
            css_variables=list(d.get("css_variables", [])),
            js_references=list(d.get("js_references", [])),
            backend_routes=dict(d.get("backend_routes", {})),
            database_tables=dict(d.get("database_tables", {})),
            artifact_hashes=dict(d.get("artifact_hashes", {})),
            observed_at=float(d.get("observed_at", time.time())),
        )
'''

pattern = r'@dataclass\s+class ApiEndpointContract:.*?@dataclass\s+class ProjectContract:'
replacement = sub + '\n\n@dataclass\nclass ProjectContract:'
new_text = re.sub(pattern, replacement, text, flags=re.DOTALL)
assert new_text != text, 'Pattern match failed'
with open('core/project_contract.py', 'w', encoding='utf-8') as f:
    f.write(new_text)
print('Successfully updated DeclaredInterfaces and ObservedInterfaces')
