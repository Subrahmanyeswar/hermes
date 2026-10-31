# core/agent_loop/preflight.py
"""
Deterministic Workspace Preflight & Intent Classifier for HERMES 2.x Agent Loop.

Accurately distinguishes between:
  1. Creating a new application from scratch (GREENFIELD_CREATE / NEW_PROJECT).
  2. Modifying an existing application (EXISTING_PROJECT_MODIFY / CONTINUATION_OR_MODIFICATION).
  3. Extending an existing application with new features (EXISTING_PROJECT_EXTEND).
  4. Inspecting an existing workspace (INSPECTION).
  5. Running tests or verification against an existing application (VERIFICATION_ONLY).

Guarantees:
  - An empty workspace is accepted for explicit new projects, even when safety clauses
    mention preserving or not modifying existing projects/repositories, or when user
    requirements mention in-app CRUD capabilities (e.g. 'edit existing tasks').
  - Modification and extension missions requiring existing target files are cleanly rejected
    when empty with actionable failure codes and guidance.
  - Explicit target workspace paths specified in the prompt that mismatch the selected
    active workspace are rejected before execution with clear corrective guidance.
  - No workspace files are mutated when a preflight rejection occurs.
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.workspace import IGNORE_PATTERNS as _WS_IGNORE_PATTERNS


class MissionIntent(str, Enum):
    GREENFIELD_CREATE = "GREENFIELD_CREATE"
    EXISTING_PROJECT_MODIFY = "EXISTING_PROJECT_MODIFY"
    EXISTING_PROJECT_EXTEND = "EXISTING_PROJECT_EXTEND"
    INSPECTION = "INSPECTION"
    VERIFICATION_ONLY = "VERIFICATION_ONLY"

    # Backward-compatible aliases
    NEW_PROJECT = "GREENFIELD_CREATE"
    CONTINUATION_OR_MODIFICATION = "EXISTING_PROJECT_MODIFY"


@dataclass
class PreflightResult:
    allowed: bool
    intent: MissionIntent
    failure_code: Optional[str] = None
    error: Optional[str] = None
    reason: str = ""
    detected_target_path: Optional[str] = None
    existing_app_files_count: int = 0
    details: Dict[str, Any] = field(default_factory=dict)


NON_APP_METADATA_DIRS = {
    ".hermes", "artifacts", ".artifacts", "sessions", ".sessions",
    "trajectories", "browser_profiles", ".gemini",
    ".git", ".svn", ".hg",
    "node_modules", "venv", ".venv", "env",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    ".idea", ".vscode", "dist", "build", "target"
}

NON_APP_METADATA_FILES = {
    ".ds_store", "thumbs.db", ".gitignore", ".gitattributes", ".gitmodules",
    ".editorconfig", ".env", ".env.local"
}

CODEBASE_NOUNS = (
    r"(?:project|app|application|website|site|codebase|repo|repository|code|system|solution|software)"
)


def extract_specified_target_workspace(prompt: str) -> Optional[str]:
    """
    Extract explicitly declared target workspace path from user prompt if present.
    Matches formats like:
      **Target workspace:** `C:\\Users\\SUBBU\\Downloads\\hermes_rocket_3d_test`
      Target directory: /path/to/project
      workspace_path: "C:\\projects\\app"
    """
    if not prompt:
        return None

    pat = re.compile(
        r"(?:target\s+workspace|target\s+directory|target\s+path|target\s+dir|workspace[\s_]+path|project[\s_]+path)"
        r"[\s*:=]+[`\"']?([a-zA-Z]:[\\/][^`\"'\r\n*?<>|]+|/[^`\"'\r\n*?<>|]+)[`\"']?",
        re.IGNORECASE,
    )
    m = pat.search(prompt)
    if m:
        extracted = m.group(1).strip().rstrip("`\"' ")
        return extracted
    return None


def clean_actionable_prompt(prompt: str) -> str:
    """
    Filter out safety guidelines, negative instructions, and foreign project preservation.
    Removes preservation clauses while keeping actionable directives intact.
    """
    if not prompt:
        return ""
    lines = [l.strip() for l in prompt.split("\n") if l.strip()]
    actionable_lines = []
    preservation_patterns = [
        r"\bdo\s+not\s+(?:overwrite|modify|change|delete|touch)\b.*?\bexisting\b.*?(?=[.;\n]|$)",
        r"\bif\s+(?:any\s+)?existing\b.*?\b(?:do\s+not|report|preserve|skip|wait|halt)\b.*?(?=[.;\n]|$)",
        r"\bpreserve\s+(?:the\s+)?(?:existing|working|original|all)\b.*?(?=[.;\n]|$)",
        r"\bwithout\s+(?:overwriting|modifying|changing|deleting)\s+(?:the\s+)?existing\b.*?(?=[.;\n]|$)",
        r"\bdo\s+not\s+modify\s+(?:hermes|other\s+projects|source\s+repository|rocket\s+application|existing\s+application)\b.*?(?=[.;\n]|$)",
        r"\bno\s+existing\s+(?:application|app|project|website|codebase|repo)\s+(?:is\s+being\s+)?(?:modified|changed|updated|touched)\b.*?(?=[.;\n]|$)",
        r"\bnot\s+modifying\s+(?:any\s+)?(?:existing\s+)?(?:application|app|project|website|codebase)\b.*?(?=[.;\n]|$)",
    ]
    for line in lines:
        cleaned_line = line
        for pat in preservation_patterns:
            cleaned_line = re.sub(pat, " ", cleaned_line, flags=re.IGNORECASE).strip()
        if cleaned_line:
            actionable_lines.append(cleaned_line)
    return " ".join(actionable_lines)


def classify_mission_intent(prompt: str) -> Tuple[MissionIntent, str]:
    """
    Deterministically classify the mission intent.
    Neutralizes negative/preservation clauses before evaluation, and prevents
    in-app domain CRUD phrases (e.g. 'edit existing tasks') from triggering
    codebase modification intent.
    """
    if not prompt or not prompt.strip():
        return MissionIntent.GREENFIELD_CREATE, "empty_prompt"

    actionable_text = clean_actionable_prompt(prompt).lower()

    # 1. Check for Verification Only
    verification_patterns = [
        r"\b(?:run|execute)\s+(?:tests?|pytest|verification|checks)\s+only\b",
        r"\b(?:run\s+)?verification\s+only\b",
        r"\b(?:audit|verify)\s+(?:the\s+)?(?:existing\s+)?(?:test\s+suite|tests?|regressions?)\b",
    ]
    for pat in verification_patterns:
        if re.search(pat, actionable_text):
            if not any(k in actionable_text for k in ["build", "create", "implement", "add", "modify", "develop"]):
                return MissionIntent.VERIFICATION_ONLY, f"verification_only:{pat}"

    # 2. Check for Inspection Only
    inspection_patterns = [
        r"\b(?:inspect|examine|show|list|read-only|explain|analyze)\s+(?:the\s+)?(?:workspace|files|codebase|directory|project\s+structure)\b",
    ]
    for pat in inspection_patterns:
        if re.search(pat, actionable_text):
            if not any(k in actionable_text for k in ["build", "create", "implement", "add", "modify", "fix", "develop"]):
                return MissionIntent.INSPECTION, f"inspection_only:{pat}"

    # 3. Check for Strong Greenfield markers (explicit new project / scratch / empty workspace)
    strong_greenfield_pats = [
        r"\b(?:from\s+scratch|greenfield|brand-new|brand\s+new)\b",
        r"\b(?:in\s+an\s+empty\s+workspace|in\s+the\s+empty\s+workspace)\b",
        r"\b(?:this\s+is\s+a|it\s+is\s+a|start\s+a)\s+(?:new|clean|blank|fresh)\s+" + CODEBASE_NOUNS,
        r"\bcreate\s+(?:an?\s+isolated\s+project|index\.html|style\.css|main\.js|package\.json)\b",
    ]
    for pat in strong_greenfield_pats:
        if re.search(pat, actionable_text):
            return MissionIntent.GREENFIELD_CREATE, f"explicit_greenfield:{pat}"

    # 4. Check for Existing Project Extension
    extend_patterns = [
        r"\b(?:add|integrate|extend|append|incorporate)\b.*?\b(?:to|into|in)\s+(?:the\s+|this\s+|my\s+|our\s+)?(?:existing|current)\s+(?:[\w-]+\s+){0,3}" + CODEBASE_NOUNS,
        r"\bextend\s+(?:the\s+|this\s+|my\s+|our\s+)?(?:existing|current)\s+(?:[\w-]+\s+){0,3}" + CODEBASE_NOUNS,
        r"\badd\s+(?:a\s+)?(?:new\s+)?(?:feature|capability|module|component|page|endpoint|route|chart|table|view)\s+(?:to|into|in)\s+(?:the\s+|this\s+|my\s+|our\s+)?(?:existing|current)\b",
        r"\bintegrate\s+(?:a\s+)?(?:new\s+)?(?:\w+\s+)*(?:chart|module|component|library|api|feature)\s+(?:into|to|in)\s+(?:the\s+|this\s+|my\s+|our\s+)?(?:existing|current)\b",
    ]
    for pat in extend_patterns:
        if re.search(pat, actionable_text):
            return MissionIntent.EXISTING_PROJECT_EXTEND, f"extend_existing:{pat}"

    # 5. Check for Existing Project Modification
    modify_patterns = [
        r"\b(?:modify|update|refactor|fix|patch|repair|debug|edit|change)\s+(?:the\s+|this\s+|my\s+|our\s+)?(?:existing|current)\s+(?:[\w-]+\s+){0,3}" + CODEBASE_NOUNS,
        r"\bfix\s+(?:the\s+|a\s+|an\s+)?(?:bug|issue|defect|error|problem|crash|failure)\s+in\s+(?:the\s+|this\s+|my\s+|our\s+)?(?:existing|current\s+)?(?:[\w-]+\s+){0,3}" + CODEBASE_NOUNS,
        r"\b(?:continue|resume)\s+(?:improving|building|working\s+on|the\s+work\s+on)?\s+(?:the\s+|this\s+)?(?:existing|current)\s+(?:[\w-]+\s+){0,3}" + CODEBASE_NOUNS,
        r"\bupdate\s+an\s+existing\s+(?:[\w-]+\s+){0,3}" + CODEBASE_NOUNS,
        r"\b(?:in|to)\s+(?:the\s+|this\s+|my\s+)?existing\s+(?:[\w-]+\s+){0,3}" + CODEBASE_NOUNS,
    ]
    for pat in modify_patterns:
        if re.search(pat, actionable_text):
            return MissionIntent.EXISTING_PROJECT_MODIFY, f"modify_existing:{pat}"

    # 6. Check for General Greenfield Creation (build/create a new or described project)
    greenfield_patterns = [
        r"\b(?:build|create|develop|generate|make|code|initialize|start|set\s*up)\s+(?:a\s+|an\s+)?(?:[^.;\n]+?\s+)?(?:web\s+application|web\s+app|website|dashboard|portal|application|app|project|game|tool|system|interface)\b",
        r"\bnew\s+" + CODEBASE_NOUNS,
    ]
    for pat in greenfield_patterns:
        if re.search(pat, actionable_text):
            return MissionIntent.GREENFIELD_CREATE, f"greenfield_creation:{pat}"

    # 7. Fallback Heuristics
    if any(k in actionable_text for k in ["build", "create", "make", "generate", "implement", "develop"]):
        return MissionIntent.GREENFIELD_CREATE, "fallback:creation_verbs"
    if any(k in actionable_text for k in ["fix", "improve", "update", "repair", "debug", "refactor"]):
        return MissionIntent.EXISTING_PROJECT_MODIFY, "fallback:modification_verbs"

    return MissionIntent.GREENFIELD_CREATE, "fallback:default"


def scan_application_files(ws_root: Path) -> List[Path]:
    """Scan workspace for legitimate non-metadata application files."""
    app_files: List[Path] = []
    if not ws_root or not ws_root.exists():
        return app_files

    for root, dirs, files in os.walk(str(ws_root), topdown=True, followlinks=False):
        # Prune ignored and metadata directories in-place to avoid deep/cyclic recursion
        dirs[:] = [
            d for d in dirs
            if d.lower() not in NON_APP_METADATA_DIRS
            and not any(fnmatch.fnmatch(d, pat) for pat in _WS_IGNORE_PATTERNS)
            and not d.startswith(".")
        ]
        root_p = Path(root)
        for f in files:
            f_lower = f.lower()
            if f_lower in NON_APP_METADATA_FILES or f_lower.endswith((".pyc", ".pyo", ".pyd")):
                continue
            app_files.append(root_p / f)
            if len(app_files) >= 5000:
                break
        if len(app_files) >= 5000:
            break
    return app_files


def validate_workspace_preflight(
    prompt: str,
    ws_root: Optional[Path],
) -> PreflightResult:
    """
    Perform deterministic preflight validation prior to execution.
    """
    intent, intent_reason = classify_mission_intent(prompt)

    if not ws_root:
        return PreflightResult(
            allowed=True,
            intent=intent,
            reason="no_workspace_locked",
        )

    ws_root_resolved = ws_root.resolve()

    # 1. Target Workspace Mismatch Check
    specified_target = extract_specified_target_workspace(prompt)
    if specified_target:
        try:
            target_path_resolved = Path(specified_target).resolve()
            if target_path_resolved != ws_root_resolved:
                err_msg = (
                    f"Target workspace mismatch: Prompt specified target workspace '{specified_target}', "
                    f"but the active selected workspace is '{ws_root_resolved}'. "
                    f"Please switch the active workspace to '{specified_target}' before running or update the prompt."
                )
                return PreflightResult(
                    allowed=False,
                    intent=intent,
                    failure_code="WORKSPACE_TARGET_MISMATCH",
                    error=err_msg,
                    reason=f"target_mismatch:{specified_target}!={ws_root_resolved}",
                    detected_target_path=specified_target,
                    details={"specified_target": str(target_path_resolved), "active_workspace": str(ws_root_resolved)},
                )
        except Exception:
            pass

    # 2. Workspace Application Files Scan
    app_files = scan_application_files(ws_root_resolved)
    file_count = len(app_files)

    # 3. Intent vs Workspace Content Evaluation
    if intent == MissionIntent.GREENFIELD_CREATE:
        # Empty workspace is explicitly valid and accepted for a new project
        return PreflightResult(
            allowed=True,
            intent=intent,
            reason=f"greenfield_create_allowed:{intent_reason}",
            detected_target_path=specified_target,
            existing_app_files_count=file_count,
        )

    if intent in (MissionIntent.EXISTING_PROJECT_MODIFY, MissionIntent.EXISTING_PROJECT_EXTEND):
        if file_count == 0:
            err_msg = (
                f"Workspace '{ws_root_resolved}' contains 0 existing application files, "
                f"but the mission requested modifying or extending an existing application: '{prompt}'. "
                f"Cannot proceed without the target application files."
            )
            return PreflightResult(
                allowed=False,
                intent=intent,
                failure_code="EMPTY_WORKSPACE_EXISTING_APPLICATION",
                error=err_msg,
                reason="empty_workspace_for_continuation",
                detected_target_path=specified_target,
                existing_app_files_count=0,
            )
        return PreflightResult(
            allowed=True,
            intent=intent,
            reason=f"existing_project_allowed:{file_count}_files_found",
            detected_target_path=specified_target,
            existing_app_files_count=file_count,
        )

    if intent in (MissionIntent.INSPECTION, MissionIntent.VERIFICATION_ONLY):
        if file_count == 0:
            err_msg = (
                f"Workspace '{ws_root_resolved}' contains 0 existing application files, "
                f"but the mission requested inspection/verification only. "
                f"Cannot proceed without application files to inspect."
            )
            return PreflightResult(
                allowed=False,
                intent=intent,
                failure_code="EMPTY_WORKSPACE_VERIFICATION",
                error=err_msg,
                reason="empty_workspace_for_verification",
                detected_target_path=specified_target,
                existing_app_files_count=0,
            )
        return PreflightResult(
            allowed=True,
            intent=intent,
            reason=f"inspection_allowed:{file_count}_files_found",
            detected_target_path=specified_target,
            existing_app_files_count=file_count,
        )

    return PreflightResult(
        allowed=True,
        intent=intent,
        reason=intent_reason,
        detected_target_path=specified_target,
        existing_app_files_count=file_count,
    )
