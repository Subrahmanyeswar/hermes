# core/subagents/governor.py
"""
Resource Governor & Concurrency Management for HERMES 2.x.

Core Invariants:
1. Bounded Concurrency: Default semaphore limits active parallel subagents to 3.
2. Hard Budget Enforcement: Turns, tool calls, wall time, tokens, and output bytes are strictly tracked.
3. Stall Watchdog: Detects non-progressing subagents and flags them before budgets are wasted.
4. Deterministic Accounting: All resource usage is recorded in authoritative AgentResourceUsage records.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

from core.runtime_state.models import (
    SubagentBudget,
    AgentResourceUsage,
)

logger = logging.getLogger("hermes.subagents.governor")


class BudgetExceededException(Exception):
    """Raised when a subagent exceeds its allocated budget."""
    def __init__(self, resource: str, limit: Any, current: Any):
        super().__init__(f"Budget exceeded for {resource}: limit={limit}, current={current}")
        self.resource = resource
        self.limit = limit
        self.current = current


class ResourceGovernor:
    """
    Controls concurrency, tracks real-time resource utilization, and terminates
    subagents that exceed their allocated budget.
    """

    def __init__(self, max_concurrent: int = 3, stall_timeout_seconds: float = 60.0):
        self.max_concurrent = max_concurrent
        self.stall_timeout_seconds = stall_timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._lock = threading.Lock()
        self._active_agents: Dict[str, Tuple[SubagentBudget, AgentResourceUsage, float]] = {}

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active_agents)

    async def acquire_slot(self, timeout: Optional[float] = None) -> None:
        """Acquire a slot in the concurrency semaphore with optional timeout."""
        if timeout is not None:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout)
        else:
            await self._semaphore.acquire()

    def release_slot(self) -> None:
        """Release a slot in the concurrency semaphore."""
        try:
            self._semaphore.release()
        except ValueError:
            pass

    def register_agent(self, agent_id: str, budget: SubagentBudget) -> AgentResourceUsage:
        """Register a new subagent for tracking."""
        usage = AgentResourceUsage()
        with self._lock:
            self._active_agents[agent_id] = (budget, usage, time.time())
        return usage

    def unregister_agent(self, agent_id: str) -> Optional[AgentResourceUsage]:
        """Unregister an agent upon completion or termination."""
        with self._lock:
            entry = self._active_agents.pop(agent_id, None)
            return entry[1] if entry else None

    def record_turn(self, agent_id: str) -> None:
        """Increment turn count and refresh activity heartbeat."""
        with self._lock:
            if agent_id in self._active_agents:
                budget, usage, _ = self._active_agents[agent_id]
                usage.turns += 1
                self._active_agents[agent_id] = (budget, usage, time.time())
                self._check_budget_limits(agent_id, budget, usage)

    def record_tool_call(self, agent_id: str) -> None:
        """Increment tool call count and refresh activity heartbeat."""
        with self._lock:
            if agent_id in self._active_agents:
                budget, usage, _ = self._active_agents[agent_id]
                usage.tool_calls += 1
                self._active_agents[agent_id] = (budget, usage, time.time())
                self._check_budget_limits(agent_id, budget, usage)

    def record_tokens(self, agent_id: str, input_tokens: int, output_tokens: int) -> None:
        """Update token usage."""
        with self._lock:
            if agent_id in self._active_agents:
                budget, usage, last_t = self._active_agents[agent_id]
                usage.input_tokens += input_tokens
                usage.output_tokens += output_tokens
                self._active_agents[agent_id] = (budget, usage, last_t)
                self._check_budget_limits(agent_id, budget, usage)

    def record_output_bytes(self, agent_id: str, num_bytes: int) -> None:
        """Update output byte count."""
        with self._lock:
            if agent_id in self._active_agents:
                budget, usage, last_t = self._active_agents[agent_id]
                usage.output_bytes += num_bytes
                self._active_agents[agent_id] = (budget, usage, last_t)
                self._check_budget_limits(agent_id, budget, usage)

    def check_stall(self, agent_id: str) -> Tuple[bool, float]:
        """
        Check if an agent has stalled (no activity for > stall_timeout_seconds).
        Returns (is_stalled, idle_seconds).
        """
        now = time.time()
        with self._lock:
            if agent_id not in self._active_agents:
                return False, 0.0
            _, _, last_active = self._active_agents[agent_id]
            idle = now - last_active
            return idle > self.stall_timeout_seconds, idle

    def _check_budget_limits(self, agent_id: str, budget: SubagentBudget, usage: AgentResourceUsage) -> None:
        """Check usage against hard limits and raise BudgetExceededException if violated."""
        if budget.max_turns > 0 and usage.turns > budget.max_turns:
            raise BudgetExceededException("max_turns", budget.max_turns, usage.turns)

        if budget.max_tool_calls > 0 and usage.tool_calls > budget.max_tool_calls:
            raise BudgetExceededException("max_tool_calls", budget.max_tool_calls, usage.tool_calls)

        if budget.max_output_bytes > 0 and usage.output_bytes > budget.max_output_bytes:
            raise BudgetExceededException("max_output_bytes", budget.max_output_bytes, usage.output_bytes)

        total_tokens = usage.input_tokens + usage.output_tokens
        if budget.max_total_tokens > 0 and total_tokens > budget.max_total_tokens:
            raise BudgetExceededException("max_total_tokens", budget.max_total_tokens, total_tokens)
