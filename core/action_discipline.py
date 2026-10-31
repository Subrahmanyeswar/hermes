# core/action_discipline.py
"""
HERMES Phase 4B — Autonomous Action Discipline & Task Action Contract System.
Enforces the core behavioral principle:
    OBSERVE → UNDERSTAND → ACT → VERIFY
Prevents model/tool wandering, repetitive discovery loops (list_directory/read_file),
and enforces decisive first-pass implementation when workspace state is known.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger


@dataclass
class TaskActionContract:
    """Explicit action contract for a mission task."""
    task_id: str
    title: str
    objective: str
    expected_artifacts: List[str] = field(default_factory=list)
    expected_operation: str = "write_file"   # write_file, edit_file, bash_exec, read_file
    known_target_paths: List[str] = field(default_factory=list)
    prerequisite_artifacts: List[str] = field(default_factory=list)
    verification_criteria: List[str] = field(default_factory=list)
    allowed_exploration_scope: int = 1       # max read-only exploration steps before implementation
    is_implementation: bool = True
    # Phase 4E: Resource & File-Contract Concurrency Fields
    resource_claims: List[str] = field(default_factory=list)
    target_paths: List[str] = field(default_factory=list)
    read_dependencies: List[str] = field(default_factory=list)
    write_dependencies: List[str] = field(default_factory=list)
    conflict_keys: List[str] = field(default_factory=list)

    def get_summary_prompt_section(self, workspace_root: Optional[Path] = None) -> str:
        """Render a compact, high-visibility state summary for prompt injection."""
        lines = [
            "═══ TASK ACTION CONTRACT & WRITE INTENT ═══",
            f"CURRENT TASK: {self.title}",
            f"OBJECTIVE: {self.objective}",
        ]
        
        target_str = ", ".join(self.known_target_paths) if self.known_target_paths else "None specified"
        lines.append(f"TARGET ARTIFACT(S): {target_str}")

        # Check target existence on disk
        targets_exist = []
        if workspace_root and workspace_root.exists() and self.known_target_paths:
            for p in self.known_target_paths:
                full = workspace_root / p
                targets_exist.append(f"{p}: {'EXISTS' if full.exists() else 'MISSING (MUST CREATE)'}")
            lines.append("TARGET STATUS: " + "; ".join(targets_exist))
        else:
            lines.append(f"TARGET STATUS: MISSING (MUST CREATE)")

        # Prerequisites status
        if self.prerequisite_artifacts and workspace_root and workspace_root.exists():
            prereq_status = []
            for p in self.prerequisite_artifacts:
                full = workspace_root / p
                prereq_status.append(f"{p}: {'READY' if full.exists() else 'PENDING'}")
            lines.append("PREREQUISITES: " + "; ".join(prereq_status))

        lines.append(f"REQUIRED OPERATION: {self.expected_operation.upper()}")
        
        if self.is_implementation:
            lines.append("ACTION MOMENTUM: Prerequisites are known. DO NOT repeat directory listing or discovery.")
            lines.append(f"NEXT MANDATORY STEP: Invoke {self.expected_operation} with complete implementation.")

        lines.append("════════════════════════════════════════════")
        return "\n".join(lines)


def derive_action_contract(
    task: Any,
    workspace_root: Optional[Path] = None,
    all_tasks: Optional[List[Any]] = None
) -> TaskActionContract:
    """Derive an authoritative TaskActionContract from a MissionTask."""
    title = getattr(task, "title", "")
    desc = getattr(task, "description", "")
    full_text = f"{title} {desc}"
    lower = full_text.lower()

    # Determine implementation vs read-only
    is_impl = True
    read_only_keywords = ["inspect", "explore", "read only", "audit", "survey", "check structure"]
    if any(k in lower for k in read_only_keywords) and not any(k in lower for k in ["write", "create", "implement", "build", "style", "markup"]):
        is_impl = False

    if getattr(task, "is_verification_task", False):
        is_impl = False

    # Extract target paths
    known_targets: List[str] = []
    # 1. Direct task fields
    for p in (getattr(task, "target_paths", []) or getattr(task, "expected_outputs", []) or getattr(task, "required_files", [])):
        if p and p not in known_targets:
            known_targets.append(p.replace("\\", "/"))

    # 2. Regex from text
    file_matches = re.findall(r'\b([\w\-/\\]+\.(?:html|css|js|py|json|md|ts|tsx|jsx|sql|sh))\b', full_text, re.IGNORECASE)
    for fm in file_matches:
        norm = fm.replace("\\", "/").lstrip("./")
        if norm not in known_targets and not norm.startswith("http") and not norm.endswith(".lock"):
            known_targets.append(norm)

    # 3. Canonical conventions based on task domain
    if not known_targets and is_impl:
        if any(k in lower for k in ["javascript", "js", "logic", "event", "interactive", "state"]):
            known_targets.append("js/app.js")
        elif any(k in lower for k in ["css", "style", "visual", "theme", "responsive"]):
            known_targets.append("css/styles.css")
        elif any(k in lower for k in ["html", "markup", "layout", "structure", "scaffold"]):
            known_targets.append("index.html")

    # Determine expected operation
    expected_op = "write_file"
    if workspace_root and known_targets:
        first_target = workspace_root / known_targets[0]
        if first_target.exists():
            expected_op = "edit_file"
        else:
            expected_op = "write_file"
    elif not is_impl:
        expected_op = "bash_exec" if getattr(task, "is_verification_task", False) else "read_file"

    # Determine prerequisites
    prerequisites: List[str] = []
    if "js/app.js" in known_targets:
        prerequisites = ["index.html", "css/styles.css"]
    elif "css/styles.css" in known_targets:
        prerequisites = ["index.html"]

    # Phase 4E: Resource & File-Contract Concurrency Fields
    write_deps = [p for p in known_targets] if is_impl else []
    read_deps = [p for p in prerequisites]
    conflict_k = [f"write:{p.lower()}" for p in write_deps] + [f"read:{p.lower()}" for p in read_deps]
    res_claims = list(set(write_deps + read_deps))

    return TaskActionContract(
        task_id=getattr(task, "task_id", ""),
        title=title,
        objective=desc[:120].strip(),
        expected_artifacts=known_targets,
        expected_operation=expected_op,
        known_target_paths=known_targets,
        prerequisite_artifacts=prerequisites,
        verification_criteria=[getattr(task, "acceptance_criteria", "Satisfy task requirements")],
        allowed_exploration_scope=1 if is_impl else 3,
        is_implementation=is_impl,
        resource_claims=res_claims,
        target_paths=known_targets,
        read_dependencies=read_deps,
        write_dependencies=write_deps,
        conflict_keys=conflict_k,
    )


@dataclass
class ToolExecutionRecord:
    task_id: str
    tool_name: str
    normalized_arguments: str
    is_repeat: bool
    is_progress: bool
    non_progress_score: int
    action_expected: str
    action_taken: str
    target_artifact: str
    filesystem_changed: bool
    model_turn_number: int
    timestamp: float = field(default_factory=time.time)


class ActionMomentumTracker:
    """
    Tracks tool actions, scores non-progress repetition, and manages escalation levels:
      - LEVEL 1: Soft guidance (warning about missing target)
      - LEVEL 2: Explicit action constraint (mandating write_file/edit_file)
      - LEVEL 3: Task-scoped enforcement (deterministic rejection of repeated read loops)
    """

    def __init__(self, contract: TaskActionContract, workspace_root: Optional[Path] = None):
        self.contract = contract
        self.workspace_root = workspace_root
        self.history: List[ToolExecutionRecord] = []
        self.non_progress_score: int = 0
        self.consecutive_read_only: int = 0
        self.repeated_read_count: int = 0
        self.repeated_list_count: int = 0
        self.non_progress_tool_count: int = 0
        self.implementation_first_action_turn: Optional[int] = None
        self.implementation_occurred: bool = False
        self._last_fingerprint: str = ""
        self._last_ws_state_hash: str = ""

    @property
    def escalation_level(self) -> int:
        if self.non_progress_score >= 3:
            return 3
        elif self.non_progress_score >= 2:
            return 2
        elif self.non_progress_score >= 1:
            return 1
        return 0

    def record_action(
        self,
        tool_name: str,
        params: Dict[str, Any],
        workspace_changed: bool,
        success: bool,
        model_turn: int
    ) -> ToolExecutionRecord:
        """Record an executed tool action and update momentum metrics."""
        norm_params = json.dumps(params, sort_keys=True) if isinstance(params, dict) else str(params)
        fingerprint = f"{tool_name}:{norm_params}"
        is_read_only = tool_name in ("list_directory", "read_file", "search_files", "file_exists", "view_file")
        is_mutation = tool_name in ("write_file", "edit_file", "create_folder")

        # Determine if repeat
        is_repeat = False
        if is_read_only and self._last_fingerprint == fingerprint and not workspace_changed:
            is_repeat = True

        if is_read_only:
            self.consecutive_read_only += 1
        elif is_mutation and workspace_changed:
            self.consecutive_read_only = 0

        # Check target artifact status
        target_art = self.contract.known_target_paths[0] if self.contract.known_target_paths else ""
        target_missing = True
        if target_art and self.workspace_root:
            target_missing = not (self.workspace_root / target_art).exists()

        is_progress = False
        if is_mutation and success and workspace_changed:
            is_progress = True
            self.implementation_occurred = True
            if self.implementation_first_action_turn is None:
                self.implementation_first_action_turn = model_turn
            # Reward progress by reducing non-progress score
            self.non_progress_score = max(0, self.non_progress_score - 2)
        elif is_read_only:
            # If implementation task and target is missing, check if discovery is excessive
            if self.contract.is_implementation and target_missing:
                if is_repeat:
                    self.non_progress_score += 2
                    if tool_name == "list_directory":
                        self.repeated_list_count += 1
                    else:
                        self.repeated_read_count += 1
                else:
                    read_count = sum(1 for r in self.history if r.tool_name in ("list_directory", "read_file"))
                    if read_count >= self.contract.allowed_exploration_scope:
                        self.non_progress_score += 1
                        self.non_progress_tool_count += 1

        rec = ToolExecutionRecord(
            task_id=self.contract.task_id,
            tool_name=tool_name,
            normalized_arguments=norm_params[:200],
            is_repeat=is_repeat,
            is_progress=is_progress,
            non_progress_score=self.non_progress_score,
            action_expected=self.contract.expected_operation,
            action_taken=tool_name,
            target_artifact=target_art,
            filesystem_changed=workspace_changed,
            model_turn_number=model_turn,
        )

        self.history.append(rec)
        self._last_fingerprint = fingerprint
        return rec

    def get_escalation_guidance(self) -> str:
        """Return progressive corrective guidance based on current escalation level."""
        lvl = self.escalation_level
        target_art = self.contract.known_target_paths[0] if self.contract.known_target_paths else "required artifact"
        op = self.contract.expected_operation

        if lvl == 1:
            return (
                f"[ACTION DISCIPLINE — LEVEL 1]\n"
                f"You have already inspected the workspace state. The requested artifact '{target_art}' is still missing.\n"
                f"Proceed to implementation now. Do not call list_directory or read-only tools again unless the workspace has changed."
            )
        elif lvl == 2:
            return (
                f"[ACTION DISCIPLINE — LEVEL 2]\n"
                f"IMPLEMENTATION REQUIRED. For this task the next meaningful action must be: {op} on '{target_art}'.\n"
                f"Read-only exploration is not useful because prerequisites are already satisfied on disk. Write the code now."
            )
        elif lvl >= 3:
            return (
                f"[ACTION DISCIPLINE — LEVEL 3 ENFORCEMENT]\n"
                f"NON_PROGRESS_READ_LOOP DETECTED.\n"
                f"Target artifact '{target_art}' is missing and prerequisites exist. Read-only actions are blocked for this step.\n"
                f"You MUST emit a {op} tool call immediately to complete '{target_art}'."
            )
        return ""

    def should_reject_read_action(self, tool_name: str) -> Tuple[bool, str]:
        """Check if an incoming tool action should be rejected fast at Level 3."""
        if not self.contract.is_implementation:
            return False, ""

        is_read_only = tool_name in ("list_directory", "read_file", "search_files", "file_exists", "view_file")
        if not is_read_only:
            return False, ""

        target_art = self.contract.known_target_paths[0] if self.contract.known_target_paths else ""
        target_missing = True
        if target_art and self.workspace_root:
            target_missing = not (self.workspace_root / target_art).exists()

        if self.escalation_level >= 3 and target_missing:
            msg = (
                f"NON_PROGRESS_READ_LOOP: Tool call '{tool_name}' rejected. "
                f"Workspace state is already known and target artifact '{target_art}' is missing. "
                f"You must invoke {self.contract.expected_operation} with complete implementation."
            )
            return True, msg

        return False, ""
