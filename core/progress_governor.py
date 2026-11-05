# core/progress_governor.py
"""
HERMES 2.x — Progress Governor and No-Progress Detection (Phase 2)
Distinguishes genuine progress from unproductive reasoning, duplicate actions,
or repeated failed operations.

Meaningful Progress Invariants:
  GENUINE PROGRESS:
    1. Successful file creation or modification with substantive changes.
    2. Successful task-advancing tool execution (e.g. test run, browser verification).
    3. Validated improvement in a requirement.
    4. Completed work-package item.
    5. Verified resolution of an identified defect.

  NOT PROGRESS ALONE:
    - Repeated thought events without actions.
    - Repeated identical searches (search_glob, search_grep with same params).
    - An attempted model call or provider failover.
    - Repeating the same failed tool operation.
    - Rewriting the same file with identical or trivial content.

Triggers controlled diagnosis after 3 consecutive non-progress turns.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger


class ProgressStatus(str, Enum):
    ADVANCING = "ADVANCING"
    STAGNANT = "STAGNANT"
    STALLED = "STALLED"
    CRITICAL_NO_PROGRESS = "CRITICAL_NO_PROGRESS"


@dataclass
class TurnProgressEvaluation:
    """Evaluation of a single agent turn's contribution to mission progress."""
    turn_id: str
    is_meaningful_progress: bool
    progress_reason: str
    actions_count: int
    mutations_count: int
    advancing_tools: List[str] = field(default_factory=list)
    repeated_actions: List[str] = field(default_factory=list)
    diagnostic_advice: Optional[str] = None


