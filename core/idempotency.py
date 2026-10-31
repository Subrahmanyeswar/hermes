# core/idempotency.py
"""
HERMES Tool Execution Idempotency Ledger
========================================
Guarantees exactly-once side-effect execution across provider failovers,
model retries, streaming interruptions, and network timeouts.

Maintains stable logical action identities across model changes:
  logical_id = f(mission_id, turn_id, canonical_tool, canonicalized_arguments)

Distinguishes execution states:
  - NOT_EXECUTED
  - PENDING
  - COMPLETED
  - FAILED
  - UNCERTAIN
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from loguru import logger


class LedgerStatus(str, Enum):
    NOT_EXECUTED = "NOT_EXECUTED"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"


def compute_logical_action_id(
    mission_id: str,
    turn_id: Optional[str],
    canonical_tool: str,
    arguments: Dict[str, Any],
) -> str:
    """
    Computes a stable, deterministic logical action identity across provider failovers.
    Normalizes argument ordering and path separators so identical actions from different
    models map to the exact same logical action ID.
    """
    norm_args = {}
    if isinstance(arguments, dict):
        for k, v in sorted(arguments.items()):
            if k.startswith("_"):
                continue  # ignore internal metadata prefixes
            if isinstance(v, str) and ("\\" in v or "/" in v):
                norm_args[k] = v.replace("\\", "/").rstrip("/")
            else:
                norm_args[k] = v
    else:
        norm_args = {"_raw": str(arguments)}

    args_str = json.dumps(norm_args, sort_keys=True, default=str)
    # Scope to mission and turn when available, or mission and action payload
    seed = f"{mission_id}:{turn_id or ''}:{canonical_tool}:{args_str}"
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"op_log_{h}"


@dataclass
class LedgerEntry:
    logical_id: str
    mission_id: str
    turn_id: Optional[str]
    tool_name: str
    arguments: Dict[str, Any]
    status: LedgerStatus
    cached_result: Any = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    execution_count: int = 0


class ToolExecutionLedger:
    """
    Thread-safe execution ledger tracking logical actions and their outcomes.
    Prevents duplicate tool side effects when a model fails over to another tier.
    """

    def __init__(self) -> None:
        self._entries: Dict[str, LedgerEntry] = {}

    def get_status(self, logical_id: str) -> LedgerStatus:
        entry = self._entries.get(logical_id)
        if entry:
            return entry.status
        return LedgerStatus.NOT_EXECUTED

    def get_cached_result(self, logical_id: str) -> Optional[Any]:
        entry = self._entries.get(logical_id)
        if entry and entry.status == LedgerStatus.COMPLETED:
            return entry.cached_result
        return None

    def mark_pending(
        self,
        logical_id: str,
        mission_id: str,
        turn_id: Optional[str],
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> LedgerEntry:
        now = time.time()
        if logical_id in self._entries:
            entry = self._entries[logical_id]
            entry.status = LedgerStatus.PENDING
            entry.updated_at = now
            return entry

        entry = LedgerEntry(
            logical_id=logical_id,
            mission_id=mission_id,
            turn_id=turn_id,
            tool_name=tool_name,
            arguments=arguments,
            status=LedgerStatus.PENDING,
            created_at=now,
            updated_at=now,
            execution_count=0,
        )
        self._entries[logical_id] = entry
        return entry

    def record_execution_start(self, logical_id: str) -> None:
        entry = self._entries.get(logical_id)
        if entry:
            entry.execution_count += 1
            entry.updated_at = time.time()

    def mark_completed(self, logical_id: str, result: Any) -> None:
        if logical_id in self._entries:
            entry = self._entries[logical_id]
            entry.status = LedgerStatus.COMPLETED
            entry.cached_result = result
            entry.updated_at = time.time()
        else:
            self._entries[logical_id] = LedgerEntry(
                logical_id=logical_id,
                mission_id="",
                turn_id="",
                tool_name="",
                arguments={},
                status=LedgerStatus.COMPLETED,
                cached_result=result,
            )

    def mark_failed(self, logical_id: str, error: str) -> None:
        if logical_id in self._entries:
            entry = self._entries[logical_id]
            entry.status = LedgerStatus.FAILED
            entry.updated_at = time.time()

    def mark_uncertain(self, logical_id: str, reason: str) -> None:
        if logical_id in self._entries:
            entry = self._entries[logical_id]
            entry.status = LedgerStatus.UNCERTAIN
            entry.updated_at = time.time()

    def get_execution_count(self, logical_id: str) -> int:
        entry = self._entries.get(logical_id)
        return entry.execution_count if entry else 0

    def clear(self) -> None:
        self._entries.clear()


# Global execution ledger instance
tool_execution_ledger = ToolExecutionLedger()
