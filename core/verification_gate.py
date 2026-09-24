# core/verification_gate.py
"""
Progressive Verification Gate for HERMES vNext.
Eliminates unnecessary Tier 2 LLM verification on deterministic, structural,
and read-only operations while preserving semantic verification for complex tasks,
security-sensitive actions, and ambiguous outcomes.

Hierarchy:
  Level 0: Deterministic validation (Filesystem, exit codes, output matching)
  Level 1: Local structural checks (Python AST parse, JSON schema/syntax validation)
  Level 2: Tier 2 Qwen3 Semantic LLM verification (Complex coding, refactoring, debugging)
  Level 3: Tier 3 Ox Alpha Cloud arbitration (Disagreements, high-risk security, destructive actions)
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from loguru import logger
from core.verifier import VerificationResult, Tier2Verifier
from config.model_config import PROGRESSIVE_VERIFICATION_ENABLED


class ToolRiskCategory(Enum):
    READ_ONLY = "read_only"
    LOW_RISK_WRITE = "low_risk_write"
    MEDIUM_RISK_WRITE = "medium_risk_write"
    HIGH_RISK_WRITE = "high_risk_write"
    DESTRUCTIVE = "destructive"
    UNKNOWN = "unknown"


# Tool classification registry
TOOL_RISK_MAP: Dict[str, ToolRiskCategory] = {
    # Read-only tools
    "list_directory": ToolRiskCategory.READ_ONLY,
    "read_file": ToolRiskCategory.READ_ONLY,
    "search_files": ToolRiskCategory.READ_ONLY,
    "file_exists": ToolRiskCategory.READ_ONLY,
    "git_status": ToolRiskCategory.READ_ONLY,
    "git_log": ToolRiskCategory.READ_ONLY,
    "git_diff": ToolRiskCategory.READ_ONLY,
    "web_search": ToolRiskCategory.READ_ONLY,
    "read_url": ToolRiskCategory.READ_ONLY,

    # Low-risk write tools
    "write_file": ToolRiskCategory.LOW_RISK_WRITE,
    "create_file": ToolRiskCategory.LOW_RISK_WRITE,
    "write_files_batch": ToolRiskCategory.LOW_RISK_WRITE,

    # Medium-risk write tools
    "patch_file": ToolRiskCategory.MEDIUM_RISK_WRITE,
    "git_commit": ToolRiskCategory.MEDIUM_RISK_WRITE,

    # High-risk & execution tools
    "execute_command": ToolRiskCategory.HIGH_RISK_WRITE,
    "python_eval": ToolRiskCategory.HIGH_RISK_WRITE,
    "package_install": ToolRiskCategory.HIGH_RISK_WRITE,

    # Destructive tools
    "delete_file": ToolRiskCategory.DESTRUCTIVE,
    "git_push": ToolRiskCategory.DESTRUCTIVE,
}

# Task-level security keywords that escalate risk regardless of tool used
SECURITY_KEYWORDS = frozenset({
    "credential", "password", "secret", "token", "api_key", "private_key",
    "exfiltrate", "drop table", "drop database", "rm -rf", "delete database",
    "authentication", "auth", "exploit", "vulnerability", "bypass"
})

# Semantic reasoning keywords that indicate complex logic requiring Tier 2
SEMANTIC_REASONING_KEYWORDS = frozenset({
    "refactor", "bug", "fix", "resolve issue", "algorithm", "optimize",
    "concurrency", "race condition", "memory leak", "security flaw",
    "regression", "unit test logic", "mocking", "architecture"
})


@dataclass
class VerificationEvidence:
    """Structured evidence collected during deterministic and structural verification."""
    tool_name: str
    tool_parameters: Dict[str, Any]
    tool_success: bool
    exit_code: int
    task_description: str
    tool_category: ToolRiskCategory
    deterministic_passed: bool = True
    structural_passed: bool = True
    is_semantic_required: bool = False
    is_security_sensitive: bool = False
    confidence: float = 1.0
    risk_score: float = 0.0
    checks_run: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)


class VerificationGate:
    """
    Centralized decision gate for progressive verification.
    Determines whether Level 0/1 local verification is sufficient
    or if Level 2 (Tier 2 Qwen3) / Level 3 (Tier 3 Ox Alpha) must be invoked.
    """

    def __init__(self, enabled: bool = PROGRESSIVE_VERIFICATION_ENABLED):
        self.enabled = enabled
        logger.info("VerificationGate initialized | progressive_enabled={}", self.enabled)

    def classify_tool(self, tool_name: str) -> ToolRiskCategory:
        """Classify tool risk category, defaulting unknown tools to UNKNOWN (conservative)."""
        return TOOL_RISK_MAP.get(tool_name, ToolRiskCategory.UNKNOWN)

    def analyze_task_risk(self, task_description: str) -> Tuple[bool, bool]:
        """Analyze task description for security sensitivity and semantic complexity."""
        # If task_description contains enriched context wrapper (e.g. from MissionRunner),
        # extract the actual core user task to avoid false positives from injected skill rules (like "never use rm -rf").
        text = task_description.lower()
        core_task = text
        if "description:" in text:
            core_task = text.split("description:", 1)[1]
            if "acceptance:" in core_task:
                core_task = core_task.split("acceptance:", 1)[0]
        elif "task to execute:" in text:
            core_task = text.split("task to execute:", 1)[1]
            if "success criterion:" in core_task:
                core_task = core_task.split("success criterion:", 1)[0]
        elif "task:" in text and "rules:" in text:
            core_task = text.split("task:", 1)[1]
            if "success criterion:" in core_task:
                core_task = core_task.split("success criterion:", 1)[0]

        is_security_sensitive = any(kw in core_task for kw in SECURITY_KEYWORDS)
        is_semantic_required = any(kw in core_task for kw in SEMANTIC_REASONING_KEYWORDS)
        return is_security_sensitive, is_semantic_required

    def run_deterministic_checks(
        self,
        tool_name: str,
        tool_parameters: Dict[str, Any],
        tool_result_output: str,
        tool_exit_code: int,
        tool_success: bool
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Execute Level 0 deterministic filesystem and state checks.
        Returns: (passed, checks_run, issues)
        """
        checks_run = []
        issues = []

        # General execution success check
        checks_run.append("check_exit_code_zero")
        if tool_exit_code != 0 or not tool_success:
            issues.append(f"Tool execution failed with exit_code={tool_exit_code}")
            return False, checks_run, issues

        from core.workspace import workspace_manager
        def _resolve_p(p: str) -> Path:
            if workspace_manager.is_locked and workspace_manager.workspace_root and not Path(p).is_absolute():
                return Path(workspace_manager.workspace_root) / p
            return Path(p)

        # Tool-specific deterministic checks
        if tool_name == "list_directory":
            checks_run.append("check_directory_exists")
            path = tool_parameters.get("path", ".")
            full_p = _resolve_p(path)
            if not full_p.exists():
                issues.append(f"Target directory does not exist: {path}")
            elif not full_p.is_dir():
                issues.append(f"Target path is not a directory: {path}")

        elif tool_name in ("read_file", "file_exists"):
            checks_run.append("check_file_exists_on_disk")
            path = tool_parameters.get("path") or tool_parameters.get("file_path") or ""
            if path and not _resolve_p(path).exists():
                issues.append(f"Target file does not exist on disk: {path}")

        elif tool_name == "search_files":
            checks_run.append("check_search_results_valid")
            if not isinstance(tool_result_output, str):
                issues.append("Search output is not a valid string")

        elif tool_name in ("git_status", "git_log", "git_diff"):
            checks_run.append("check_git_clean_exit")
            # Exit code 0 check was already performed

        elif tool_name == "write_file":
            checks_run.append("check_written_file_exists_and_non_empty")
            path = tool_parameters.get("path") or tool_parameters.get("file_path") or ""
            if path:
                full_p = _resolve_p(path)
                if not full_p.exists():
                    issues.append(f"Expected created file not found on disk: {path}")
                else:
                    file_size = full_p.stat().st_size
                    if file_size == 0 and len(tool_parameters.get("content", "")) > 0:
                        issues.append(f"File {path} is 0 bytes despite content being provided")

        elif tool_name == "write_files_batch":
            checks_run.append("check_batch_files_exist_and_non_empty")
            files = tool_parameters.get("files") or []
            for item in files:
                if isinstance(item, dict):
                    p = item.get("path") or item.get("file_path") or ""
                    c = item.get("content", "")
                    if p:
                        full_p = _resolve_p(p)
                        if not full_p.exists():
                            issues.append(f"Expected created batch file not found on disk: {p}")
                        else:
                            file_size = full_p.stat().st_size
                            if file_size == 0 and len(c) > 0:
                                issues.append(f"Batch file {p} is 0 bytes despite content being provided")

        passed = len(issues) == 0
        return passed, checks_run, issues

    def _validate_python_contracts(
        self,
        path_str: str,
        content: str,
        checks_run: List[str],
        issues: List[str]
    ) -> None:
        """
        Validate Python module import contracts and test suite execution.
        Detects API mismatches (e.g. importing class methods as standalone functions)
        and runs pytest on test suites if present.
        """
        from core.workspace import workspace_manager
        ws_root = Path(workspace_manager.workspace_root) if (workspace_manager.is_locked and workspace_manager.workspace_root) else Path.cwd()

        code_to_parse = content
        if "\\n" in code_to_parse and "\n" not in code_to_parse:
            try:
                code_to_parse = code_to_parse.encode("utf-8").decode("unicode_escape")
            except Exception:
                pass

        try:
            tree = ast.parse(code_to_parse, filename=path_str)
        except Exception:
            return

        # 1. Check imports against workspace modules
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mod_name = node.module
                mod_candidates = [
                    ws_root / f"{mod_name}.py",
                    ws_root / mod_name / "__init__.py",
                    ws_root / "generated_projects" / f"{mod_name}.py",
                    Path(path_str).parent / f"{mod_name}.py",
                    Path(path_str).parent / "generated_projects" / f"{mod_name}.py"
                ]
                target_file = None
                for cand in mod_candidates:
                    if cand.exists() and cand.is_file():
                        target_file = cand
                        break

                if target_file:
                    checks_run.append(f"import_contract_check:{mod_name}")
                    try:
                        target_ast = ast.parse(target_file.read_text(encoding="utf-8"), filename=str(target_file))
                        top_level_defs = set()
                        class_methods: Dict[str, str] = {}

                        for stmt in target_ast.body:
                            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                top_level_defs.add(stmt.name)
                            elif isinstance(stmt, ast.ClassDef):
                                top_level_defs.add(stmt.name)
                                for sub in stmt.body:
                                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                        class_methods[sub.name] = stmt.name
                            elif isinstance(stmt, ast.Assign):
                                for target in stmt.targets:
                                    if isinstance(target, ast.Name):
                                        top_level_defs.add(target.id)
                            elif isinstance(stmt, ast.AnnAssign):
                                if isinstance(stmt.target, ast.Name):
                                    top_level_defs.add(stmt.target.id)

                        for alias in node.names:
                            if alias.name == "*":
                                continue
                            if alias.name not in top_level_defs:
                                if alias.name in class_methods:
                                    cls_name = class_methods[alias.name]
                                    issues.append(
                                        f"API contract mismatch in {path_str}: '{alias.name}' is imported as a standalone function from '{mod_name}', but it is defined as a method inside class '{cls_name}'. Use 'from {mod_name} import {cls_name}' and instantiate '{cls_name}()'."
                                    )
                                else:
                                    issues.append(
                                        f"API contract mismatch in {path_str}: '{alias.name}' is not exported by module '{mod_name}'."
                                    )
                    except Exception as e:
                        logger.debug("Failed parsing target module {}: {}", target_file, e)
                else:
                    # Target file not found locally. Check if it is a standard library or installed third-party package
                    import importlib.util
                    is_known = mod_name in sys.builtin_module_names
                    if not is_known:
                        try:
                            is_known = importlib.util.find_spec(mod_name) is not None
                        except Exception:
                            is_known = False
                    if not is_known:
                        checks_run.append(f"import_contract_check:{mod_name}")
                        suggestion = ""
                        gen_dir = ws_root / "generated_projects"
                        if gen_dir.exists():
                            for p in gen_dir.glob("*.py"):
                                if mod_name in p.stem or p.stem in mod_name:
                                    suggestion = f" Did you mean '{p.stem}' from '{p.relative_to(ws_root)}'?"
                                    break
                        issues.append(
                            f"Import error in {path_str}: No module named '{mod_name}' found in workspace or python environment.{suggestion}"
                        )

        # 2. Test execution verification
        file_p = Path(path_str)
        if not file_p.is_absolute() and ws_root:
            file_p = ws_root / path_str

        # If this is a test file, execute it using pytest in the workspace environment
        if file_p.name.startswith("test_") or file_p.name.endswith("_test.py"):
            checks_run.append(f"test_execution_check:{file_p.name}")
            import tempfile
            temp_file = None
            try:
                # Write candidate code_to_parse to a temporary test file in target directory so relative imports work
                file_p.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=f"_{file_p.name}",
                    prefix="tmp_verify_",
                    dir=str(file_p.parent),
                    delete=False,
                    encoding="utf-8"
                ) as tf:
                    tf.write(code_to_parse)
                    temp_file = Path(tf.name)

                env = os.environ.copy()
                pp = os.pathsep.join(filter(None, [str(ws_root), str(file_p.parent), env.get("PYTHONPATH", "")]))
                env["PYTHONPATH"] = pp

                proc = subprocess.run(
                    [sys.executable, "-m", "pytest", str(temp_file), "-q", "--tb=short"],
                    cwd=str(ws_root),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                if proc.returncode != 0:
                    raw_out = (proc.stdout or "") + "\n" + (proc.stderr or "")
                    lines = [line.strip() for line in raw_out.splitlines() if line.strip() and not line.startswith("=")]
                    summary = " | ".join(lines[-3:]) if lines else "pytest returned non-zero exit code"
                    issues.append(f"Test suite execution failed ({file_p.name}): {summary}")
            except subprocess.TimeoutExpired:
                issues.append(f"Test suite execution timed out (>15s) for {file_p.name}")
            except Exception as e:
                logger.debug("Test execution check encountered error: {}", e)
            finally:
                if temp_file and temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass

    def run_structural_checks(
        self,
        tool_name: str,
        tool_parameters: Dict[str, Any]
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Execute Level 1 structural and AST parsing checks.
        Returns: (passed, checks_run, issues)
        """
        checks_run = []
        issues = []

        if tool_name == "write_file":
            path = str(tool_parameters.get("path") or tool_parameters.get("file_path") or "")
            content = tool_parameters.get("content", "")

            # Python syntax / AST validation
            if path.endswith(".py") and content:
                checks_run.append("python_ast_parse")
                # Handle raw escaped string literals if model generated literal \n
                code_to_parse = content
                if "\\n" in code_to_parse and "\n" not in code_to_parse:
                    try:
                        code_to_parse = code_to_parse.encode("utf-8").decode("unicode_escape")
                    except Exception:
                        pass
                try:
                    ast.parse(code_to_parse, filename=path)
                    self._validate_python_contracts(path, code_to_parse, checks_run, issues)
                except SyntaxError as e:
                    # Also try reading directly from disk if file was already written
                    disk_parsed = False
                    try:
                        from pathlib import Path
                        p_file = Path(path)
                        if p_file.exists():
                            disk_content = p_file.read_text(encoding="utf-8")
                            ast.parse(disk_content, filename=path)
                            disk_parsed = True
                            self._validate_python_contracts(path, disk_content, checks_run, issues)
                    except Exception:
                        pass
                    if not disk_parsed:
                        issues.append(f"Python syntax error in {path} at line {e.lineno}: {e.msg}")
                except Exception as e:
                    issues.append(f"AST parse failed for {path}: {e}")

            # JSON syntax validation
            elif path.endswith(".json") and content:
                checks_run.append("json_syntax_parse")
                try:
                    json.loads(content)
                except Exception as e:
                    issues.append(f"JSON syntax error in {path}: {e}")

            # HTML structure check
            elif path.endswith((".html", ".htm")) and content:
                checks_run.append("html_structure_check")
                if not content.strip() or "<" not in content or ">" not in content:
                    issues.append(f"HTML file {path} missing valid markup tags")

            # CSS syntax validation
            elif path.endswith(".css") and content:
                checks_run.append("css_syntax_check")
                if content.count("{") != content.count("}"):
                    issues.append(f"CSS syntax error in {path}: mismatched curly braces")

            # JS syntax validation
            elif path.endswith(".js") and content:
                checks_run.append("js_syntax_check")
                if content.count("{") != content.count("}"):
                    issues.append(f"JS syntax error in {path}: mismatched curly braces")

        elif tool_name == "write_files_batch":
            files = tool_parameters.get("files") or []
            for item in files:
                if isinstance(item, dict):
                    path = str(item.get("path") or item.get("file_path") or "")
                    content = item.get("content", "")
                    if path.endswith(".py") and content:
                        checks_run.append(f"python_ast_parse:{path}")
                        code_to_parse = content
                        if "\\n" in code_to_parse and "\n" not in code_to_parse:
                            try:
                                code_to_parse = code_to_parse.encode("utf-8").decode("unicode_escape")
                            except Exception:
                                pass
                        try:
                            ast.parse(code_to_parse, filename=path)
                            self._validate_python_contracts(path, code_to_parse, checks_run, issues)
                        except SyntaxError as e:
                            issues.append(f"Python syntax error in batch file {path} at line {e.lineno}: {e.msg}")
                        except Exception as e:
                            issues.append(f"AST parse failed for batch file {path}: {e}")
                    elif path.endswith(".json") and content:
                        checks_run.append(f"json_syntax_parse:{path}")
                        try:
                            json.loads(content)
                        except Exception as e:
                            issues.append(f"JSON syntax error in batch file {path}: {e}")
                    elif path.endswith((".html", ".htm")) and content:
                        checks_run.append(f"html_structure_check:{path}")
                        if not content.strip() or "<" not in content or ">" not in content:
                            issues.append(f"HTML file {path} missing valid markup tags")
                    elif path.endswith(".css") and content:
                        checks_run.append(f"css_syntax_check:{path}")
                        if content.count("{") != content.count("}"):
                            issues.append(f"CSS syntax error in {path}: mismatched curly braces")
                    elif path.endswith(".js") and content:
                        checks_run.append(f"js_syntax_check:{path}")
                        if content.count("{") != content.count("}"):
                            issues.append(f"JS syntax error in {path}: mismatched curly braces")

        passed = len(issues) == 0
        return passed, checks_run, issues

    async def run_parallel_structural_checks(
        self,
        files: List[Dict[str, Any]]
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Execute Level 1 structural checks concurrently across multiple files
        using BoundedExecutor (max_workers=2).
        """
        from core.bounded_executor import bounded_executor, BoundedTask, ResourceClass

        def _check_single(item: Dict[str, Any]) -> Tuple[str, Optional[str]]:
            path = str(item.get("path") or item.get("file_path") or "")
            content = item.get("content", "")
            if path.endswith(".py") and content:
                try:
                    code_to_parse = content
                    if "\\n" in code_to_parse and "\n" not in code_to_parse:
                        try:
                            code_to_parse = code_to_parse.encode("utf-8").decode("unicode_escape")
                        except Exception:
                            pass
                    ast.parse(code_to_parse, filename=path)
                    return f"python_ast_parse:{path}", None
                except Exception as e:
                    return f"python_ast_parse:{path}", f"Python syntax error in {path}: {e}"
            elif path.endswith(".json") and content:
                try:
                    json.loads(content)
                    return f"json_syntax_parse:{path}", None
                except Exception as e:
                    return f"json_syntax_parse:{path}", f"JSON syntax error in {path}: {e}"
            elif path.endswith((".html", ".htm")) and content:
                if not content.strip() or "<" not in content or ">" not in content:
                    return f"html_structure_check:{path}", f"HTML file {path} missing valid markup"
                return f"html_structure_check:{path}", None
            elif path.endswith(".css") and content:
                if content.count("{") != content.count("}"):
                    return f"css_syntax_check:{path}", f"CSS syntax error in {path}: mismatched curly braces"
                return f"css_syntax_check:{path}", None
            elif path.endswith(".js") and content:
                if content.count("{") != content.count("}"):
                    return f"js_syntax_check:{path}", f"JS syntax error in {path}: mismatched curly braces"
                return f"js_syntax_check:{path}", None
            return f"generic_check:{path}", None

        tasks = [
            BoundedTask(
                task_id=f"struct_check_{i}",
                func=_check_single,
                args=(item,),
                resource_class=ResourceClass.CPU
            )
            for i, item in enumerate(files)
        ]

        records = await bounded_executor.execute_batch(tasks, refresh_index_barrier=False)
        checks_run = []
        issues = []
        for r in records:
            if r.success and r.result:
                check_name, issue = r.result
                checks_run.append(check_name)
                if issue:
                    issues.append(issue)
            elif not r.success:
                issues.append(f"Structural verification worker failure: {r.error}")

        return len(issues) == 0, checks_run, issues

    async def evaluate(
        self,
        task_description: str,
        tier1_reasoning: str,
        tool_name: str,
        tool_parameters: Dict[str, Any],
        tool_result_output: str,
        tool_exit_code: int,
        tool_success: bool,
        verifier: Tier2Verifier,
        task_complexity: float = 0.5,
        execution_mode: str = "production"
    ) -> Tuple[VerificationResult, str]:
        """
        Evaluate verification for a completed tool call.
        Returns: (VerificationResult, verification_method_str)
        """
        # Benchmark isolation rule: Benchmark mode retains 100% frozen execution semantics
        if execution_mode == "benchmark":
            logger.debug("VerificationGate: execution_mode='benchmark', preserving frozen Tier 2 LLM verification")
            res = await verifier.verify(
                task=task_description,
                tier1_reasoning=tier1_reasoning,
                tool_name=tool_name,
                tool_parameters=tool_parameters,
                tool_result_output=tool_result_output[:600],
                tool_exit_code=tool_exit_code
            )
            return res, "BENCHMARK_FROZEN_T2"

        # Feature flag check: If disabled, run full Tier 2 verification
        if not self.enabled:
            logger.debug("VerificationGate: progressive verification disabled, using Tier 2 LLM")
            res = await verifier.verify(
                task=task_description,
                tier1_reasoning=tier1_reasoning,
                tool_name=tool_name,
                tool_parameters=tool_parameters,
                tool_result_output=tool_result_output[:600],
                tool_exit_code=tool_exit_code
            )
            return res, "LEGACY_T2_FULL"

        # 1. Classify tool risk & task risk
        tool_category = self.classify_tool(tool_name)
        is_security, is_semantic = self.analyze_task_risk(task_description)

        # 2. Run Level 0 Deterministic Checks
        det_passed, det_checks, det_issues = self.run_deterministic_checks(
            tool_name=tool_name,
            tool_parameters=tool_parameters,
            tool_result_output=tool_result_output,
            tool_exit_code=tool_exit_code,
            tool_success=tool_success
        )

        # 3. Run Level 1 Structural Checks
        struct_passed, struct_checks, struct_issues = self.run_structural_checks(
            tool_name=tool_name,
            tool_parameters=tool_parameters
        )

        all_issues = det_issues + struct_issues
        all_checks = det_checks + struct_checks

        import inspect
        async def _call_verifier_safe(**kwargs):
            val = verifier.verify(**kwargs)
            if inspect.isawaitable(val):
                return await val
            return val

        # Gating Decision Logic:
        # Case A: Deterministic/Structural Failure -> If local checks failed, immediately trigger Level 2 or fail
        if not det_passed or not struct_passed:
            logger.warning(
                "VerificationGate: local checks failed on {} | issues={}. Invoking Tier 2 for diagnostic.",
                tool_name, all_issues
            )
            fail_msg = f"LOCAL CHECKS FAILED: {all_issues}\n\n{tool_result_output[:500]}"
            res = await _call_verifier_safe(
                task=task_description,
                tier1_reasoning=tier1_reasoning,
                tool_name=tool_name,
                tool_parameters=tool_parameters,
                tool_result_output=fail_msg,
                tool_exit_code=tool_exit_code
            )
            # Ensure issues from local checks are preserved in result and agree is False
            res.agree = False
            res.critical_issues.extend(all_issues)
            return res, "T2_DIAGNOSTIC_FAILURE"

        # Case B: High Security or Destructive Tasks -> Always require Tier 2
        if is_security or tool_category in (ToolRiskCategory.DESTRUCTIVE, ToolRiskCategory.HIGH_RISK_WRITE, ToolRiskCategory.UNKNOWN):
            logger.info(
                "VerificationGate: Security/Destructive/Unknown operation (tool={}, category={}). Invoking Tier 2.",
                tool_name, tool_category.value
            )
            res = await _call_verifier_safe(
                task=task_description,
                tier1_reasoning=tier1_reasoning,
                tool_name=tool_name,
                tool_parameters=tool_parameters,
                tool_result_output=tool_result_output[:600],
                tool_exit_code=tool_exit_code
            )
            return res, "T2_SECURITY_SENSITIVE"

        # Case C: Semantic Reasoning Required (e.g. refactoring, debugging, complex logic) -> Require Tier 2
        if is_semantic or task_complexity >= 0.7:
            logger.info(
                "VerificationGate: Semantic reasoning required for task '{}'. Invoking Tier 2.",
                task_description[:50]
            )
            res = await _call_verifier_safe(
                task=task_description,
                tier1_reasoning=tier1_reasoning,
                tool_name=tool_name,
                tool_parameters=tool_parameters,
                tool_result_output=tool_result_output[:600],
                tool_exit_code=tool_exit_code
            )
            return res, "T2_SEMANTIC_REASONING"

        # Case D: Read-Only Tool with 100% Deterministic Pass -> Level 0 Fast Path (No T2!)
        if tool_category == ToolRiskCategory.READ_ONLY:
            logger.info(
                "VerificationGate: READ_ONLY tool '{}' verified deterministically. Bypassing Tier 2.",
                tool_name
            )
            res = VerificationResult(
                agree=True,
                confidence=1.0,
                critical_issues=[],
                risk_score=0.02,
                reasoning=f"Verified deterministically via VerificationGate: {all_checks}",
                quality_verdict="COMPLETE",
                quality_findings=["Deterministic filesystem verification succeeded"],
                missing_requirements=[],
                latency_seconds=0.001,
                model_used="deterministic_gate"
            )
            return res, "LOCAL_DETERMINISTIC"

        # Case E: Low-Risk Write Tool (e.g. create simple file) with 100% AST & File Pass -> Level 1 Fast Path (No T2!)
        if tool_category == ToolRiskCategory.LOW_RISK_WRITE and det_passed and struct_passed:
            logger.info(
                "VerificationGate: Low-risk write '{}' verified structurally (AST+disk). Bypassing Tier 2.",
                tool_name
            )
            res = VerificationResult(
                agree=True,
                confidence=0.98,
                critical_issues=[],
                risk_score=0.05,
                reasoning=f"Verified structurally & deterministically via VerificationGate: {all_checks}",
                quality_verdict="COMPLETE",
                quality_findings=["Structural AST and filesystem verification succeeded"],
                missing_requirements=[],
                latency_seconds=0.002,
                model_used="structural_gate"
            )
            return res, "LOCAL_STRUCTURAL"

        # Default fallback: If any ambiguity remains, conservatively invoke Tier 2
        logger.info("VerificationGate: Conservative fallback to Tier 2 for tool '{}'", tool_name)
        res = await verifier.verify(
            task=task_description,
            tier1_reasoning=tier1_reasoning,
            tool_name=tool_name,
            tool_parameters=tool_parameters,
            tool_result_output=tool_result_output[:600],
            tool_exit_code=tool_exit_code
        )
        return res, "T2_CONSERVATIVE_FALLBACK"
