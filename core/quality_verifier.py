# core/quality_verifier.py
"""
HERMES Quality Verifier — Implementation Depth and Completeness Checker.

Responsibility:
    After a task executes and writes files, this module inspects the
    actual filesystem output and determines whether the implementation
    is genuinely complete or merely superficial.

Design principle:
    A 10-line HTML file is not a "premium website".
    A function stub is not an "implemented feature".
    An empty CSS file is not "styling".
    Quality verification catches shallow implementations before
    they are accepted as mission-complete.

Never use line count alone as the quality metric.
Instead evaluate:
    - Requirement keyword coverage
    - Structural completeness
    - Absence of placeholder patterns
    - File size relative to task complexity
    - Content meaningfulness
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from loguru import logger


# ── Quality thresholds ────────────────────────────────────────────────────────

# Minimum file sizes (bytes) for implementation files to be considered non-trivial
MIN_SIZES: dict[str, int] = {
    ".html":  800,     # Meaningful HTML must have structure + content
    ".css":   400,     # Real CSS must have multiple rules
    ".js":    300,     # Real JS must have actual logic
    ".jsx":   400,     # React component must have real render
    ".tsx":   400,
    ".ts":    300,
    ".py":    200,     # Python module must have real code
    ".vue":   400,
}

# Placeholder patterns — if these dominate a file, it is not implemented
PLACEHOLDER_PATTERNS: list[str] = [
    r"<!-- TODO",
    r"# TODO",
    r"// TODO",
    r"placeholder",
    r"lorem ipsum",
    r"your content here",
    r"add content here",
    r"coming soon",
    r"under construction",
    r"\[content\]",
    r"sample text",
    r"example text",
    r"dummy",
]

# Keywords that indicate meaningful website implementation
WEB_IMPLEMENTATION_SIGNALS: list[str] = [
    "class=", "id=", "@media", "flex", "grid",
    "animation", "transition", "addEventListener",
    "useState", "useEffect", "props", "return (",
    "function ", "const ", "import ", "export ",
]


@dataclass
class FileQualityResult:
    """Quality assessment for a single file."""
    path: str
    exists: bool
    size_bytes: int
    extension: str
    is_trivial: bool
    has_placeholders: bool
    implementation_signals: int
    issues: list[str] = field(default_factory=list)
    verdict: str = "UNKNOWN"   # "GOOD", "SHALLOW", "EMPTY", "MISSING"

    @property
    def is_acceptable(self) -> bool:
        return self.verdict == "GOOD"


@dataclass
class TaskQualityResult:
    """Quality assessment for a complete task."""
    task_id: str
    task_title: str
    file_results: list[FileQualityResult] = field(default_factory=list)
    requirements_checked: list[str] = field(default_factory=list)
    requirements_met: list[str] = field(default_factory=list)
    requirements_missing: list[str] = field(default_factory=list)
    overall_verdict: str = "UNKNOWN"
    # "COMPLETE", "SHALLOW", "EMPTY", "NEEDS_IMPROVEMENT"
    improvement_suggestions: list[str] = field(default_factory=list)
    repair_prompt: str = ""

    @property
    def needs_improvement(self) -> bool:
        return self.overall_verdict in ("SHALLOW", "EMPTY", "NEEDS_IMPROVEMENT")

    @property
    def coverage_pct(self) -> float:
        if not self.requirements_checked:
            return 100.0
        return (
            len(self.requirements_met) / len(self.requirements_checked)
        ) * 100


class QualityVerifier:
    """
    Inspects filesystem output of task execution and determines
    whether the implementation is genuinely complete.

    Usage:
        verifier = QualityVerifier()
        result = verifier.verify_task(task, mission, project_root)
        if result.needs_improvement:
            repair_prompt = result.repair_prompt
            # re-execute with repair_prompt
    """

    def verify_task(
        self,
        task_id: str,
        task_title: str,
        task_description: str,
        project_root: str,
        files_created: list[str],
        files_modified: list[str],
    ) -> TaskQualityResult:
        """
        Main entry point. Inspect the task's output and return
        a structured quality assessment.
        """
        result = TaskQualityResult(
            task_id=task_id,
            task_title=task_title,
        )

        root = Path(project_root) if project_root else None

        # 1. Check all files that were supposedly created/modified
        all_files = list(set(files_created + files_modified))

        if not all_files and root:
            # No tracked files — check project root directly
            all_files = self._find_implementation_files(root)

        for f_path in all_files[:20]:  # Check up to 20 files
            file_result = self._check_file(f_path)
            result.file_results.append(file_result)

        # 2. Derive requirements from task description
        result.requirements_checked = self._extract_requirements(
            task_description
        )

        # 3. Check which requirements are met
        all_content = self._read_all_content(all_files)
        for req in result.requirements_checked:
            if self._requirement_satisfied(req, all_content, all_files):
                result.requirements_met.append(req)
            else:
                result.requirements_missing.append(req)

        # 4. Determine overall verdict
        result.overall_verdict = self._determine_verdict(result)

        # 5. Build improvement suggestions and repair prompt
        if result.needs_improvement:
            result.improvement_suggestions = self._build_suggestions(result)
            result.repair_prompt = self._build_repair_prompt(
                task_description, result
            )

        logger.info(
            f"QualityVerifier: task='{task_title}' | "
            f"verdict={result.overall_verdict} | "
            f"files={len(result.file_results)} | "
            f"coverage={result.coverage_pct:.0f}%"
        )
        return result

    def verify_project_completeness(
        self,
        project_root: str,
        acceptance_criteria: list[str],
        user_prompt: str,
    ) -> TaskQualityResult:
        """
        Verify the entire project against the mission acceptance criteria.
        Called after all tasks complete, before declaring MISSION COMPLETE.
        """
        result = TaskQualityResult(
            task_id="final_verification",
            task_title="Final Project Verification",
        )

        root = Path(project_root)
        if not root.exists():
            result.overall_verdict = "EMPTY"
            result.improvement_suggestions = [
                f"Project root {project_root} does not exist — "
                f"no implementation was created."
            ]
            return result

        # Check all files in project
        all_files = self._find_implementation_files(root)
        for f_path in all_files:
            file_result = self._check_file(f_path)
            result.file_results.append(file_result)

        # Check acceptance criteria
        result.requirements_checked = acceptance_criteria
        all_content = self._read_all_content(all_files)

        for criterion in acceptance_criteria:
            if self._requirement_satisfied(criterion, all_content, all_files):
                result.requirements_met.append(criterion)
            else:
                result.requirements_missing.append(criterion)

        result.overall_verdict = self._determine_verdict(result)
        if result.needs_improvement:
            result.improvement_suggestions = self._build_suggestions(result)
            result.repair_prompt = self._build_repair_prompt(
                user_prompt, result
            )

        return result

    # ── File-level checks ─────────────────────────────────────────────────────

    def _check_file(self, f_path: str) -> FileQualityResult:
        """Check a single file for implementation quality."""
        p = Path(f_path)
        ext = p.suffix.lower()

        result = FileQualityResult(
            path=f_path,
            exists=p.exists(),
            size_bytes=0,
            extension=ext,
            is_trivial=False,
            has_placeholders=False,
            implementation_signals=0,
        )

        if not p.exists():
            result.verdict = "MISSING"
            result.issues.append(f"File does not exist: {f_path}")
            return result

        result.size_bytes = p.stat().st_size

        if result.size_bytes == 0:
            result.verdict = "EMPTY"
            result.issues.append(f"File is empty: {f_path}")
            return result

        # Size check
        min_size = MIN_SIZES.get(ext, 100)
        if result.size_bytes < min_size:
            result.is_trivial = True
            result.issues.append(
                f"File is too small ({result.size_bytes} bytes, "
                f"minimum {min_size} for {ext})"
            )

        # Read content for deeper analysis
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            result.verdict = "UNKNOWN"
            return result

        # Placeholder check
        placeholder_count = 0
        for pattern in PLACEHOLDER_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                placeholder_count += 1
        if placeholder_count >= 2:
            result.has_placeholders = True
            result.issues.append(
                f"File contains {placeholder_count} placeholder patterns"
            )

        # Implementation signal count
        for signal in WEB_IMPLEMENTATION_SIGNALS:
            result.implementation_signals += content.count(signal)

        # Determine verdict
        if result.is_trivial and result.has_placeholders:
            result.verdict = "SHALLOW"
        elif result.is_trivial:
            result.verdict = "SHALLOW"
        elif result.has_placeholders:
            result.verdict = "NEEDS_IMPROVEMENT"
        else:
            result.verdict = "GOOD"

        return result

    def _find_implementation_files(self, root: Path) -> list[str]:
        """Find all implementation files in a project directory."""
        impl_extensions = {
            ".html", ".css", ".js", ".jsx", ".ts", ".tsx",
            ".py", ".vue", ".svelte",
        }
        files = []
        for f in root.rglob("*"):
            if (
                f.is_file()
                and f.suffix.lower() in impl_extensions
                and "node_modules" not in str(f)
                and ".git" not in str(f)
                and "__pycache__" not in str(f)
            ):
                files.append(str(f))
        return files

    # ── Requirement checks ────────────────────────────────────────────────────

    def _extract_requirements(self, task_description: str) -> list[str]:
        """
        Extract measurable requirements from a task description.
        Returns a list of requirement strings that can be checked.
        """
        reqs: list[str] = []
        lower = task_description.lower()

        # Feature keywords → requirements
        feature_map = {
            "navigation": "Navigation component implemented",
            "navbar": "Navigation component implemented",
            "hero": "Hero section implemented",
            "landing": "Landing page implemented",
            "roadmap": "Roadmap section implemented",
            "progress": "Progress tracking implemented",
            "dashboard": "Dashboard implemented",
            "card": "Card components implemented",
            "animation": "Animations implemented",
            "responsive": "Responsive design implemented",
            "mobile": "Mobile support implemented",
            "questionnaire": "Questionnaire implemented",
            "form": "Form implemented",
            "button": "Interactive buttons implemented",
            "modal": "Modal component implemented",
            "auth": "Authentication implemented",
            "login": "Login functionality implemented",
            "api": "API endpoints implemented",
            "test": "Tests written",
            "stylesheet": "Stylesheet created",
            "styling": "Styling implemented",
            "css": "CSS implemented",
            "javascript": "JavaScript implemented",
            "interactive": "Interactive functionality implemented",
            "content": "Content sections populated",
            "footer": "Footer implemented",
            "header": "Header implemented",
        }

        for keyword, requirement in feature_map.items():
            if keyword in lower and requirement not in reqs:
                reqs.append(requirement)

        # Always require: at minimum one non-trivial file
        reqs.append("At least one implementation file with real content")

        return reqs

    def _requirement_satisfied(
        self,
        requirement: str,
        all_content: str,
        all_files: list[str],
    ) -> bool:
        """Check whether a requirement is satisfied in the actual output."""
        lower_req = requirement.lower()
        lower_content = all_content.lower()

        # Generic: at least one file with real content
        if "at least one implementation file" in lower_req:
            for f_path in all_files:
                p = Path(f_path)
                min_size = MIN_SIZES.get(p.suffix.lower(), 100)
                if p.exists() and p.stat().st_size >= min_size:
                    return True
            return False

        # Navigation
        if "navigation" in lower_req:
            return (
                "nav" in lower_content
                or "navbar" in lower_content
                or "navigation" in lower_content
            )

        # Hero
        if "hero" in lower_req:
            return (
                "hero" in lower_content
                or "hero-section" in lower_content
                or "hero_section" in lower_content
            )

        # Roadmap
        if "roadmap" in lower_req:
            return "roadmap" in lower_content

        # Progress
        if "progress" in lower_req:
            return (
                "progress" in lower_content
                or "progressbar" in lower_content
            )

        # Dashboard
        if "dashboard" in lower_req:
            return "dashboard" in lower_content

        # Animations
        if "animation" in lower_req:
            return (
                "@keyframes" in lower_content
                or "animation:" in lower_content
                or "transition:" in lower_content
                or "animate" in lower_content
            )

        # Responsive
        if "responsive" in lower_req:
            return "@media" in lower_content

        # Tests
        if "test" in lower_req:
            test_files = [
                f for f in all_files
                if "test" in Path(f).name.lower() or "spec" in Path(f).name.lower()
            ]
            return len(test_files) > 0

        # CSS
        if "css" in lower_req or "styling" in lower_req:
            css_files = [f for f in all_files if Path(f).suffix == ".css"]
            scss_files = [f for f in all_files if Path(f).suffix in (".scss", ".sass")]
            return len(css_files + scss_files) > 0

        # JavaScript
        if "javascript" in lower_req:
            js_files = [
                f for f in all_files
                if Path(f).suffix in (".js", ".jsx", ".ts", ".tsx")
            ]
            return len(js_files) > 0

        # Generic keyword match
        keywords = lower_req.replace("implemented", "").replace("created", "").strip().split()
        return any(kw in lower_content for kw in keywords if len(kw) > 4)

    def _read_all_content(self, all_files: list[str]) -> str:
        """Read content from all files for combined analysis."""
        parts: list[str] = []
        for f_path in all_files[:30]:
            try:
                content = Path(f_path).read_text(
                    encoding="utf-8", errors="replace"
                )
                parts.append(content[:3000])  # Cap per file to avoid OOM
            except Exception:
                continue
        return "\n".join(parts)

    # ── Verdict and repair ────────────────────────────────────────────────────

    def _determine_verdict(self, result: TaskQualityResult) -> str:
        """Determine overall task quality verdict."""
        file_results = result.file_results

        if not file_results:
            return "EMPTY"

        # Check if all tracked files are empty or missing
        good_files = [f for f in file_results if f.verdict == "GOOD"]
        shallow_files = [f for f in file_results if f.verdict == "SHALLOW"]
        empty_files = [
            f for f in file_results
            if f.verdict in ("EMPTY", "MISSING")
        ]

        if len(empty_files) == len(file_results):
            return "EMPTY"

        # Requirement coverage
        total_reqs = len(result.requirements_checked)
        met_reqs = len(result.requirements_met)
        coverage = met_reqs / total_reqs if total_reqs > 0 else 1.0

        if coverage >= 0.85 and len(good_files) >= max(1, len(file_results) // 2):
            return "COMPLETE"
        elif coverage >= 0.60:
            return "NEEDS_IMPROVEMENT"
        elif shallow_files:
            return "SHALLOW"
        else:
            return "NEEDS_IMPROVEMENT"

    def _build_suggestions(self, result: TaskQualityResult) -> list[str]:
        """Build actionable improvement suggestions."""
        suggestions: list[str] = []

        for f_result in result.file_results:
            if f_result.verdict == "EMPTY":
                suggestions.append(
                    f"File {Path(f_result.path).name} is empty — "
                    f"write full implementation content"
                )
            elif f_result.verdict == "SHALLOW":
                suggestions.append(
                    f"File {Path(f_result.path).name} is too minimal "
                    f"({f_result.size_bytes} bytes) — expand implementation"
                )
            elif f_result.has_placeholders:
                suggestions.append(
                    f"File {Path(f_result.path).name} contains placeholder "
                    f"content — replace with real implementation"
                )

        for missing_req in result.requirements_missing:
            suggestions.append(f"Requirement not satisfied: {missing_req}")

        return suggestions

    def _build_repair_prompt(
        self,
        original_task: str,
        result: TaskQualityResult,
    ) -> str:
        """Build a targeted repair prompt for re-execution."""
        issues_text = "\n".join(
            f"  - {s}" for s in result.improvement_suggestions[:8]
        )
        missing_text = "\n".join(
            f"  - {r}" for r in result.requirements_missing[:6]
        )

        return f"""QUALITY REVIEW FAILED — REPAIR REQUIRED

Original task: {original_task}

Quality verdict: {result.overall_verdict}
Requirement coverage: {result.coverage_pct:.0f}%

Issues found:
{issues_text}

Unsatisfied requirements:
{missing_text}

MANDATORY REPAIR INSTRUCTIONS:
1. Do NOT start over from scratch. Inspect the existing files first.
2. Use read_file to read each existing implementation file.
3. Identify specifically what is missing or trivial.
4. Use write_file to REPLACE shallow implementations with complete ones.
5. Every required feature must have real, working code.
6. Remove all placeholder content (TODO, lorem ipsum, etc.).
7. Ensure every file meets minimum size: HTML 800+ bytes, CSS 400+ bytes,
   JS/JSX 300+ bytes.
8. After fixing, the implementation must satisfy all requirements above.

Do not stop until every requirement above is satisfied.
"""
