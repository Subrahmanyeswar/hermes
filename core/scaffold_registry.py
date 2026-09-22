# core/scaffold_registry.py
"""
Deterministic Scaffolding Engine for HERMES vNext (Prompt 6).

Generates deterministic project and file skeletons without LLM inference
where the requested structure is known, standard, and generic.

Key Guarantees:
- Deterministic: Same template ID + same variables produces identical output bit-for-bit.
- Hashable: Every template and rendered file set has a verifiable SHA-256 digest.
- Secure: Plain-data variable interpolation only; arbitrary code execution or eval is strictly rejected.
- Safe Filesystem Policy: Respects workspace boundaries, pre-validates paths, and enforces overwrite protection.
- Benchmark Isolated: Never auto-activated in benchmark execution mode.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger
from core.workspace import workspace_manager, WorkspaceBoundaryError


# Permitted plain-data variable names across templates
ALLOWED_VARIABLE_NAMES = frozenset({
    "project_name",
    "title",
    "description",
    "author",
    "primary_color",
    "app_name",
    "version",
})

# Forbidden patterns in variable values (code injection, script tags, escape sequences)
FORBIDDEN_VALUE_PATTERNS = [
    re.compile(r"<\s*script\b", re.IGNORECASE),
    re.compile(r"\{\{.*\}\}"),
    re.compile(r"eval\s*\(", re.IGNORECASE),
    re.compile(r"exec\s*\(", re.IGNORECASE),
    re.compile(r"__import__", re.IGNORECASE),
    re.compile(r"\.\./"),  # Directory traversal attempt inside variable
    re.compile(r"\\x[0-9a-fA-F]{2}"),  # Hex escape
    re.compile(r"\\0"),  # Null byte escape
]


@dataclass(frozen=True)
class ScaffoldFileSpec:
    """Specification of a single file produced by a deterministic scaffold."""
    rel_path: str
    content_template: str
    content_type: str  # 'html', 'css', 'javascript', 'python', 'json'


@dataclass
class ScaffoldTemplate:
    """Versioned, hashable deterministic scaffold template definition."""
    template_id: str
    version: int
    description: str
    files: List[ScaffoldFileSpec]
    allowed_variables: Set[str]
    template_hash: str = field(init=False)

    def __post_init__(self):
        raw_repr = f"{self.template_id}:{self.version}:" + ":".join(
            f"{f.rel_path}::{f.content_template}" for f in sorted(self.files, key=lambda x: x.rel_path)
        )
        object.__setattr__(self, "template_hash", hashlib.sha256(raw_repr.encode("utf-8")).hexdigest())


@dataclass
class RenderedScaffold:
    """Output of rendering a deterministic scaffold."""
    template_id: str
    template_version: int
    template_hash: str
    variables: Dict[str, str]
    files: Dict[str, str]  # rel_path -> rendered content
    file_hashes: Dict[str, str]  # rel_path -> sha256
    overall_hash: str
    file_count: int


class ScaffoldRegistry:
    """
    Controlled registry for deterministic scaffolding templates.
    Ensures safe, bounded, reproducible skeleton generation.
    """

    def __init__(self):
        self._templates: Dict[str, ScaffoldTemplate] = {}
        self._register_default_templates()

    def register(self, template: ScaffoldTemplate) -> None:
        if template.template_id in self._templates:
            logger.warning(
                "ScaffoldRegistry: Overwriting template '{}' (v{}) with v{}",
                template.template_id, self._templates[template.template_id].version, template.version
            )
        self._templates[template.template_id] = template

    def get_template(self, template_id: str) -> Optional[ScaffoldTemplate]:
        return self._templates.get(template_id)

    def list_templates(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": t.template_id,
                "version": t.version,
                "description": t.description,
                "files": [f.rel_path for f in t.files],
                "allowed_variables": sorted(list(t.allowed_variables)),
                "template_hash": t.template_hash,
            }
            for t in sorted(self._templates.values(), key=lambda x: x.template_id)
        ]

    def validate_variables(self, template: ScaffoldTemplate, variables: Dict[str, Any]) -> Dict[str, str]:
        clean_vars: Dict[str, str] = {}
        for key, val in variables.items():
            if key not in template.allowed_variables:
                raise ValueError(
                    f"Variable '{key}' is not allowed for scaffold '{template.template_id}'. "
                    f"Allowed: {sorted(list(template.allowed_variables))}"
                )

            if not isinstance(val, (str, int, float)):
                raise ValueError(f"Variable '{key}' must be a string or number, got {type(val).__name__}")

            val_str = str(val).strip()
            if len(val_str) > 500:
                raise ValueError(f"Variable '{key}' exceeds maximum allowed length of 500 characters")

            for pattern in FORBIDDEN_VALUE_PATTERNS:
                if pattern.search(val_str):
                    raise ValueError(
                        f"Variable '{key}' contains forbidden character sequence or potential code injection: '{val_str[:50]}'"
                    )

            sanitized = val_str.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            clean_vars[key] = sanitized

        return clean_vars

    def render(self, template_id: str, variables: Optional[Dict[str, Any]] = None) -> RenderedScaffold:
        template = self.get_template(template_id)
        if not template:
            raise KeyError(f"Scaffold template '{template_id}' is not registered.")

        clean_vars = self.validate_variables(template, variables or {})

        defaults = {
            "project_name": "Project",
            "title": "Welcome",
            "description": "Generated by HERMES Autonomous SWE Engine",
            "primary_color": "#2563eb",
            "author": "HERMES",
            "app_name": "App",
            "version": "1.0.0",
        }

        merged_vars = {**defaults, **clean_vars}
        rendered_files: Dict[str, str] = {}
        file_hashes: Dict[str, str] = {}

        for f_spec in sorted(template.files, key=lambda x: x.rel_path):
            content = f_spec.content_template
            for v_name, v_val in sorted(merged_vars.items()):
                token = f"{{{v_name}}}"
                content = content.replace(token, v_val)

            rendered_files[f_spec.rel_path] = content
            file_hashes[f_spec.rel_path] = hashlib.sha256(content.encode("utf-8")).hexdigest()

        overall_repr = ":".join(f"{p}={file_hashes[p]}" for p in sorted(rendered_files.keys()))
        overall_hash = hashlib.sha256(overall_repr.encode("utf-8")).hexdigest()

        return RenderedScaffold(
            template_id=template.template_id,
            template_version=template.version,
            template_hash=template.template_hash,
            variables=clean_vars,
            files=rendered_files,
            file_hashes=file_hashes,
            overall_hash=overall_hash,
            file_count=len(rendered_files),
        )

    def write_scaffold_to_workspace(
        self,
        rendered: RenderedScaffold,
        target_dir: str = ".",
        allow_overwrite: bool = False,
    ) -> Dict[str, Any]:
        target_base = Path(target_dir)
        written_paths: List[str] = []

        for rel_path in rendered.files.keys():
            full_rel = str(target_base / rel_path).replace("\\", "/")
            dest_path = workspace_manager.validate_path(full_rel)

            if dest_path.exists() and not allow_overwrite:
                raise FileExistsError(
                    f"Scaffold write rejected: File '{full_rel}' already exists and allow_overwrite=False"
                )

        for rel_path, content in rendered.files.items():
            full_rel = str(target_base / rel_path).replace("\\", "/")
            dest_path = workspace_manager.validate_path(full_rel)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_text(content, encoding="utf-8")
            written_paths.append(full_rel)

        try:
            workspace_manager.refresh_index()
        except Exception as e:
            logger.warning("ScaffoldRegistry: Index refresh warning: {}", e)

        return {
            "success": True,
            "template_id": rendered.template_id,
            "overall_hash": rendered.overall_hash,
            "files_written": written_paths,
            "file_hashes": rendered.file_hashes,
        }

    def _register_default_templates(self) -> None:
        blank_html_content = (
            "<!DOCTYPE html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '    <meta charset="UTF-8">\n'
            '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            "    <title>{title}</title>\n"
            "</head>\n"
            "<body>\n"
            "    <main>\n"
            "        <h1>{title}</h1>\n"
            "        <p>{description}</p>\n"
            "    </main>\n"
            "</body>\n"
            "</html>\n"
        )
        self.register(ScaffoldTemplate(
            template_id="html-blank-v1",
            version=1,
            description="Single-file clean semantic HTML5 document shell",
            files=[
                ScaffoldFileSpec(rel_path="index.html", content_template=blank_html_content, content_type="html")
            ],
            allowed_variables={"title", "description"},
        ))

        web_html_content = (
            "<!DOCTYPE html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '    <meta charset="UTF-8">\n'
            '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            "    <title>{title}</title>\n"
            '    <link rel="stylesheet" href="styles.css">\n'
            "</head>\n"
            "<body>\n"
            '    <header class="site-header">\n'
            "        <nav>\n"
            '            <div class="logo">{project_name}</div>\n'
            "        </nav>\n"
            "    </header>\n"
            '    <main id="app" class="container">\n'
            '        <section class="hero">\n'
            "            <h1>{title}</h1>\n"
            "            <p>{description}</p>\n"
            '            <button id="cta-button" class="btn">Get Started</button>\n'
            "        </section>\n"
            '        <section id="content" class="content-grid">\n'
            "            <!-- Dynamic content injected here -->\n"
            "        </section>\n"
            "    </main>\n"
            "    <footer>\n"
            "        <p>&copy; 2026 {project_name}. All rights reserved.</p>\n"
            "    </footer>\n"
            '    <script src="app.js"></script>\n'
            "</body>\n"
            "</html>\n"
        )

        web_css_content = (
            "/* Basic responsive styles and reset */\n"
            ":root {\n"
            "    --primary-color: {primary_color};\n"
            "    --bg-color: #f8fafc;\n"
            "    --text-color: #1e293b;\n"
            "    --card-bg: #ffffff;\n"
            "    --font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;\n"
            "}\n"
            "\n"
            "* {\n"
            "    box-sizing: border-box;\n"
            "    margin: 0;\n"
            "    padding: 0;\n"
            "}\n"
            "\n"
            "body {\n"
            "    font-family: var(--font-family);\n"
            "    background-color: var(--bg-color);\n"
            "    color: var(--text-color);\n"
            "    line-height: 1.6;\n"
            "}\n"
            "\n"
            ".container {\n"
            "    max-width: 1024px;\n"
            "    margin: 0 auto;\n"
            "    padding: 2rem 1rem;\n"
            "}\n"
            "\n"
            ".site-header {\n"
            "    background-color: #ffffff;\n"
            "    border-bottom: 1px solid #e2e8f0;\n"
            "    padding: 1rem 2rem;\n"
            "}\n"
            "\n"
            ".logo {\n"
            "    font-weight: 700;\n"
            "    font-size: 1.25rem;\n"
            "    color: var(--primary-color);\n"
            "}\n"
            "\n"
            ".hero {\n"
            "    text-align: center;\n"
            "    padding: 3rem 1rem;\n"
            "}\n"
            "\n"
            ".hero h1 {\n"
            "    font-size: 2.25rem;\n"
            "    margin-bottom: 1rem;\n"
            "}\n"
            "\n"
            ".btn {\n"
            "    background-color: var(--primary-color);\n"
            "    color: #ffffff;\n"
            "    border: none;\n"
            "    padding: 0.75rem 1.5rem;\n"
            "    border-radius: 0.375rem;\n"
            "    font-weight: 600;\n"
            "    cursor: pointer;\n"
            "    margin-top: 1.5rem;\n"
            "}\n"
            "\n"
            ".btn:hover {\n"
            "    opacity: 0.9;\n"
            "}\n"
            "\n"
            "footer {\n"
            "    text-align: center;\n"
            "    padding: 2rem;\n"
            "    font-size: 0.875rem;\n"
            "    color: #64748b;\n"
            "}\n"
        )

        web_js_content = (
            "// Application logic initialization\n"
            "document.addEventListener('DOMContentLoaded', () => {\n"
            "    console.log('{project_name} initialized');\n"
            "    const cta = document.getElementById('cta-button');\n"
            "    if (cta) {\n"
            "        cta.addEventListener('click', () => {\n"
            "            alert('{project_name} action triggered!');\n"
            "        });\n"
            "    }\n"
            "});\n"
        )

        self.register(ScaffoldTemplate(
            template_id="web-basic-v1",
            version=1,
            description="Standard 3-file web project (index.html, styles.css, app.js)",
            files=[
                ScaffoldFileSpec(rel_path="index.html", content_template=web_html_content, content_type="html"),
                ScaffoldFileSpec(rel_path="styles.css", content_template=web_css_content, content_type="css"),
                ScaffoldFileSpec(rel_path="app.js", content_template=web_js_content, content_type="javascript"),
            ],
            allowed_variables={"project_name", "title", "description", "primary_color"},
        ))

        py_main_content = (
            '"""Main entry point for {project_name}."""\n'
            "from config import Config\n"
            "from utils import setup_logger\n"
            "\n"
            "logger = setup_logger(__name__)\n"
            "\n"
            "def main():\n"
            '    logger.info("Starting {project_name} v{version}")\n'
            '    print("Welcome to {project_name}")\n'
            "\n"
            'if __name__ == "__main__":\n'
            "    main()\n"
        )

        py_utils_content = (
            '"""Utility helper functions for {project_name}."""\n'
            "import logging\n"
            "\n"
            "def setup_logger(name: str) -> logging.Logger:\n"
            "    logger = logging.getLogger(name)\n"
            "    if not logger.handlers:\n"
            "        handler = logging.StreamHandler()\n"
            '        formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")\n'
            "        handler.setFormatter(formatter)\n"
            "        logger.addHandler(handler)\n"
            "        logger.setLevel(logging.INFO)\n"
            "    return logger\n"
        )

        py_config_content = (
            '"""Configuration parameters for {project_name}."""\n'
            "from dataclasses import dataclass\n"
            "\n"
            "@dataclass(frozen=True)\n"
            "class Config:\n"
            '    APP_NAME: str = "{project_name}"\n'
            '    VERSION: str = "{version}"\n'
            '    DEBUG: bool = False\n'
        )

        self.register(ScaffoldTemplate(
            template_id="python-basic-v1",
            version=1,
            description="Minimal clean Python project (main.py, utils.py, config.py)",
            files=[
                ScaffoldFileSpec(rel_path="main.py", content_template=py_main_content, content_type="python"),
                ScaffoldFileSpec(rel_path="utils.py", content_template=py_utils_content, content_type="python"),
                ScaffoldFileSpec(rel_path="config.py", content_template=py_config_content, content_type="python"),
            ],
            allowed_variables={"project_name", "version"},
        ))


scaffold_registry = ScaffoldRegistry()
