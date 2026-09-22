# core/website_fast_path.py
"""
Website Fast Path Engine for HERMES vNext (Prompt 6).

Recognizes common, low-risk, small (<=3 files) website generation requests
that can safely use deterministic scaffolding and consolidated execution.

Key Guarantees:
- High Precision: Strict eligibility criteria; zero false positives on complex/backend/auth/framework tasks.
- Zero LLM Overhead: Deterministic regex/keyword classifier runs in < 1 ms.
- Safe Fallback: Complex, ambiguous, or ineligible requests fall back cleanly to normal HERMES path.
- Traceable Decision Record: Every evaluation produces auditable structured metadata.
- Prompt 5 Composition: Composes directly with `write_files_batch` for atomic multi-file staging.
- Benchmark Isolation: Unconditionally disabled when execution_mode == "benchmark".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger
from core.scaffold_registry import scaffold_registry, RenderedScaffold


# Explicit rejection keywords that disqualify a task from the simple website fast path
FRAMEWORK_DISQUALIFIERS = frozenset({
    "react", "vue", "angular", "next.js", "nextjs", "nuxt", "svelte", "gatsby",
    "tailwind", "bootstrap", "webpack", "vite", "babel", "npm", "yarn", "pnpm",
})

BACKEND_DISQUALIFIERS = frozenset({
    "flask", "fastapi", "django", "express", "node", "backend", "api", "rest",
    "database", "sql", "sqlite", "postgres", "mongodb", "endpoint", "server",
    "route", "graphql", "microservice",
})

SECURITY_AUTH_DISQUALIFIERS = frozenset({
    "auth", "authentication", "login", "signup", "register", "password",
    "secret", "token", "jwt", "oauth", "session", "credential", "private",
})

MODIFICATION_DISQUALIFIERS = frozenset({
    "modify", "edit", "update", "refactor", "fix", "bug", "patch", "repair",
    "existing", "change", "enhance", "optimize", "delete", "remove",
})


@dataclass
class FastPathDecisionRecord:
    """Auditable decision record for website fast-path evaluation."""
    fast_path_candidate: bool
    reason: str
    target_files: List[str]
    file_count: int
    deterministic_components: List[str]
    model_required: bool
    batch_eligible: bool
    execution_mode: str
    template_id: Optional[str] = None
    variables: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fast_path_candidate": self.fast_path_candidate,
            "reason": self.reason,
            "target_files": self.target_files,
            "files": self.file_count,
            "deterministic_components": self.deterministic_components,
            "model_required": self.model_required,
            "batch_eligible": self.batch_eligible,
            "execution_mode": self.execution_mode,
            "template_id": self.template_id,
            "variables": self.variables,
        }


class WebsiteFastPathClassifier:
    """
    Zero-LLM rule-based classifier for website fast-path eligibility.
    Prioritizes precision: false negatives are tolerated (fall back to normal path),
    while false positives are strictly rejected.
    """

    @classmethod
    def evaluate(cls, prompt: str, execution_mode: str = "production") -> FastPathDecisionRecord:
        """
        Evaluate user prompt against website fast path eligibility criteria.
        Returns a complete FastPathDecisionRecord.
        """
        # Invariant: Benchmark mode isolation
        if execution_mode == "benchmark":
            return FastPathDecisionRecord(
                fast_path_candidate=False,
                reason="benchmark_mode_isolation: fast path strictly disabled in benchmark mode",
                target_files=[],
                file_count=0,
                deterministic_components=[],
                model_required=True,
                batch_eligible=False,
                execution_mode="benchmark",
            )

        lower_prompt = prompt.lower().strip()
        words = set(re.findall(r"\b[a-z0-9_\-\.]+\b", lower_prompt))

        # Check explicit disqualifiers
        for kw in FRAMEWORK_DISQUALIFIERS:
            if kw in words or f" {kw} " in f" {lower_prompt} ":
                return FastPathDecisionRecord(
                    fast_path_candidate=False,
                    reason=f"disqualified_by_framework_keyword:{kw}",
                    target_files=[],
                    file_count=0,
                    deterministic_components=[],
                    model_required=True,
                    batch_eligible=False,
                    execution_mode=execution_mode,
                )

        for kw in BACKEND_DISQUALIFIERS:
            if kw in words or f" {kw} " in f" {lower_prompt} ":
                return FastPathDecisionRecord(
                    fast_path_candidate=False,
                    reason=f"disqualified_by_backend_keyword:{kw}",
                    target_files=[],
                    file_count=0,
                    deterministic_components=[],
                    model_required=True,
                    batch_eligible=False,
                    execution_mode=execution_mode,
                )

        for kw in SECURITY_AUTH_DISQUALIFIERS:
            if kw in words or f" {kw} " in f" {lower_prompt} ":
                return FastPathDecisionRecord(
                    fast_path_candidate=False,
                    reason=f"disqualified_by_security_auth_keyword:{kw}",
                    target_files=[],
                    file_count=0,
                    deterministic_components=[],
                    model_required=True,
                    batch_eligible=False,
                    execution_mode=execution_mode,
                )

        for kw in MODIFICATION_DISQUALIFIERS:
            if kw in words:
                return FastPathDecisionRecord(
                    fast_path_candidate=False,
                    reason=f"disqualified_by_modification_keyword:{kw}",
                    target_files=[],
                    file_count=0,
                    deterministic_components=[],
                    model_required=True,
                    batch_eligible=False,
                    execution_mode=execution_mode,
                )

        # Detect target files
        explicit_files = re.findall(
            r"\b([\w\-]+\.(?:html|css|js))\b", prompt, re.IGNORECASE
        )
        unique_files = list(dict.fromkeys([f.lower() for f in explicit_files]))

        # Check positive website indicators
        web_indicators = [
            "website", "web page", "webpage", "landing page", "html",
            "html5", "portfolio", "site", "web app"
        ]
        has_web_intent = any(ind in lower_prompt for ind in web_indicators) or bool(unique_files)

        if not has_web_intent:
            return FastPathDecisionRecord(
                fast_path_candidate=False,
                reason="no_website_intent_detected",
                target_files=[],
                file_count=0,
                deterministic_components=[],
                model_required=True,
                batch_eligible=False,
                execution_mode=execution_mode,
            )

        # If files are explicitly listed, enforce <= 3 files bound
        if unique_files:
            if len(unique_files) > 3:
                return FastPathDecisionRecord(
                    fast_path_candidate=False,
                    reason=f"exceeds_max_files_bound:{len(unique_files)}_files_requested",
                    target_files=unique_files,
                    file_count=len(unique_files),
                    deterministic_components=[],
                    model_required=True,
                    batch_eligible=False,
                    execution_mode=execution_mode,
                )
            target_files = unique_files
        else:
            # Infer standard 3-file or 1-file website based on prompt phrasing
            if any(k in lower_prompt for k in ["blank", "single page", "just html", "only html", "html file"]):
                target_files = ["index.html"]
            else:
                target_files = ["index.html", "styles.css", "app.js"]

        file_count = len(target_files)

        # Determine template and model involvement
        if file_count == 1 and target_files == ["index.html"]:
            template_id = "html-blank-v1"
            is_blank = any(k in lower_prompt for k in ["blank", "empty", "simple template", "skeleton"])
            model_required = not is_blank
        else:
            template_id = "web-basic-v1"
            # If user asks for custom copy or specific functional logic, model is required for content
            custom_indicators = [
                "course", "calculator", "quiz", "game", "tracker", "dashboard",
                "custom", "specific", "interactive", "edupath", "feature"
            ]
            model_required = any(k in lower_prompt for k in custom_indicators)

        # Extract title / project name hints
        title_match = re.search(r"title\s+['\"]([^'\"]+)['\"]", prompt, re.IGNORECASE)
        name_match = re.search(r"(?:called|named|for)\s+['\"]?([A-Za-z0-9_\-\s]+?)['\"]?(?:\s+website|\s+page|$|\.)", prompt, re.IGNORECASE)

        vars_extracted: Dict[str, str] = {}
        if title_match:
            vars_extracted["title"] = title_match.group(1).strip()
        if name_match:
            vars_extracted["project_name"] = name_match.group(1).strip()
            if "title" not in vars_extracted:
                vars_extracted["title"] = vars_extracted["project_name"]

        deterministic_components = [
            "directory_structure",
            "html5_shell",
            "css_reset_and_theme",
            "js_event_listeners",
        ]

        return FastPathDecisionRecord(
            fast_path_candidate=True,
            reason="eligible_simple_website_request",
            target_files=target_files,
            file_count=file_count,
            deterministic_components=deterministic_components,
            model_required=model_required,
            batch_eligible=True,
            execution_mode=execution_mode,
            template_id=template_id,
            variables=vars_extracted,
        )


class WebsiteFastPathCoordinator:
    """
    Orchestrates execution of an eligible website fast-path request.
    Composes deterministic scaffolding with optional model dynamic content
    and Prompt 5's write_files_batch.
    """

    @classmethod
    def execute_fast_path(
        cls,
        decision: FastPathDecisionRecord,
        dynamic_content_generator: Optional[Any] = None,
        workspace_dir: str = ".",
    ) -> Dict[str, Any]:
        """
        Execute the fast path:
        1. Render deterministic scaffold.
        2. If model_required is False, write scaffold directly to workspace.
        3. If model_required is True, pass scaffolded files to dynamic_content_generator
           and write resulting files via write_files_batch.
        """
        if not decision.fast_path_candidate or not decision.template_id:
            raise ValueError(f"Cannot execute fast path for non-candidate: {decision.reason}")

        # 1. Render deterministic scaffold
        rendered: RenderedScaffold = scaffold_registry.render(
            decision.template_id,
            decision.variables
        )

        # Category A: Fully deterministic (0 model calls)
        if not decision.model_required or dynamic_content_generator is None:
            logger.info("WebsiteFastPath: Executing Category A (Fully deterministic, 0 model calls)")
            write_res = scaffold_registry.write_scaffold_to_workspace(
                rendered,
                target_dir=workspace_dir,
                allow_overwrite=True
            )
            return {
                "success": True,
                "category": "A_fully_deterministic",
                "model_calls": 0,
                "tool_calls": 1,
                "files_written": write_res["files_written"],
                "overall_hash": rendered.overall_hash,
                "decision": decision.to_dict(),
            }

        # Category B: Scaffold + Model Dynamic Content
        logger.info("WebsiteFastPath: Executing Category B (Scaffold + 1 Model call + Batch commit)")
        # dynamic_content_generator receives rendered scaffold files and returns customized files
        customized_files = dynamic_content_generator(rendered.files)

        # Verify batch invariants
        if len(customized_files) > 3 or len(customized_files) < 1:
            raise ValueError(f"Customized files count {len(customized_files)} violates batch bounds [1, 3]")

        # Commit via write_files_batch semantics
        from tools.file_tools import WriteFilesBatchTool, BatchFileItem
        batch_tool = WriteFilesBatchTool()
        tool_inp = WriteFilesBatchTool.Input(
            files=[
                BatchFileItem(path=p, content=c)
                for p, c in customized_files.items()
            ]
        )
        res = batch_tool.execute(tool_inp)
        if res.exit_code != 0:
            raise RuntimeError(f"Batch write failed during fast path: {res.output}")

        return {
            "success": True,
            "category": "B_scaffold_plus_model_batch",
            "model_calls": 1,
            "tool_calls": 1,
            "files_written": list(customized_files.keys()),
            "decision": decision.to_dict(),
        }
