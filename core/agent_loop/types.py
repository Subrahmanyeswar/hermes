# core/agent_loop/types.py
"""
Data models, enums, and structures for the HERMES 2.x Agent Loop.
Provides normalized representations for:
- Lifecycle dimensions
- Agent turns
- Semantic decision types
- Action envelopes
- Observations
- Configuration and results
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Set

from config.model_config import (
    DEFAULT_MISSION_MAX_TURNS,
    WEBSITE_MISSION_MAX_TURNS,
)


class LifecycleDimension(str, Enum):
    """
    Lifecycle dimensions describe runtime activity in HERMES 2.x.
    These are observational categories, NOT mandatory execution stages.
    """
    INTAKE = "INTAKE"
    CONTEXT = "CONTEXT"
    AGENT = "AGENT"
    ACTION = "ACTION"
    OBSERVE = "OBSERVE"
    VERIFY = "VERIFY"
    JUDGE = "JUDGE"
    REPAIR = "REPAIR"
    MEMORY = "MEMORY"
    COMPLETE = "COMPLETE"


class AgentDecisionType(str, Enum):
    """
    Semantic classification of model-directed choices.
    """
    ACT = "ACT"                              # Model requests a tool action
    ASK_USER = "ASK_USER"                    # Model needs clarification from user
    VERIFY = "VERIFY"                        # Model requests verification
    DELEGATE = "DELEGATE"                    # Model requests subagent delegation
    COMPLETE = "COMPLETE"                    # Model proposes completion candidate
    CONTINUE_REASONING = "CONTINUE_REASONING"# Model generates thought/text and continues
    ABORT = "ABORT"                          # Model or system requests abort
    INVALID = "INVALID"                      # Model output could not be parsed safely


class ActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class AgentDecision:
    """The interpreted semantic decision produced by a single agent turn."""
    decision_type: AgentDecisionType
    tool_name: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    tool_call_id: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    user_question: Optional[str] = None
    verification_target: Optional[str] = None
    delegation_target: Optional[str] = None
    reasoning: str = ""
    explanation: str = ""
    raw_text: str = ""
    turn_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["decision_type"] = self.decision_type.value
        return d


@dataclass
class ActionEnvelope:
    """
    Normalized representation for an action proposed by the model.
    Passes through Harness Policy (ALLOW, DENY, ASK, MODIFY, ESCALATE)
    before physical tool execution.
    """
    action_id: str = field(default_factory=lambda: f"act_{uuid.uuid4().hex[:8]}")
    mission_id: str = ""
    task_id: Optional[str] = None
    turn_id: Optional[str] = None
    request_id: Optional[str] = None
    action_type: str = "TOOL"                 # "TOOL", "VERIFY", "USER_QUESTION", "DELEGATE"
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    requested_at: float = field(default_factory=time.time)
    policy_context: Dict[str, Any] = field(default_factory=dict)
    risk_level: str = "NORMAL"
    permission_required: Optional[str] = None
    source: str = "agent_loop"
    status: ActionStatus = ActionStatus.PROPOSED
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class Observation:
    """
    Structured outcome of an environment interaction or tool execution.
    Observations feed subsequent model context turns.
    """
    observation_id: str = field(default_factory=lambda: f"obs_{uuid.uuid4().hex[:8]}")
    mission_id: str = ""
    task_id: Optional[str] = None
    turn_id: Optional[str] = None
    action_id: Optional[str] = None
    source_type: str = "tool"                 # "tool", "environment", "system", "verification", "user"
    source_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    success: bool = True
    summary: str = ""
    content: str = ""
    exit_code: Optional[int] = 0
    full_result_ref: Optional[str] = None
    evidence_ids: List[str] = field(default_factory=list)
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_context_string(self) -> str:
        """Format concise observation representation for LLM context grounding."""
        status_str = "SUCCESS" if self.success else f"FAILED (exit_code={self.exit_code})"
        lines = [f"[OBSERVATION from {self.source_id or self.source_type}]: status={status_str}"]
        if self.summary:
            lines.append(f"  Summary: {self.summary}")
        if self.content:
            trimmed = self.content.strip()
            max_len = 3500 if not self.success else 1200
            if len(trimmed) > max_len:
                trimmed = trimmed[:max_len] + "... [truncated]"
            lines.append(f"  Output:\n{trimmed}")
        if self.error_message:
            lines.append(f"  Error: {self.error_message}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentTurn:
    """
    Represents one model decision cycle in the continuous loop.
    Carries full causal tracking without storing unbounded transcripts in state.
    """
    turn_id: str = field(default_factory=lambda: f"turn_{uuid.uuid4().hex[:8]}")
    mission_id: str = ""
    task_id: Optional[str] = None
    request_id: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    model: str = ""
    provider: str = ""
    decision_type: AgentDecisionType = AgentDecisionType.CONTINUE_REASONING
    tool_call_ids: List[str] = field(default_factory=list)
    action_ids: List[str] = field(default_factory=list)
    observation_ids: List[str] = field(default_factory=list)
    state_version_before: int = 0
    state_version_after: int = 0
    continuation: bool = True
    termination_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["decision_type"] = self.decision_type.value
        return d


@dataclass
class AgentLoopConfig:
    """Explicit safety guardrails and resource budgets for AgentLoop execution."""
    max_turns: int = DEFAULT_MISSION_MAX_TURNS
    website_max_turns: int = WEBSITE_MISSION_MAX_TURNS
    max_tool_actions: int = 50
    max_wall_time_seconds: float = float(os.getenv("MISSION_MAX_WALL_TIME_SECONDS", "1200.0"))
    max_consecutive_failures: int = 5
    stall_window_size: int = 4
    stall_repeat_threshold: int = 3
    execution_mode: str = "agentic"            # "agentic" or "strict"
    enable_streaming: bool = True
    auto_verify_on_completion: bool = True
    temperature: float = 0.2
    _explicit_max_turns: bool = field(default=False, repr=False)
    _initialized: bool = field(default=False, repr=False)

    def __init__(
        self,
        max_turns: Optional[int] = None,
        website_max_turns: Optional[int] = None,
        max_tool_actions: int = 50,
        max_wall_time_seconds: Optional[float] = None,
        max_consecutive_failures: int = 5,
        stall_window_size: int = 4,
        stall_repeat_threshold: int = 3,
        execution_mode: str = "agentic",
        enable_streaming: bool = True,
        auto_verify_on_completion: bool = True,
        temperature: float = 0.2,
        **kwargs: Any,
    ):
        object.__setattr__(self, "_initialized", False)
        object.__setattr__(self, "_explicit_max_turns", (max_turns is not None))
        object.__setattr__(self, "max_turns", max_turns if max_turns is not None else DEFAULT_MISSION_MAX_TURNS)
        object.__setattr__(self, "website_max_turns", website_max_turns if website_max_turns is not None else WEBSITE_MISSION_MAX_TURNS)
        self.max_tool_actions = max_tool_actions
        self.max_wall_time_seconds = (
            max_wall_time_seconds
            if max_wall_time_seconds is not None
            else float(os.getenv("MISSION_MAX_WALL_TIME_SECONDS", "1200.0"))
        )
        self.max_consecutive_failures = max_consecutive_failures
        self.stall_window_size = stall_window_size
        self.stall_repeat_threshold = stall_repeat_threshold
        self.execution_mode = execution_mode
        self.enable_streaming = enable_streaming
        self.auto_verify_on_completion = auto_verify_on_completion
        self.temperature = temperature
        for k, v in kwargs.items():
            setattr(self, k, v)
        object.__setattr__(self, "_initialized", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "max_turns" and getattr(self, "_initialized", False):
            object.__setattr__(self, "_explicit_max_turns", True)
        object.__setattr__(self, name, value)

    def resolve_for_mission(
        self,
        mission: Any,
        workspace_root: Optional[Path] = None,
        written_files: Optional[Set[str]] = None,
    ) -> int:
        """
        Resolve the effective turn budget based on mission type and configuration.
        Website missions receive website_max_turns (default 80) unless max_turns
        was explicitly overridden.
        """
        # If caller explicitly specified mission.max_turns on mission object, respect it
        mission_override = getattr(mission, "max_turns", None)
        if mission_override is not None:
            object.__setattr__(self, "max_turns", int(mission_override))
            object.__setattr__(self, "_explicit_max_turns", True)
            return self.max_turns

        if getattr(self, "_explicit_max_turns", False):
            return self.max_turns

        from core.agent_loop.mvp_gate import WebsiteMvpGate
        prompt = getattr(mission, "user_prompt", "") or str(mission or "")
        ws = workspace_root
        if ws is None and hasattr(mission, "workspace_root") and mission.workspace_root:
            ws = Path(mission.workspace_root)

        from core.verification_profiles import classify_verification_profile, VerificationProfile
        prof = classify_verification_profile(prompt, workspace_path=str(ws) if ws else None, written_files=list(written_files) if written_files else None)

        if prof == VerificationProfile.PROFILE_A:
            # Simple smoke test / diagnostic task: compact turn budget and wall time
            object.__setattr__(self, "max_turns", min(self.max_turns, 8))
            object.__setattr__(self, "max_wall_time_seconds", min(self.max_wall_time_seconds, 300.0))
        elif WebsiteMvpGate.is_website_mission(prompt, workspace_root=ws, written_files=written_files):
            object.__setattr__(self, "max_turns", self.website_max_turns)
        else:
            object.__setattr__(self, "max_turns", DEFAULT_MISSION_MAX_TURNS)
        return self.max_turns


@dataclass
class AgentLoopResult:
    """Terminal execution outcome of an AgentLoop run."""
    mission_id: str
    success: bool
    status: str = "COMPLETE"                  # "COMPLETE", "FAILED", "CANCELLED", "ABORTED"
    turns_executed: int = 0
    actions_executed: int = 0
    tool_calls_count: int = 0
    verification_calls_count: int = 0
    duration_seconds: float = 0.0
    files_created: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    final_output: str = ""
    error: Optional[str] = None
    termination_reason: Optional[str] = None