class ProgressGovernor:
    """
    Monitors turn-by-turn outcomes to guarantee the mission advances objectively.
    Configurable threshold: 3 consecutive non-progress turns triggers diagnostic escalation.
    """

    NON_PROGRESS_THRESHOLD: int = 3
    MAX_NO_PROGRESS_BUDGET: int = 5

    def __init__(self, threshold: int = 3) -> None:
        self.threshold = threshold
        self.consecutive_non_progress_turns: int = 0
        self.total_non_progress_turns: int = 0
        self.turn_history: List[TurnProgressEvaluation] = []
        self._seen_file_hashes: Dict[str, str] = {}
        self._seen_action_signatures: Set[str] = set()
        self._recent_searches: List[str] = []
        self._last_error: Optional[str] = None

    def reset(self) -> None:
        self.consecutive_non_progress_turns = 0
        self.total_non_progress_turns = 0
        self.turn_history.clear()
        self._seen_file_hashes.clear()
        self._seen_action_signatures.clear()
        self._recent_searches.clear()
        self._last_error = None

    def evaluate_turn(
        self,
        turn_id: str,
        actions: List[Dict[str, Any]],
        file_modifications: List[Dict[str, Any]],
        tool_results: List[Dict[str, Any]],
        requirements_progressed: bool = False,
        work_package_completed: bool = False,
        test_or_browser_passed: bool = False,
        error_context: Optional[str] = None,
    ) -> TurnProgressEvaluation:
        """
        Authoritatively evaluate whether a turn yielded meaningful progress.
        """
        if error_context:
            self._last_error = error_context

        # 1. Check for genuine file modifications (content actually changed)
        substantive_writes = 0
        for mod in file_modifications:
            path = str(mod.get("path") or mod.get("target") or "")
            content = str(mod.get("content") or mod.get("replacement") or "")
            if path and not content:
                try:
                    import os
                    if os.path.exists(path):
                        with open(path, "rb") as f_in:
                            content_hash = hashlib.sha256(f_in.read()).hexdigest()
                    else:
                        content_hash = f"path_seen:{path}"
                except Exception:
                    content_hash = f"path_seen:{path}"
            elif path and content:
                content_hash = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
            else:
                continue

            prev_hash = self._seen_file_hashes.get(path)
            if prev_hash != content_hash:
                self._seen_file_hashes[path] = content_hash
                substantive_writes += 1

        # 2. Check for task-advancing tool results
        advancing_tools: List[str] = []
        repeated_actions: List[str] = []

        for act in actions:
            name = act.get("name") or act.get("tool") or ""
            args = act.get("arguments") or act.get("parameters") or {}
            sig = f"{name}:{sorted(args.items()) if isinstance(args, dict) else args}"
            
            # Detect repeated searches
            if name in ("search_glob", "search.glob", "search_grep", "search.grep"):
                if sig in self._recent_searches:
                    repeated_actions.append(f"repeated search {name}")
                else:
                    self._recent_searches.append(sig)
                    if len(self._recent_searches) > 10:
                        self._recent_searches.pop(0)

            # Check if this tool genuinely advances tasks (tests, verification, builds)
            if name in ("browser_evaluate", "browser_navigate", "run_tests", "pytest", "npm_test", "shell.bash"):
                # Check exit code or success
                matching_res = next((r for r in tool_results if r.get("tool") == name or r.get("name") == name), None)
                if matching_res and matching_res.get("success", False) and matching_res.get("exit_code", 0) == 0:
                    advancing_tools.append(name)

        # 3. Determine meaningful progress verdict
        is_progress = False
        progress_reasons = []

        if substantive_writes > 0:
            is_progress = True
            progress_reasons.append(f"modified {substantive_writes} file(s) with substantive content")
        if work_package_completed:
            is_progress = True
            progress_reasons.append("completed work-package milestone")
        if requirements_progressed:
            is_progress = True
            progress_reasons.append("progressed acceptance requirements")
        if test_or_browser_passed:
            is_progress = True
            progress_reasons.append("verified successful browser/test execution")
        if advancing_tools and not repeated_actions:
            is_progress = True
            progress_reasons.append(f"executed task-advancing tools: {', '.join(advancing_tools)}")

        # 4. Update counters
        if is_progress:
            self.consecutive_non_progress_turns = 0
            reason_str = "; ".join(progress_reasons)
            diag_advice = None
        else:
            self.consecutive_non_progress_turns += 1
            self.total_non_progress_turns += 1
            reason_str = "No substantive file modifications, milestone completions, or advancing tools"
            if repeated_actions:
                reason_str += f" ({'; '.join(repeated_actions)})"
            
            # Construct actionable diagnostic advice
            if self._last_error:
                diag_advice = f"Focus directly on resolving latest error: {self._last_error[:120]}. Use fs.write or fs.edit."
            elif repeated_actions:
                diag_advice = "Avoid repeating previous searches or queries. Proceed directly to writing required files."
            else:
                diag_advice = "Implement missing code or styles using fs.write/fs.edit rather than reading or planning."

        eval_obj = TurnProgressEvaluation(
            turn_id=turn_id,
            is_meaningful_progress=is_progress,
            progress_reason=reason_str,
            actions_count=len(actions),
            mutations_count=substantive_writes,
            advancing_tools=advancing_tools,
            repeated_actions=repeated_actions,
            diagnostic_advice=diag_advice,
        )
        self.turn_history.append(eval_obj)
        return eval_obj

    def get_status(self) -> ProgressStatus:
        """Return high-level progress health status."""
        if self.consecutive_non_progress_turns == 0:
            return ProgressStatus.ADVANCING
        elif self.consecutive_non_progress_turns < self.threshold:
            return ProgressStatus.STAGNANT
        elif self.consecutive_non_progress_turns < self.MAX_NO_PROGRESS_BUDGET:
            return ProgressStatus.STALLED
        else:
            return ProgressStatus.CRITICAL_NO_PROGRESS

    def should_trigger_diagnosis(self) -> bool:
        """True when consecutive non-progress turns reaches threshold (>=3)."""
        return self.consecutive_non_progress_turns >= self.threshold

    def get_diagnostic_payload(self) -> Dict[str, Any]:
        """Construct structured NO_PROGRESS diagnostic payload for telemetry and UI events."""
        latest = self.turn_history[-1] if self.turn_history else None
        return {
            "status": self.get_status().value,
            "consecutive_non_progress_turns": self.consecutive_non_progress_turns,
            "total_non_progress_turns": self.total_non_progress_turns,
            "threshold": self.threshold,
            "last_error": self._last_error,
            "suggested_action": latest.diagnostic_advice if latest else "Implement code modifications directly.",
            "repeated_actions": latest.repeated_actions if latest else [],
        }


# Global instance
progress_governor = ProgressGovernor(threshold=3)
