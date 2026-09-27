# ui/viewmodels/tools.py
"""Tool Execution and Trace ViewModels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ToolTraceItemViewModel:
    tool_call_id: str
    tool_name: str
    status: str            # REQUESTED, STARTED, RUNNING, SUCCEEDED, FAILED, CANCELLED
    arguments_preview: str = ""
    output_preview: str = ""
    duration_str: str = "N/A"
    exit_code: Optional[int] = None
    risk_level: str = "NORMAL"
    timestamp_str: str = ""
    is_error: bool = False


@dataclass(frozen=True)
class ToolTraceViewModel:
    recent_tools: Tuple[ToolTraceItemViewModel, ...] = ()
    active_tool_name: Optional[str] = None
    active_status: str = "IDLE"
    total_invocations: int = 0
    successful_invocations: int = 0
    failed_invocations: int = 0
