# core/architecture_lock.py
"""
Architecture Lock for HERMES 2.x.

Guarantees single continuous mission context and strict technology stack integrity.
Once an ArchitectureDecision is locked at mission start:
1. Framework and technology choices cannot be silently flipped or rediscovered per-file.
2. Contaminating imports (e.g. React/JSX in vanilla HTML/CSS/JS) are strictly prevented.
3. Skills contradicting the architecture (e.g. react-frontend for vanilla web) are filtered out.
4. Entrypoints, storage strategies, and file boundaries remain deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger


class ArchitectureType(str, Enum):
    VANILLA_WEB = "vanilla_web"      # Plain HTML5, CSS3, modern Vanilla JS (DOM API, localStorage)
    REACT_APP   = "react_app"        # React 18+, JSX/TSX, Tailwind, Next.js / Vite
    PYTHON_CLI  = "python_cli"       # Python CLI, click/argparse, single or multi-module Python
    FLASK_API   = "flask_api"        # Flask REST API, SQLAlchemy, pytest
    FASTAPI     = "fastapi"          # FastAPI REST API, Pydantic, pytest
    NODE_APP    = "node_app"         # Node.js backend/tool, Express, package.json
    GENERIC     = "generic"          # General software project


@dataclass
class ArchitectureDecision:
    """The authoritative architecture specification locked for a mission."""
    architecture_type: ArchitectureType = ArchitectureType.GENERIC
    language: str = "javascript"
    framework: str = "vanilla"
    entrypoint: str = "index.html"
    storage_strategy: str = "localStorage"
    allowed_extensions: List[str] = field(default_factory=lambda: [".html", ".css", ".js", ".json", ".md", ".txt"])
    disallowed_patterns: List[str] = field(default_factory=list)
    disallowed_skills: List[str] = field(default_factory=list)
    allowed_skills: List[str] = field(default_factory=list)
    description: str = ""

    def validate_file_content(self, file_path: str, content: str) -> Tuple[bool, List[str]]:
        """
        Check if content violates architectural invariants (e.g. React imports in vanilla JS).
        Returns (is_valid, list_of_violations).
        """
        violations: List[str] = []
        p_str = file_path.lower()

        # If architecture is VANILLA_WEB, check for React / JSX / bundler leakage
        if self.architecture_type == ArchitectureType.VANILLA_WEB:
            if p_str.endswith(".js") or p_str.endswith(".html"):
                react_patterns = [
                    (r"\bimport\s+React\b", "import React"),
                    (r"\bfrom\s+['\"]react['\"]", "from 'react'"),
                    (r"\bfrom\s+['\"]react-dom['\"]", "from 'react-dom'"),
                    (r"\brequire\s*\(\s*['\"]react['\"]\s*\)", "require('react')"),
                    (r"\buseState\s*\(", "useState (React hook in vanilla file)"),
                    (r"\buseEffect\s*\(", "useEffect (React hook in vanilla file)"),
                    (r"\bexport\s+default\b", "export default (module syntax in vanilla script)"),
                ]
                for pat, label in react_patterns:
                    if re.search(pat, content):
                        violations.append(f"Architectural contamination: {label} found in vanilla web file '{file_path}'")

        for pattern in self.disallowed_patterns:
            if pattern in content:
                violations.append(f"Disallowed pattern '{pattern}' detected in '{file_path}'")

        return len(violations) == 0, violations

    def sanitize_file_content(self, file_path: str, content: str) -> str:
        """
        Sanitize accidental framework contamination from file content.
        For example, strips React imports or export default statements from vanilla JS files.
        """
        if not content:
            return content

        sanitized = content
        p_str = file_path.lower()

        if self.architecture_type == ArchitectureType.VANILLA_WEB and p_str.endswith(".js"):
            # Strip React import lines
            lines = sanitized.splitlines()
            cleaned_lines = []
            for line in lines:
                l_strip = line.strip()
                if re.match(r"^import\s+.*?from\s+['\"]react.*?['\"];?$", l_strip):
                    continue
                if re.match(r"^import\s+React.*?$", l_strip):
                    continue
                if l_strip.startswith("export default "):
                    # Convert 'export default function foo()' to 'function foo()'
                    # or 'export default App;' to comment/nothing
                    cleaned = re.sub(r"^export\s+default\s+", "", l_strip)
                    if cleaned and not cleaned.endswith(";"):
                        cleaned_lines.append(cleaned)
                    continue
                cleaned_lines.append(line)
            sanitized = "\n".join(cleaned_lines)

        return sanitized

    def is_skill_allowed(self, skill_id: str) -> bool:
        """Check whether a skill is compatible with this locked architecture."""
        s_id = skill_id.lower().strip()
        if s_id in [s.lower() for s in self.disallowed_skills]:
            return False
        return True


class ArchitectureLock:
    """Session-level architecture lock coordinator."""
    _current_decision: Optional[ArchitectureDecision] = None
    _mission_id: Optional[str] = None

    @classmethod
    def lock(cls, decision: ArchitectureDecision, mission_id: str = "") -> None:
        """Lock the architecture decision for the active mission."""
        cls._current_decision = decision
        cls._mission_id = mission_id
        logger.info(
            f"ArchitectureLock: LOCKED {decision.architecture_type.value} | "
            f"entrypoint={decision.entrypoint} | framework={decision.framework} | "
            f"mission={mission_id or 'default'}"
        )

    @classmethod
    def get_current(cls) -> ArchitectureDecision:
        """Get the current locked decision, or a default generic decision."""
        if cls._current_decision is None:
            return ArchitectureDecision()
        return cls._current_decision

    @classmethod
    def release(cls) -> None:
        """Release the architecture lock."""
        cls._current_decision = None
        cls._mission_id = None


def detect_architecture(
    prompt: str,
    workspace_root: Optional[Path | str] = None,
) -> ArchitectureDecision:
    """
    Establish early authoritative ArchitectureDecision from prompt and workspace ground truth.
    Prevents mid-mission stack flipping and cross-stack contamination.
    """
    p_lower = prompt.lower()

    # 1. Inspect existing files in workspace if present
    if workspace_root:
        ws_p = Path(workspace_root).resolve()
        if ws_p.exists() and ws_p.is_dir():
            files = [f.name.lower() for f in ws_p.iterdir() if f.is_file() and not f.name.startswith(".")]
            if "index.html" in files:
                has_package_json = "package.json" in files
                if not has_package_json:
                    return ArchitectureDecision(
                        architecture_type=ArchitectureType.VANILLA_WEB,
                        language="javascript",
                        framework="vanilla",
                        entrypoint="index.html",
                        storage_strategy="localStorage",
                        allowed_extensions=[".html", ".css", ".js", ".json", ".svg", ".png"],
                        disallowed_patterns=["import React", "from 'react'", "from \"react\""],
                        disallowed_skills=["react-frontend"],
                        allowed_skills=["vanilla-web"],
                        description="Vanilla HTML5/CSS3/JavaScript web application (standalone, browser-native)",
                    )

    # 2. React / Next.js / JSX explicit cues
    is_explicit_react = any(kw in p_lower for kw in [
        "react", "next.js", "nextjs", "jsx", "tsx", "react component", "create-react-app", "vite react"
    ])
    if is_explicit_react:
        return ArchitectureDecision(
            architecture_type=ArchitectureType.REACT_APP,
            language="typescript" if ("typescript" in p_lower or "tsx" in p_lower) else "javascript",
            framework="react",
            entrypoint="src/App.tsx" if "typescript" in p_lower else "src/App.jsx",
            storage_strategy="state/context",
            allowed_extensions=[".jsx", ".tsx", ".js", ".ts", ".css", ".json", ".html"],
            allowed_skills=["react-frontend"],
            description="React application with component state and hooks",
        )

    # 3. Flask API explicit cues
    is_flask = any(kw in p_lower for kw in ["flask", "flask-rest-api", "flask api"])
    if is_flask:
        return ArchitectureDecision(
            architecture_type=ArchitectureType.FLASK_API,
            language="python",
            framework="flask",
            entrypoint="run.py",
            storage_strategy="sqlite",
            allowed_extensions=[".py", ".sql", ".txt", ".json", ".md"],
            disallowed_skills=["react-frontend"],
            allowed_skills=["flask-rest-api", "pytest-generation", "database-design"],
            description="Flask REST API backend service",
        )

    # 4. FastAPI explicit cues
    is_fastapi = any(kw in p_lower for kw in ["fastapi", "uvicorn"])
    if is_fastapi:
        return ArchitectureDecision(
            architecture_type=ArchitectureType.FASTAPI,
            language="python",
            framework="fastapi",
            entrypoint="main.py",
            storage_strategy="sqlite",
            allowed_extensions=[".py", ".sql", ".txt", ".json", ".md"],
            disallowed_skills=["react-frontend"],
            allowed_skills=["pytest-generation"],
            description="FastAPI async backend service",
        )

    # 5. Website / Web Application cues (without explicit React) -> Authoritative VANILLA_WEB
    is_web = any(kw in p_lower for kw in [
        "website", "web app", "web application", "webpage", "landing page",
        "campus lost and found", "lost-and-found", "lost and found",
        "portfolio", "html", "css", "vanilla", "frontend", "ui", "browser",
        "dashboard", "board", "kanban", "tracker", "calculator", "console",
    ])
    if is_web:
        return ArchitectureDecision(
            architecture_type=ArchitectureType.VANILLA_WEB,
            language="javascript",
            framework="vanilla",
            entrypoint="index.html",
            storage_strategy="localStorage",
            allowed_extensions=[".html", ".css", ".js", ".json", ".svg", ".png", ".jpg", ".txt", ".md"],
            disallowed_patterns=["import React", "from 'react'", "from \"react\""],
            disallowed_skills=["react-frontend"],
            allowed_skills=["vanilla-web"],
            description="Vanilla HTML5/CSS3/JavaScript web application (standalone, browser-native)",
        )

    # 6. Python CLI cues
    is_python = any(kw in p_lower for kw in [
        "python", ".py", "script", "cli", "command line", "hello.py", "test-pipeline"
    ])
    if is_python:
        return ArchitectureDecision(
            architecture_type=ArchitectureType.PYTHON_CLI,
            language="python",
            framework="standard_library",
            entrypoint="main.py",
            storage_strategy="json_file",
            allowed_extensions=[".py", ".txt", ".json", ".md"],
            disallowed_skills=["react-frontend", "vanilla-web"],
            allowed_skills=["pytest-generation"],
            description="Python command-line application or script",
        )

    # Default generic
    return ArchitectureDecision(
        architecture_type=ArchitectureType.GENERIC,
        language="any",
        framework="generic",
        entrypoint="index.html",
        storage_strategy="file",
        allowed_extensions=[".py", ".js", ".html", ".css", ".json", ".md", ".txt"],
        description="Generic software engineering mission",
    )
