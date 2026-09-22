# core/adaptive_execution.py
"""
Adaptive Execution Engine for HERMES vNext (Phase 9).
Routes requests between SIMPLE (0-LLM fast path), STANDARD (streamlined agent),
and COMPLEX (full KAIROS mission) with runtime escalation and hysteresis.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from loguru import logger
from config.model_config import ADAPTIVE_EXECUTION_ENABLED


class ExecutionMode(Enum):
    SIMPLE = "SIMPLE"       # Deterministic fast path (0 LLMs, <15ms)
    STANDARD = "STANDARD"   # Streamlined agent (ContextEngine + T1 + Progressive Gate)
    COMPLEX = "COMPLEX"     # Full autonomous mission (Planning + KAIROS DAG + T1/T2/T3)


@dataclass
class ClassificationResult:
    mode: ExecutionMode
    confidence: float
    risk_score: float
    reasons: List[str]
    deterministic_tool: Optional[str] = None
    deterministic_args: Optional[Dict[str, Any]] = None
    duration_ms: float = 0.0


class TaskComplexityClassifier:
    """
    Deterministic ultra-fast (<0.5ms) multi-signal request classifier.
    Never calls an LLM to classify requests.
    """

    COMPLEX_INDICATORS = [
        "architecture", "migrate", "refactor entire", "complete system",
        "full-stack", "frontend and backend", "data layer", "distributed",
        "across all files", "end-to-end", "multi-module", "microservice"
    ]

    SIMPLE_PATTERNS = [
        # Create folder / directory
        (r"^(?:create|make|add|new)\s+(?:folder|dir|directory)\s+([a-zA-Z0-9_\-./\\]+)$", "create_directory", "path"),
        (r"^mkdir\s+([a-zA-Z0-9_\-./\\]+)$", "create_directory", "path"),
        # Read file
        (r"^(?:read|view|show|cat|inspect|open)\s+(?:file\s+)?([a-zA-Z0-9_\-./\\]+\.[a-zA-Z0-9]+)$", "read_file", "path"),
        # List directory
        (r"^(?:list\s+(?:files|all\s+files|directory|dir)|ls|dir|show\s+(?:project\s+structure|structure|files))$", "list_directory", "path"),
        # File exists / stat
        (r"^(?:check\s+if\s+file\s+exists|file\s+exists|stat)\s+([a-zA-Z0-9_\-./\\]+)$", "file_exists", "path"),
    ]

    def classify(self, user_request: str) -> ClassificationResult:
        start_time = time.perf_counter()
        req_clean = user_request.strip()
        req_lower = req_clean.lower()
        reasons = []

        # 1. Check for Complex Mission indicators
        for ind in self.COMPLEX_INDICATORS:
            if ind in req_lower:
                reasons.append(f"matched_complex_keyword_{ind}")
                dur = (time.perf_counter() - start_time) * 1000.0
                return ClassificationResult(
                    mode=ExecutionMode.COMPLEX,
                    confidence=0.90,
                    risk_score=0.40,
                    reasons=reasons,
                    duration_ms=dur
                )

        # 2. Check for Simple Deterministic operations
        for pattern, tool_name, arg_name in self.SIMPLE_PATTERNS:
            m = re.match(pattern, req_clean, re.IGNORECASE)
            if m:
                arg_val = m.group(1).strip() if m.groups() else "."
                reasons.append(f"deterministic_{tool_name}")
                dur = (time.perf_counter() - start_time) * 1000.0
                return ClassificationResult(
                    mode=ExecutionMode.SIMPLE,
                    confidence=0.95,
                    risk_score=0.05,
                    reasons=reasons,
                    deterministic_tool=tool_name,
                    deterministic_args={arg_name: arg_val},
                    duration_ms=dur
                )

        # 3. Default to Standard Agent Path (Safe Fallback)
        reasons.append("standard_agent_reasoning_required")
        dur = (time.perf_counter() - start_time) * 1000.0
        return ClassificationResult(
            mode=ExecutionMode.STANDARD,
            confidence=0.85,
            risk_score=0.20,
            reasons=reasons,
            duration_ms=dur
        )


class EscalationManager:
    """
    Manages runtime escalation triggers (e.g. SIMPLE -> STANDARD -> COMPLEX).
    Maintains hysteresis to prevent flip-flopping during an active mission.
    """

    def __init__(self, initial_mode: ExecutionMode = ExecutionMode.STANDARD):
        self.current_mode = initial_mode
        self.escalations: List[Dict[str, Any]] = []

    def check_escalation(
        self,
        tool_failed: bool = False,
        dependency_count: int = 0,
        syntax_error: bool = False,
        unanticipated_files: int = 0
    ) -> ExecutionMode:
        prev_mode = self.current_mode

        if self.current_mode == ExecutionMode.SIMPLE:
            if tool_failed or syntax_error or unanticipated_files > 0:
                self.current_mode = ExecutionMode.STANDARD
                self.escalations.append({
                    "from": "SIMPLE", "to": "STANDARD",
                    "reason": "tool_failure_or_unexpected_complexity",
                    "timestamp": time.time()
                })
                logger.info("EscalationManager: Escalated SIMPLE -> STANDARD")

        elif self.current_mode == ExecutionMode.STANDARD:
            if dependency_count > 3 or unanticipated_files > 3:
                self.current_mode = ExecutionMode.COMPLEX
                self.escalations.append({
                    "from": "STANDARD", "to": "COMPLEX",
                    "reason": f"high_dependency_count_{dependency_count}",
                    "timestamp": time.time()
                })
                logger.info("EscalationManager: Escalated STANDARD -> COMPLEX")

        return self.current_mode


class AdaptiveExecutionEngine:
    """
    Coordinator for Phase 9 Adaptive Execution Routing.
    """

    def __init__(self, enabled: bool = ADAPTIVE_EXECUTION_ENABLED):
        self.enabled = enabled
        self.classifier = TaskComplexityClassifier()

    def execute_fast_path(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        workspace_manager=None
    ) -> Tuple[bool, str]:
        """
        Executes deterministic SIMPLE tasks with 0 LLMs in <15ms.
        Passes through security validation and deterministic verification.
        """
        start_time = time.perf_counter()
        try:
            target_path = tool_args.get("path", ".")

            # 1. Security Gate Validation
            from core.tool_validator import tool_validator
            is_safe, sec_err = tool_validator.validate_security(tool_name, tool_args)
            if not is_safe:
                return False, f"SECURITY_ERROR: {sec_err}"

            # 2. Execute Deterministic Action
            if tool_name == "create_directory":
                if workspace_manager and workspace_manager.is_locked:
                    abs_p = Path(workspace_manager.root_str) / target_path
                else:
                    abs_p = Path(target_path).resolve()
                abs_p.mkdir(parents=True, exist_ok=True)
                dur = (time.perf_counter() - start_time) * 1000.0
                return True, f"Successfully created directory '{target_path}' in {dur:.2f}ms"

            elif tool_name == "read_file":
                if workspace_manager and workspace_manager.is_locked:
                    content = workspace_manager.get_file_content(target_path)
                else:
                    content = Path(target_path).read_text(encoding="utf-8", errors="replace")
                dur = (time.perf_counter() - start_time) * 1000.0
                return True, f"{content}\n\n[Read completed in {dur:.2f}ms]"

            elif tool_name == "list_directory":
                if workspace_manager and workspace_manager.is_locked:
                    skeleton = workspace_manager.get_skeleton()
                    summary = workspace_manager.get_workspace_summary()
                    dur = (time.perf_counter() - start_time) * 1000.0
                    return True, f"Workspace: {summary.get('root', '.')}\nFiles: {summary.get('total_files', 0)}\n\n{skeleton}\n\n[Listed in {dur:.2f}ms]"
                else:
                    files = [f.name for f in Path(target_path).iterdir()]
                    dur = (time.perf_counter() - start_time) * 1000.0
                    return True, f"Files in {target_path}:\n" + "\n".join(files) + f"\n\n[Listed in {dur:.2f}ms]"

            elif tool_name == "file_exists":
                if workspace_manager and workspace_manager.is_locked:
                    abs_p = Path(workspace_manager.root_str) / target_path
                else:
                    abs_p = Path(target_path)
                exists = abs_p.exists()
                dur = (time.perf_counter() - start_time) * 1000.0
                return True, f"File '{target_path}' exists: {exists} (checked in {dur:.2f}ms)"

            return False, f"Unknown deterministic tool: {tool_name}"

        except Exception as e:
            logger.warning("Fast path execution failed: {}", e)
            return False, f"Fast path error: {e}"


# Global singleton
adaptive_execution_engine = AdaptiveExecutionEngine()
