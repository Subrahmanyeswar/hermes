# core/project_contract.py
"""
Versioned Project Contract and DOM Inventory System for HERMES.
Ensures multi-file consistency, canonical entrypoint resolution,
and cross-tier state preservation for web and full-stack missions.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class FormFieldContract:
    field_name: str
    control_id: Optional[str] = None
    input_type: str = "text"
    required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectContract:
    """
    Authoritative, versioned contract governing application topology,
    canonical entrypoints, DOM identifiers, form fields, and storage keys.
    """
    version: int = 1
    mission_id: str = ""
    app_name: str = "Application"
    app_type: str = "vanilla_web"
    is_greenfield: bool = True
    canonical_html: str = "index.html"
    canonical_js: str = "app.js"
    canonical_css: str = "style.css"
    package_json_entry: Optional[str] = None
    required_files: List[str] = field(default_factory=lambda: ["index.html", "style.css", "app.js"])
    required_ids: List[str] = field(default_factory=list)
    form_fields: Dict[str, FormFieldContract] = field(default_factory=dict)
    storage_keys: Dict[str, str] = field(default_factory=dict)
    features: List[str] = field(default_factory=list)
    contract_hash: str = ""

    def __post_init__(self):
        if not self.contract_hash:
            self.contract_hash = self.compute_hash()

    def compute_hash(self) -> str:
        d = self.to_dict()
        d.pop("contract_hash", None)
        canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "mission_id": self.mission_id,
            "app_name": self.app_name,
            "app_type": self.app_type,
            "is_greenfield": self.is_greenfield,
            "canonical_html": self.canonical_html,
            "canonical_js": self.canonical_js,
            "canonical_css": self.canonical_css,
            "package_json_entry": self.package_json_entry,
            "required_files": list(self.required_files),
            "required_ids": list(self.required_ids),
            "form_fields": {k: v.to_dict() if hasattr(v, "to_dict") else dict(v) for k, v in self.form_fields.items()},
            "storage_keys": dict(self.storage_keys),
            "features": list(self.features),
            "contract_hash": self.contract_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectContract:
        if not data:
            return cls()
        fields_map = {}
        for k, v in data.get("form_fields", {}).items():
            if isinstance(v, dict):
                fields_map[k] = FormFieldContract(**v)
            else:
                fields_map[k] = FormFieldContract(field_name=k)
        return cls(
            version=data.get("version", 1),
            mission_id=data.get("mission_id", ""),
            app_name=data.get("app_name", "Application"),
            app_type=data.get("app_type", "vanilla_web"),
            is_greenfield=data.get("is_greenfield", True),
            canonical_html=data.get("canonical_html", "index.html"),
            canonical_js=data.get("canonical_js", "app.js"),
            canonical_css=data.get("canonical_css", "style.css"),
            package_json_entry=data.get("package_json_entry"),
            required_files=data.get("required_files", ["index.html", "style.css", "app.js"]),
            required_ids=data.get("required_ids", []),
            form_fields=fields_map,
            storage_keys=data.get("storage_keys", {}),
            features=data.get("features", []),
            contract_hash=data.get("contract_hash", ""),
        )

    @classmethod
    def determine_canonical_js(
        cls,
        prompt: str = "",
        workspace_root: Optional[Path | str] = None,
    ) -> str:
        """
        Deterministically resolve the canonical JavaScript entrypoint name:
        1. Explicit user prompt request (e.g. 'app.js' vs 'main.js')
        2. Existing index.html <script src="..."> reference
        3. Existing package.json 'main' field
        4. Existing file on disk in workspace
        5. Deterministic default for new projects ('app.js' or 'main.js')
        """
        p_lower = (prompt or "").lower()
        ws = Path(workspace_root) if workspace_root else None

        # 1. Prompt explicit mentions
        has_app_js = "app.js" in p_lower
        has_main_js = "main.js" in p_lower
        if has_app_js and not has_main_js:
            return "app.js"
        if has_main_js and not has_app_js:
            return "main.js"

        # 2. Existing index.html on disk
        if ws and (ws / "index.html").exists():
            try:
                html_txt = (ws / "index.html").read_text(encoding="utf-8", errors="ignore")
                matches = re.findall(r'<script[^>]+src=["\']([^"\']+\.js)["\']', html_txt, re.I)
                for m in matches:
                    if not m.startswith(("http://", "https://", "//")):
                        clean = m.lstrip("./")
                        if clean in ("app.js", "main.js", "script.js", "index.js", "src/app.js", "src/main.js"):
                            return clean
            except Exception:
                pass

        # 3. Existing package.json 'main'
        if ws and (ws / "package.json").exists():
            try:
                pkg = json.loads((ws / "package.json").read_text(encoding="utf-8", errors="ignore"))
                main_val = pkg.get("main")
                if main_val and isinstance(main_val, str) and main_val.endswith(".js"):
                    return main_val.lstrip("./")
            except Exception:
                pass

        # 4. Existing file on disk
        if ws:
            for cand in ("app.js", "main.js", "src/app.js", "src/main.js"):
                if (ws / cand).exists() and (ws / cand).stat().st_size > 40:
                    return cand

        # 5. Default
        return "app.js" if has_app_js else ("main.js" if has_main_js else "app.js")

    @classmethod
    def create_or_load(
        cls,
        workspace_root: Path | str,
        mission_id: str = "",
        prompt: str = "",
    ) -> ProjectContract:
        """Create or load the persistent project contract from workspace."""
        ws = Path(workspace_root)
        contract_file = ws / ".hermes" / "project_contract.json"
        if contract_file.exists():
            try:
                data = json.loads(contract_file.read_text(encoding="utf-8", errors="ignore"))
                contract = cls.from_dict(data)
                if mission_id and not contract.mission_id:
                    contract.mission_id = mission_id
                return contract
            except Exception:
                pass

        # Derive new contract
        canonical_js = cls.determine_canonical_js(prompt, ws)
        app_name = "Application"
        for name_match in re.findall(r'(?:called|named)\s+\*?\*?([A-Za-z0-9_\-]+)\*?\*?', prompt, re.I):
            app_name = name_match
            break

        contract = cls(
            mission_id=mission_id,
            app_name=app_name,
            app_type="vanilla_web",
            is_greenfield=not any((ws / f).exists() for f in ("index.html", "package.json", "src")),
            canonical_html="index.html",
            canonical_js=canonical_js,
            canonical_css="style.css",
            required_files=["index.html", "style.css", canonical_js],
        )
        contract.save_to_workspace(ws)
        return contract

    def save_to_workspace(self, workspace_root: Path | str) -> Path:
        """Persist contract to .hermes/project_contract.json."""
        ws = Path(workspace_root)
        hermes_dir = ws / ".hermes"
        hermes_dir.mkdir(parents=True, exist_ok=True)
        contract_path = hermes_dir / "project_contract.json"
        self.contract_hash = self.compute_hash()
        contract_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return contract_path

    @classmethod
    def extract_dom_inventory(cls, workspace_root: Path | str) -> Dict[str, Any]:
        """
        Deterministically parse index.html and extract the authoritative DOM inventory:
        all IDs, classes, form input names, scripts, and stylesheet links.
        Saves inventory to .hermes/dom_contract.json.
        """
        ws = Path(workspace_root)
        html_path = ws / "index.html"
        if not html_path.exists():
            return {"ids": [], "classes": [], "form_names": [], "scripts": [], "stylesheets": []}

        try:
            txt = html_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return {"ids": [], "classes": [], "form_names": [], "scripts": [], "stylesheets": []}

        # Extract IDs
        raw_ids = re.findall(r'\bid=["\']([a-zA-Z0-9_\-]+)["\']', txt)
        ids = sorted(list(set(raw_ids)))

        # Extract Classes
        classes_set = set()
        for cm in re.findall(r'\bclass=["\']([^"\']+)["\']', txt):
            for c in cm.split():
                if c.strip():
                    classes_set.add(c.strip())
        classes = sorted(list(classes_set))

        # Extract form field names
        raw_names = re.findall(r'\bname=["\']([a-zA-Z0-9_\-]+)["\']', txt)
        form_names = sorted(list(set(raw_names)))

        # Extract script src
        scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', txt, re.I)

        # Extract stylesheets
        stylesheets = []
        for m in re.findall(r'<link[^>]+(?:href=["\']([^"\']+)["\'][^>]+rel=["\']stylesheet["\']|rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\'])', txt, re.I):
            stylesheets.append(m[0] or m[1])

        inventory = {
            "ids": ids,
            "classes": classes,
            "form_names": form_names,
            "scripts": scripts,
            "stylesheets": stylesheets,
            "ids_count": len(ids),
            "form_names_count": len(form_names),
        }

        # Persist
        hermes_dir = ws / ".hermes"
        hermes_dir.mkdir(parents=True, exist_ok=True)
        (hermes_dir / "dom_contract.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
        return inventory
