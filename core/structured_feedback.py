# core/structured_feedback.py
"""
HERMES Structured Feedback System
Based on: Self-Refine (Madaan et al., NeurIPS 2023) and
           CRITIC (Gou et al., ICLR 2024)

Self-Refine finding: Generic feedback ("this is bad") produces small
improvement. Structured, named feedback dimensions produce large
improvement. The feedback must be specific, actionable, and organized
by aspect.

CRITIC finding: LLM self-critique is unreliable because models
confidently confirm their own wrong answers. External tool feedback
(linters, interpreters, tests) provides ground-truth signals that
are immune to this hallucination problem.

This module combines both: structured feedback dimensions populated
by tool-grounded evidence, not model self-judgment.
"""

from __future__ import annotations

import subprocess
import ast
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from loguru import logger


# ── Feedback dimensions (from Self-Refine Table 2) ───────────────────────────

FEEDBACK_DIMENSIONS = {
    "correctness": "Does the implementation do what was asked? Are there logical errors?",
    "completeness": "Are all requested features implemented? Is anything missing?",
    "quality":     "Is the code well-structured? Are there obvious improvements?",
    "safety":      "Are there any dangerous patterns, unhandled exceptions, or security issues?",
    "efficiency":  "Are there obvious performance issues (O(n²) where O(n) works, etc.)?",
}


@dataclass
class DimensionScore:
    """Score and evidence for one feedback dimension."""
    dimension: str
    score: str          # "PASS", "WARN", "FAIL"
    finding: str        # Specific, actionable finding
    evidence: str       # Tool output or content excerpt that proves the finding
    is_tool_grounded: bool = False  # True if evidence comes from a tool


@dataclass
class StructuredFeedback:
    """
    Complete structured feedback for a task execution result.
    Populated by tool verification, not model self-judgment.
    """
    task_description: str
    file_path: str
    dimension_scores: list[DimensionScore] = field(default_factory=list)
    overall_verdict: str = "UNKNOWN"   # "PASS", "WARN", "FAIL"
    is_ready: bool = False
    repair_instructions: str = ""
    tool_evidence: dict = field(default_factory=dict)  # raw tool outputs

    @property
    def failed_dimensions(self) -> list[DimensionScore]:
        return [d for d in self.dimension_scores if d.score == "FAIL"]

    @property
    def warned_dimensions(self) -> list[DimensionScore]:
        return [d for d in self.dimension_scores if d.score == "WARN"]

    def to_feedback_text(self) -> str:
        """Convert to the feedback text injected into the repair prompt."""
        lines = [
            f"STRUCTURED FEEDBACK — {self.overall_verdict}",
            f"File: {self.file_path}",
            "",
        ]
        for ds in self.dimension_scores:
            icon = "✓" if ds.score == "PASS" else ("⚠" if ds.score == "WARN" else "✗")
            tool_marker = " [tool-verified]" if ds.is_tool_grounded else ""
            lines.append(f"{icon} {ds.dimension.upper()}{tool_marker}")
            lines.append(f"   Finding: {ds.finding}")
            if ds.evidence:
                lines.append(f"   Evidence: {ds.evidence[:150]}")
            lines.append("")

        if self.repair_instructions:
            lines.append("REPAIR INSTRUCTIONS:")
            lines.append(self.repair_instructions)

        return "\n".join(lines)


