# tools/platform/batch.py
"""
Programmatic Tool Calling and Batch Execution Interface for HERMES 2.x.
Provides safe contracts for orchestrating sequential or batched tool operations
without intermediate model round-trips.

STATUS: ADVANCED EXTENSION / FUTURE (DEFERRED TO PHASE 2 PER PROMPT 5 SPECIFICATION)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from tools.platform.specs import ToolSpec
from tools.platform.catalog import tool_catalog
from tools.platform.executor import ToolExecutor, ToolPlatformResult


@dataclass
class BatchToolRequest:
    """Single tool request within a batch."""
    tool_name: str
    arguments: Dict[str, Any]
    step_id: str
    stop_on_error: bool = True


@dataclass
class BatchExecutionResult:
    """Outcome of a batched tool execution sequence."""
    batch_id: str
    success: bool
    results: List[ToolPlatformResult] = field(default_factory=list)
    total_duration_seconds: float = 0.0
    failed_step_id: Optional[str] = None


class ToolBatchExecutor:
    """
    Executes declaring batch-safe tool requests sequentially under causal order.
    """

    def __init__(self, mode: str = "auto") -> None:
        self.mode = mode
        self.executor = ToolExecutor(mode=mode)

    async def execute_batch(
        self,
        batch_id: str,
        requests: List[BatchToolRequest],
        mission_id: str = "",
        task_id: str = "",
        turn_id: str = "",
        abort_event: Optional[asyncio.Event] = None,
    ) -> BatchExecutionResult:
        """
        Execute batch requests in strict sequence.
        """
        results: List[ToolPlatformResult] = []
        overall_success = True
        failed_id = None
        t_start = asyncio.get_event_loop().time()

        for req in requests:
            if abort_event is not None and abort_event.is_set():
                overall_success = False
                break

            spec = tool_catalog.get(req.tool_name)
            if spec and not spec.batch_safe:
                # If tool does not declare batch safety, execute with caution
                pass

            res = await self.executor.execute(
                tool_name=req.tool_name,
                arguments=req.arguments,
                tool_call_id=f"{batch_id}-{req.step_id}",
                action_id=req.step_id,
                mission_id=mission_id,
                task_id=task_id,
                turn_id=turn_id,
                abort_event=abort_event,
            )
            results.append(res)

            if not res.success:
                overall_success = False
                failed_id = req.step_id
                if req.stop_on_error:
                    break

        duration = asyncio.get_event_loop().time() - t_start
        return BatchExecutionResult(
            batch_id=batch_id,
            success=overall_success,
            results=results,
            total_duration_seconds=duration,
            failed_step_id=failed_id,
        )
