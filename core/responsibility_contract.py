# core/responsibility_contract.py
"""
Responsibility-Based Artifact Acceptance for HERMES (Section 9.1).
Replaces existence-only and crude byte-count gates with application responsibility contracts.
Enforces that full-stack deliverables fulfill functional responsibilities rather than mere presence on disk.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger


@dataclass
class ResponsibilityCheck:
    name: str
    fulfilled: bool
    description: str
    evidence: str = ""


@dataclass
class FileResponsibilityResult:
    filename: str
    fulfilled: bool
    checks: List[ResponsibilityCheck] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)


@dataclass
class ResponsibilityReport:
    valid: bool
    workspace_type: str  # "fullstack", "frontend_only", "backend_only", "python_cli"
    file_results: Dict[str, FileResponsibilityResult] = field(default_factory=dict)
    unmet_responsibilities: List[str] = field(default_factory=list)
    action_directives: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.valid:
            return f"All application responsibilities fulfilled for {self.workspace_type}."
        return (
            f"Responsibility contract failed for {self.workspace_type}: "
            f"{len(self.unmet_responsibilities)} unmet responsibility(ies)."
        )


class ResponsibilityContractEvaluator:
    """Evaluates workspace files against concrete architectural responsibilities."""

    @classmethod
    def evaluate_workspace(cls, workspace_root: Path | str) -> ResponsibilityReport:
        ws = Path(workspace_root).resolve()
        file_results: Dict[str, FileResponsibilityResult] = {}
        unmet: List[str] = []
        actions: List[str] = []

        has_backend = (ws / "main.py").exists() or (ws / "app.py").exists() or (ws / "server.py").exists()
        has_frontend = (
            (ws / "index.html").exists() or (ws / "static" / "index.html").exists() or
            (ws / "package.json").exists()
        )

        ws_type = "fullstack" if (has_backend and has_frontend) else ("backend_only" if has_backend else "frontend_only")

        # 1. Backend Responsibility: main.py / app.py / server.py
        if has_backend:
            be_file = ws / "main.py" if (ws / "main.py").exists() else (ws / "app.py" if (ws / "app.py").exists() else ws / "server.py")
            res_be = cls._evaluate_backend(be_file)
            file_results[be_file.name] = res_be
            if not res_be.fulfilled:
                for m in res_be.missing:
                    unmet.append(f"{be_file.name} missing responsibility: {m}")
                    actions.append(f"Implement {m} in {be_file.name}.")

        # 2. HTML Presentation Responsibility: index.html
        html_file = ws / "static" / "index.html" if (ws / "static" / "index.html").exists() else ws / "index.html"
        if html_file.exists():
            res_html = cls._evaluate_html(html_file)
            file_results[html_file.name] = res_html
            if not res_html.fulfilled:
                for m in res_html.missing:
                    unmet.append(f"{html_file.name} missing responsibility: {m}")
                    actions.append(f"Add {m} to {html_file.name}.")
        elif has_frontend:
            unmet.append("Missing index.html presentation structure")
            actions.append("Create index.html with complete semantic structure.")

        # 3. CSS Styling Responsibility: style.css
        css_file = (
            ws / "static" / "style.css" if (ws / "static" / "style.css").exists() else
            (ws / "style.css" if (ws / "style.css").exists() else None)
        )
        if css_file and css_file.exists():
            res_css = cls._evaluate_css(css_file)
            file_results[css_file.name] = res_css
            if not res_css.fulfilled:
                for m in res_css.missing:
                    unmet.append(f"{css_file.name} missing responsibility: {m}")
                    actions.append(f"Add {m} to {css_file.name}.")
        elif has_frontend:
            unmet.append("Missing style.css responsive styling")
            actions.append("Create style.css with complete component and responsive styles.")

        # 4. JavaScript Logic Responsibility: app.js / main.js
        js_file = (
            ws / "static" / "app.js" if (ws / "static" / "app.js").exists() else
            (ws / "static" / "main.js" if (ws / "static" / "main.js").exists() else
            (ws / "app.js" if (ws / "app.js").exists() else
            (ws / "main.js" if (ws / "main.js").exists() else None)))
        )
        if js_file and js_file.exists():
            res_js = cls._evaluate_js(js_file)
            file_results[js_file.name] = res_js
            if not res_js.fulfilled:
                for m in res_js.missing:
                    unmet.append(f"{js_file.name} missing responsibility: {m}")
                    actions.append(f"Implement complete logic for {m} in {js_file.name}.")
        elif has_frontend:
            unmet.append("Missing client-side logic script (app.js/main.js)")
            actions.append("Create app.js with complete client application logic.")

        # 5. Tests Responsibility: tests/ directory
        test_dir = ws / "tests"
        if test_dir.exists() and test_dir.is_dir():
            res_tests = cls._evaluate_tests(test_dir)
            file_results["tests"] = res_tests
            if not res_tests.fulfilled:
                for m in res_tests.missing:
                    unmet.append(f"tests/ missing responsibility: {m}")
                    actions.append(f"Add {m} in tests/ directory.")
        elif ws_type in ("fullstack", "backend_only"):
            unmet.append("tests/ directory missing automated test battery")
            actions.append("Create tests/ directory with isolated unit and contract tests.")

        return ResponsibilityReport(
            valid=len(unmet) == 0,
            workspace_type=ws_type,
            file_results=file_results,
            unmet_responsibilities=unmet,
            action_directives=actions,
        )

    @classmethod
    def _evaluate_backend(cls, be_file: Path) -> FileResponsibilityResult:
        content = be_file.read_text(encoding="utf-8", errors="ignore")
        checks: List[ResponsibilityCheck] = []
        missing: List[str] = []

        # Parse AST to inspect backend structure reliably without brittle regex
        tree: Optional[ast.AST] = None
        try:
            tree = ast.parse(content, filename=be_file.name)
        except Exception:
            pass

        # Check 1: Backend Routes
        routes_found: List[str] = []
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for dec in node.decorator_list:
                        dec_str = ast.unparse(dec) if hasattr(ast, "unparse") else ""
                        if any(k in dec_str for k in ("app.get", "app.post", "app.put", "app.delete", "router.")):
                            routes_found.append(node.name)
        else:
            routes_found = re.findall(r'@(?:app|router)\.(?:get|post|put|delete|patch)\(', content)

        has_routes = len(routes_found) >= 1
        checks.append(ResponsibilityCheck("backend_routes", has_routes, "Exposes REST endpoints", f"{len(routes_found)} routes"))
        if not has_routes:
            missing.append("REST API route handlers")

        # Check 2: Request/Response Schemas
        schemas_found: List[str] = []
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        base_str = ast.unparse(base) if hasattr(ast, "unparse") else ""
                        if "BaseModel" in base_str or "Schema" in base_str:
                            schemas_found.append(node.name)
        else:
            schemas_found = re.findall(r'class\s+([A-Za-z0-9_]+)\s*\(\s*BaseModel', content)

        has_schemas = len(schemas_found) >= 1
        checks.append(ResponsibilityCheck("request_schemas", has_schemas, "Pydantic data models for contract validation", f"{len(schemas_found)} models"))
        if not has_schemas:
            missing.append("Pydantic request/response validation schemas")

        # Check 3: Database Lifecycle
        has_db = any(k in content for k in ("sqlite3.connect", "get_db", "create_engine", "init_db", "PRAGMA foreign_keys"))
        checks.append(ResponsibilityCheck("database_lifecycle", has_db, "Database connection, initialization, or session lifecycle", "db lifecycle present" if has_db else ""))
        if not has_db:
            missing.append("Database connection lifecycle management")

        # Check 4: Static File Hosting / Root Handler
        has_static = any(k in content for k in ("StaticFiles", "mount(\"/static\"", "mount('/static'", "FileResponse", "@app.get(\"/\")", "@app.get('/')"))
        checks.append(ResponsibilityCheck("static_hosting", has_static, "Static asset mounting or index route", "static hosting configured" if has_static else ""))
        if not has_static:
            missing.append("Static asset hosting or root index handler")

        # Check 5: Runnable Entrypoint
        has_startup = "__main__" in content and "uvicorn.run" in content
        checks.append(ResponsibilityCheck("startup_entrypoint", has_startup, "Runnable uvicorn server startup entrypoint", "if __name__ == '__main__' present" if has_startup else ""))
        if not has_startup:
            missing.append("Runnable uvicorn startup entrypoint (if __name__ == '__main__')")

        return FileResponsibilityResult(
            filename=be_file.name,
            fulfilled=len(missing) == 0,
            checks=checks,
            missing=missing,
        )

    @classmethod
    def _evaluate_html(cls, html_file: Path) -> FileResponsibilityResult:
        content = html_file.read_text(encoding="utf-8", errors="ignore")
        checks: List[ResponsibilityCheck] = []
        missing: List[str] = []

        # Check 1: Multi-view or page containers
        has_pages = bool(re.search(r'<(?:section|div)[^>]+class=["\'][^"\']*(?:page|view|section)[^"\']*["\']', content, re.I)) or "page-view" in content
        checks.append(ResponsibilityCheck("page_sections", has_pages, "Semantic page or view sections", "view sections defined" if has_pages else ""))
        if not has_pages:
            missing.append("Semantic page/view sections for multi-view navigation")

        # Check 2: Forms or Interactive Inputs
        has_forms = "<form" in content.lower() or ("<input" in content.lower() and "<button" in content.lower())
        checks.append(ResponsibilityCheck("interactive_forms", has_forms, "Forms or inputs for user interaction", "form elements present" if has_forms else ""))
        if not has_forms:
            missing.append("Interactive forms or input controls")

        # Check 3: Navigation Links
        has_nav = "<nav" in content.lower() or "nav-item" in content or "data-page" in content
        checks.append(ResponsibilityCheck("navigation_elements", has_nav, "Navigation controls", "nav elements present" if has_nav else ""))
        if not has_nav:
            missing.append("Navigation controls or tab links")

        # Check 4: Modal or Feedback Container
        has_feedback = "modal" in content.lower() or "toast" in content.lower() or "alert" in content.lower()
        checks.append(ResponsibilityCheck("feedback_containers", has_feedback, "Modal or toast feedback container", "feedback containers present" if has_feedback else ""))
        if not has_feedback:
            missing.append("Modal dialog or notification feedback container")

        return FileResponsibilityResult(
            filename=html_file.name,
            fulfilled=len(missing) == 0,
            checks=checks,
            missing=missing,
        )

    @classmethod
    def _evaluate_css(cls, css_file: Path) -> FileResponsibilityResult:
        content = css_file.read_text(encoding="utf-8", errors="ignore")
        checks: List[ResponsibilityCheck] = []
        missing: List[str] = []

        # Check 1: Responsive Media Queries
        media_queries = re.findall(r'@media[^{]+', content)
        has_responsive = len(media_queries) >= 1
        checks.append(ResponsibilityCheck("responsive_breakpoints", has_responsive, "Responsive media queries", f"{len(media_queries)} media queries"))
        if not has_responsive:
            missing.append("Responsive media queries (@media) for multi-viewport layout")

        # Check 2: Layout Systems (Flexbox or Grid)
        has_layout = "display: flex" in content or "display: flexbox" in content or "display: grid" in content
        checks.append(ResponsibilityCheck("layout_rules", has_layout, "CSS Grid or Flexbox layout rules", "flex/grid present" if has_layout else ""))
        if not has_layout:
            missing.append("CSS Grid or Flexbox layout specifications")

        # Check 3: Form and Table Presentation
        has_components = any(k in content for k in (".btn", ".form-", "table", ".card", ".stat", "input"))
        checks.append(ResponsibilityCheck("component_styles", has_components, "Form, button, card, and table styling", "component styles present" if has_components else ""))
        if not has_components:
            missing.append("Component styles for buttons, forms, cards, and tables")

        # Check 4: Active / Hidden Visibility States
        has_states = any(k in content for k in (".active", ".hidden", "display: none", ":hover", ":focus"))
        checks.append(ResponsibilityCheck("interactive_states", has_states, "Active, hidden, hover, and focus states", "state styles present" if has_states else ""))
        if not has_states:
            missing.append("Active/hidden visibility rules and interactive hover states")

        return FileResponsibilityResult(
            filename=css_file.name,
            fulfilled=len(missing) == 0,
            checks=checks,
            missing=missing,
        )

    @classmethod
    def _evaluate_js(cls, js_file: Path) -> FileResponsibilityResult:
        content = js_file.read_text(encoding="utf-8", errors="ignore")
        checks: List[ResponsibilityCheck] = []
        missing: List[str] = []

        # Check 1: API Communication
        has_api = "fetch(" in content or "axios" in content or "XMLHttpRequest" in content or "api.get" in content
        checks.append(ResponsibilityCheck("api_communication", has_api, "HTTP client calls to backend", "API client present" if has_api else ""))
        if not has_api:
            missing.append("Backend API integration (fetch/XMLHttpRequest calls)")

        # Check 2: Event Handling & Form Processing
        has_events = "addEventListener" in content or "onclick" in content or "onsubmit" in content
        checks.append(ResponsibilityCheck("event_handling", has_events, "Event listeners for interactive actions", "event listeners present" if has_events else ""))
        if not has_events:
            missing.append("DOM event listeners and user interaction handlers")

        # Check 3: View Routing / Page Navigation
        has_nav = any(k in content for k in ("data-page", "navigateTo", "classList.add('active')", "classList.remove('active')", "hidden", "hash"))
        checks.append(ResponsibilityCheck("view_navigation", has_nav, "Single-page view switching logic", "page switching present" if has_nav else ""))
        if not has_nav:
            missing.append("Single-page view switching and navigation logic")

        # Check 4: Error Handling & User Notification
        has_errors = "catch" in content or "toast" in content.lower() or "alert(" in content or "console.error" in content
        checks.append(ResponsibilityCheck("error_handling", has_errors, "Error handling and visual feedback", "error handling present" if has_errors else ""))
        if not has_errors:
            missing.append("Error catching and user notification feedback")

        return FileResponsibilityResult(
            filename=js_file.name,
            fulfilled=len(missing) == 0,
            checks=checks,
            missing=missing,
        )

    @classmethod
    def _evaluate_tests(cls, test_dir: Path) -> FileResponsibilityResult:
        test_files = list(test_dir.glob("test_*.py")) + list(test_dir.glob("*_test.py"))
        checks: List[ResponsibilityCheck] = []
        missing: List[str] = []

        has_files = len(test_files) >= 1
        checks.append(ResponsibilityCheck("test_files", has_files, "Pytest test modules", f"{len(test_files)} test files"))
        if not has_files:
            missing.append("Test files named test_*.py")

        total_funcs = 0
        total_asserts = 0
        for tf in test_files:
            try:
                tree = ast.parse(tf.read_text(encoding="utf-8", errors="ignore"))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                        total_funcs += 1
                    elif isinstance(node, ast.Assert):
                        total_asserts += 1
            except Exception:
                pass

        has_funcs = total_funcs >= 2
        checks.append(ResponsibilityCheck("test_functions", has_funcs, "Test functions (test_*)", f"{total_funcs} test functions"))
        if not has_funcs:
            missing.append("At least 2 test functions asserting application behavior")

        has_asserts = total_asserts >= 2
        checks.append(ResponsibilityCheck("assertions", has_asserts, "Assertions validating contracts", f"{total_asserts} assertions"))
        if not has_asserts:
            missing.append("Assertions (assert statements) validating outcomes")

        return FileResponsibilityResult(
            filename="tests",
            fulfilled=len(missing) == 0,
            checks=checks,
            missing=missing,
        )