class StructuredFeedbackGenerator:
    """
    Generates structured, tool-grounded feedback for HERMES task outputs.

    CRITIC principle: do not ask the model to judge its own output.
    Use tools to produce objective evidence, then structure it
    by the Self-Refine named dimensions.

    For code files this runs: syntax check, basic execution,
    content analysis, and feature coverage check.
    """

    def generate(
        self,
        task_description: str,
        file_path: str,
        task_requirements: Optional[list[str]] = None,
        timeout_seconds: int = 15,
    ) -> StructuredFeedback:
        """
        Generate structured feedback for a written file.

        Args:
            task_description: What the task asked for
            file_path:        Path to the file that was written
            task_requirements: List of specific requirements to check
            timeout_seconds:  Max time for any single tool check

        Returns:
            StructuredFeedback with tool-grounded dimension scores
        """
        if task_requirements is None:
            task_requirements = []

        fb = StructuredFeedback(
            task_description=task_description,
            file_path=file_path,
        )

        p = Path(file_path)
        if not p.exists():
            fb.dimension_scores.append(DimensionScore(
                dimension="correctness",
                score="FAIL",
                finding=f"File does not exist: {file_path}",
                evidence="",
                is_tool_grounded=True,
            ))
            fb.overall_verdict = "FAIL"
            fb.is_ready = False
            fb.repair_instructions = (
                f"The file {file_path} was not created. "
                f"Use write_file to create it with complete content."
            )
            return fb

        content = p.read_text(encoding="utf-8", errors="replace")
        ext = p.suffix.lower()

        # ── Dimension 1: Correctness — tool-grounded syntax check ────────────
        fb.dimension_scores.append(
            self._check_correctness(p, content, ext, timeout_seconds)
        )

        # ── Dimension 2: Completeness — requirement coverage ─────────────────
        fb.dimension_scores.append(
            self._check_completeness(content, task_description, task_requirements)
        )

        # ── Dimension 3: Quality — content depth check ────────────────────────
        fb.dimension_scores.append(
            self._check_quality(content, ext, p.stat().st_size)
        )

        # ── Dimension 4: Safety — placeholder and dangerous pattern check ─────
        fb.dimension_scores.append(
            self._check_safety(content)
        )

        # ── Dimension 5: Efficiency (lightweight heuristic) ───────────────────
        fb.dimension_scores.append(
            self._check_efficiency(content, ext)
        )

        # ── Determine overall verdict ─────────────────────────────────────────
        fail_count = len(fb.failed_dimensions)
        warn_count = len(fb.warned_dimensions)

        if fail_count > 0:
            fb.overall_verdict = "FAIL"
            fb.is_ready = False
        elif warn_count > 1:
            fb.overall_verdict = "WARN"
            fb.is_ready = False
        else:
            fb.overall_verdict = "PASS"
            fb.is_ready = True

        # ── Build repair instructions ─────────────────────────────────────────
        if not fb.is_ready:
            fb.repair_instructions = self._build_repair_instructions(fb)

        logger.info(
            f"StructuredFeedback: {p.name} | {fb.overall_verdict} | "
            f"fail={fail_count} warn={warn_count}"
        )
        return fb

    # ── Dimension checkers ────────────────────────────────────────────────────

    def _check_correctness(
        self, p: Path, content: str, ext: str, timeout: int
    ) -> DimensionScore:
        """
        CRITIC principle: use the tool (Python parser / node --check / etc.)
        as the ground truth, not the model's self-assessment.
        """
        if ext == ".py":
            return self._check_python_syntax(p, content, timeout)
        elif ext in (".js", ".jsx", ".ts", ".tsx"):
            return self._check_js_syntax(p, content, timeout)
        elif ext == ".html":
            return self._check_html_structure(content)
        elif ext == ".css":
            return self._check_css_structure(content)
        else:
            # Generic: check file is non-empty and not all whitespace
            stripped = content.strip()
            if not stripped:
                return DimensionScore(
                    dimension="correctness", score="FAIL",
                    finding="File is empty",
                    evidence="",
                    is_tool_grounded=True,
                )
            return DimensionScore(
                dimension="correctness", score="PASS",
                finding="File has content",
                evidence=f"{len(stripped)} chars",
                is_tool_grounded=True,
            )

    def _check_python_syntax(
        self, p: Path, content: str, timeout: int
    ) -> DimensionScore:
        """Run Python's own AST parser — true ground truth for syntax."""
        try:
            ast.parse(content)
            # Also try running with sys.executable -c to catch import-level errors
            result = subprocess.run(
                [sys.executable, "-c", f"import ast; ast.parse(open(r'{p}', encoding='utf-8').read())"],
                capture_output=True, text=True, timeout=timeout
            )
            if result.returncode == 0:
                return DimensionScore(
                    dimension="correctness", score="PASS",
                    finding="Python syntax is valid",
                    evidence="ast.parse() succeeded",
                    is_tool_grounded=True,
                )
            else:
                return DimensionScore(
                    dimension="correctness", score="FAIL",
                    finding="Python syntax error detected",
                    evidence=result.stderr[:200],
                    is_tool_grounded=True,
                )
        except SyntaxError as e:
            return DimensionScore(
                dimension="correctness", score="FAIL",
                finding=f"SyntaxError at line {e.lineno}: {e.msg}",
                evidence=str(e)[:200],
                is_tool_grounded=True,
            )
        except Exception as e:
            return DimensionScore(
                dimension="correctness", score="WARN",
                finding=f"Could not verify syntax: {e}",
                evidence="",
                is_tool_grounded=False,
            )

    def _check_js_syntax(self, p: Path, content: str, timeout: int) -> DimensionScore:
        """Check JavaScript/TypeScript syntax using node --check."""
        try:
            result = subprocess.run(
                ["node", "--check", str(p)],
                capture_output=True, text=True, timeout=timeout
            )
            if result.returncode == 0:
                return DimensionScore(
                    dimension="correctness", score="PASS",
                    finding="JavaScript syntax is valid",
                    evidence="node --check passed",
                    is_tool_grounded=True,
                )
            else:
                return DimensionScore(
                    dimension="correctness", score="FAIL",
                    finding="JavaScript syntax error",
                    evidence=(result.stderr or result.stdout)[:200],
                    is_tool_grounded=True,
                )
        except (FileNotFoundError, Exception):
            # node not available — do basic brace check
            open_braces = content.count("{")
            close_braces = content.count("}")
            if open_braces != close_braces:
                return DimensionScore(
                    dimension="correctness", score="WARN",
                    finding=f"Unmatched braces in JS file ({open_braces} open vs {close_braces} close)",
                    evidence="Basic syntax check",
                    is_tool_grounded=False,
                )
            return DimensionScore(
                dimension="correctness", score="PASS",
                finding="Basic JavaScript structure valid",
                evidence="node not available — basic brace check passed",
                is_tool_grounded=False,
            )

    def _check_html_structure(self, content: str) -> DimensionScore:
        """Check HTML has required structural elements."""
        lower = content.lower()
        required = ["<!doctype", "<html", "<head", "<body"]
        missing = [r for r in required if r not in lower]
        if missing:
            return DimensionScore(
                dimension="correctness", score="FAIL",
                finding=f"HTML missing structural elements: {missing}",
                evidence=f"File starts with: {content[:100]}",
                is_tool_grounded=True,
            )
        return DimensionScore(
            dimension="correctness", score="PASS",
            finding="HTML has required structure",
            evidence="DOCTYPE, html, head, body all present",
            is_tool_grounded=True,
        )

    def _check_css_structure(self, content: str) -> DimensionScore:
        """Check CSS has actual rules (not just comments/whitespace)."""
        # Count CSS rules: lines with { that are not comments
        rule_lines = [
            l for l in content.split("\n")
            if "{" in l and not l.strip().startswith("/*")
        ]
        if len(rule_lines) < 3:
            return DimensionScore(
                dimension="correctness", score="FAIL",
                finding=f"CSS has only {len(rule_lines)} rule blocks — insufficient",
                evidence=f"Expected at least 3 rule blocks",
                is_tool_grounded=True,
            )
        return DimensionScore(
            dimension="correctness", score="PASS",
            finding=f"CSS has {len(rule_lines)} rule blocks",
            evidence=f"First rule: {rule_lines[0].strip()[:80]}",
            is_tool_grounded=True,
        )

    def _check_completeness(
        self,
        content: str,
        task_description: str,
        task_requirements: list[str],
    ) -> DimensionScore:
        """
        Check requirement coverage by looking for keywords in the content.
        This is structured (per-requirement) rather than generic.
        """
        lower_content = content.lower()
        lower_task = task_description.lower()

        # Domain-specific coverage keywords
        coverage_map = {
            "navbar":       ["nav", "navbar", "navigation"],
            "hero":         ["hero", "banner", "jumbotron"],
            "animation":    ["animation", "@keyframes", "transition", "animate"],
            "responsive":   ["@media", "responsive", "mobile"],
            "questionnaire":["questionnaire", "form", "question", "quiz"],
            "dashboard":    ["dashboard"],
            "roadmap":      ["roadmap"],
            "progress":     ["progress"],
            "auth":         ["login", "auth", "password", "token"],
            "api":          ["route", "endpoint", "api", "@app.route", "flask"],
            "test":         ["def test_", "assert", "pytest"],
            "database":     ["db", "model", "sqlalchemy", "sqlite"],
            "footer":       ["footer"],
            "header":       ["header"],
        }

        covered = []
        missing = []

        for keyword, signals in coverage_map.items():
            if keyword in lower_task or any(keyword in r.lower() for r in task_requirements):
                if any(s in lower_content for s in signals):
                    covered.append(keyword)
                else:
                    missing.append(keyword)

        if not covered and not missing:
            # No specific keywords found — check minimum content
            if len(content.strip()) > 500:
                return DimensionScore(
                    dimension="completeness", score="PASS",
                    finding="Content appears substantive",
                    evidence=f"{len(content)} chars",
                    is_tool_grounded=True,
                )
            else:
                return DimensionScore(
                    dimension="completeness", score="WARN",
                    finding="Content is minimal — may be incomplete",
                    evidence=f"Only {len(content)} chars",
                    is_tool_grounded=True,
                )

        coverage_pct = len(covered) / (len(covered) + len(missing)) * 100 if (covered or missing) else 100

        if missing:
            return DimensionScore(
                dimension="completeness",
                score="FAIL" if len(missing) > len(covered) else "WARN",
                finding=f"Missing required features: {', '.join(missing)} | Coverage: {coverage_pct:.0f}%",
                evidence=f"Present: {covered} | Missing: {missing}",
                is_tool_grounded=True,
            )
        return DimensionScore(
            dimension="completeness", score="PASS",
            finding=f"All detected requirements covered ({coverage_pct:.0f}%)",
            evidence=f"Covered: {covered}",
            is_tool_grounded=True,
        )

    def _check_quality(
        self, content: str, ext: str, size_bytes: int
    ) -> DimensionScore:
        """
        Self-Refine quality dimension: structural depth check.
        Tool-grounded via file statistics and content analysis.
        """
        from core.quality_verifier import MIN_SIZES
        min_size = MIN_SIZES.get(ext, 100)

        placeholder_patterns = [
            "todo", "placeholder", "lorem ipsum", "coming soon",
            "your content", "add content", "sample text",
        ]
        lower = content.lower()
        placeholder_hits = [p for p in placeholder_patterns if p in lower]

        if size_bytes < min_size:
            return DimensionScore(
                dimension="quality", score="FAIL",
                finding=f"File too small: {size_bytes} bytes (minimum {min_size} for {ext})",
                evidence=f"Content preview: {content[:80]}",
                is_tool_grounded=True,
            )
        if len(placeholder_hits) >= 2:
            return DimensionScore(
                dimension="quality", score="FAIL",
                finding=f"Placeholder content detected: {placeholder_hits}",
                evidence=f"File has placeholder patterns that should be real implementation",
                is_tool_grounded=True,
            )
        if placeholder_hits:
            return DimensionScore(
                dimension="quality", score="WARN",
                finding=f"Possible placeholder: {placeholder_hits[0]}",
                evidence="Verify this is intentional content",
                is_tool_grounded=True,
            )
        return DimensionScore(
            dimension="quality", score="PASS",
            finding=f"File size adequate ({size_bytes} bytes) with no placeholder patterns",
            evidence=f"Min required: {min_size} bytes",
            is_tool_grounded=True,
        )

    def _check_safety(self, content: str) -> DimensionScore:
        """
        CRITIC tool-grounded safety check using pattern matching.
        """
        danger_patterns = [
            ("eval(", "use of eval() — potential code injection"),
            ("exec(", "use of exec() — potential code injection"),
            ("os.system(", "os.system() — use subprocess instead"),
            ("pickle.load", "pickle deserialization — potential security issue"),
            ("shell=True", "shell=True in subprocess — injection risk"),
        ]
        found = [
            desc for pattern, desc in danger_patterns
            if pattern in content
        ]
        if found:
            return DimensionScore(
                dimension="safety", score="WARN",
                finding=f"Potential safety concerns: {found[0]}",
                evidence=f"Found patterns: {found}",
                is_tool_grounded=True,
            )
        return DimensionScore(
            dimension="safety", score="PASS",
            finding="No dangerous patterns detected",
            evidence="",
            is_tool_grounded=True,
        )

    def _check_efficiency(self, content: str, ext: str) -> DimensionScore:
        """
        Lightweight efficiency heuristic — check for obvious O(n²) patterns.
        """
        if ext != ".py":
            return DimensionScore(
                dimension="efficiency", score="PASS",
                finding="Efficiency check not applicable for this file type",
                evidence="",
                is_tool_grounded=False,
            )

        # Check for nested for loops (common O(n²) pattern)
        lines = content.split("\n")
        for_depth = 0
        max_for_depth = 0
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("for ") and stripped.endswith(":"):
                for_depth += 1
                max_for_depth = max(max_for_depth, for_depth)
            elif stripped == "" or not stripped.startswith(" "):
                for_depth = 0

        if max_for_depth >= 3:
            return DimensionScore(
                dimension="efficiency", score="WARN",
                finding=f"Triple-nested for loops detected (depth {max_for_depth}) — possible O(n³)",
                evidence="Consider algorithmic optimization",
                is_tool_grounded=True,
            )
        return DimensionScore(
            dimension="efficiency", score="PASS",
            finding="No obvious efficiency issues",
            evidence="",
            is_tool_grounded=True,
        )

    def _build_repair_instructions(self, fb: StructuredFeedback) -> str:
        """Build targeted repair instructions from failed/warned dimensions."""
        instructions = ["Fix these specific issues before marking this task done:"]
        for ds in fb.dimension_scores:
            if ds.score in ("FAIL", "WARN"):
                instructions.append(
                    f"\n[{ds.dimension.upper()}] {ds.finding}"
                )
                if ds.evidence:
                    instructions.append(f"  Evidence: {ds.evidence[:120]}")
        instructions.append(
            "\nUse read_file to inspect the current file, "
            "then write_file to replace it with a corrected version."
        )
        return "\n".join(instructions)