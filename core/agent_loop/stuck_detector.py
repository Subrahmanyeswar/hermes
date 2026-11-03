"""
core/agent_loop/stuck_detector.py
Hermes 2.x - Stuck Loop and Oscillation Detector (Section 16).

Detects:
1. Repeated identical tool failures (>= max_identical_errors).
2. A-B-A-B tool oscillation where workspace state remains unchanged.
3. Repeated unchanged read operations without intervening writes.
Preserves bounded history and guarantees mission isolation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("hermes.agent_loop.stuck_detector")


@dataclass
class OperationFingerprint:
    """Deterministic fingerprint of a single tool execution or attempt."""
    mission_id: str
    tool_name: str
    canonical_args: Dict[str, Any]
    target_paths: List[str] = field(default_factory=list)
    input_hashes: List[str] = field(default_factory=list)
    workspace_mutation_digest: str = ""
    failure_class: Optional[str] = None
    diagnostic_digest: str = ""
    timestamp: float = field(default_factory=time.time)
    success: bool = True
    output_hash: str = ""

    def compute_hash(self) -> str:
        """Deterministic hash of operation identity and inputs."""
        try:
            norm_args = json.dumps(self.canonical_args, sort_keys=True, separators=(",", ":"), default=str)
        except Exception:
            norm_args = str(self.canonical_args)

        payload = "|".join([
            self.tool_name,
            norm_args,
            ",".join(sorted(self.target_paths)),
            ",".join(sorted(self.input_hashes)),
            self.failure_class or "",
            self.diagnostic_digest,
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class StuckLoopDetector:
    """
    Monitors tool invocation sequence and failure patterns to detect
    infinite loops, repeated identical failures, and oscillation.
    """

    def __init__(self, max_identical_errors: int = 2, max_history: int = 50):
        # Enforce consistent constructor naming per Section 16
        self.max_identical_errors: int = max_identical_errors
        self.max_history: int = max_history
        self.history: List[OperationFingerprint] = []
        self.mission_id: Optional[str] = None

    def reset(self, mission_id: Optional[str] = None) -> None:
        """Reset history for mission isolation."""
        self.history.clear()
        self.mission_id = mission_id

    def record_operation(
        self,
        fp_or_tool_name: Union[OperationFingerprint, str],
        arguments: Optional[Dict[str, Any]] = None,
        result_summary: Optional[str] = None,
        success: bool = True,
        mission_id: Optional[str] = None,
        workspace_mutation_digest: str = "",
        failure_class: Optional[str] = None,
    ) -> None:
        """Append an operation fingerprint, maintaining bounded history."""
        if isinstance(fp_or_tool_name, OperationFingerprint):
            fp = fp_or_tool_name
        else:
            fp = OperationFingerprint(
                mission_id=mission_id or self.mission_id or "",
                tool_name=str(fp_or_tool_name),
                canonical_args=arguments or {},
                success=success,
                failure_class=failure_class,
                diagnostic_digest=str(result_summary or "")[:128],
                workspace_mutation_digest=workspace_mutation_digest,
            )

        if self.mission_id and fp.mission_id and self.mission_id != fp.mission_id:
            # Automatic mission isolation if mission changed
            self.reset(fp.mission_id)
        elif not self.mission_id and fp.mission_id:
            self.mission_id = fp.mission_id

        self.history.append(fp)
        if len(self.history) > self.max_history:
            self.history.pop(0)

    def check_stuck(self, fp: Optional[OperationFingerprint] = None) -> Tuple[bool, Optional[str]]:
        """
        Check if the incoming operation indicates a stuck condition.
        Returns: (is_stuck, reason_string)
        """
        if not self.history and fp is None:
            return False, None

        is_incoming = (fp is not None)
        if fp is None:
            fp = self.history[-1]

        # 1. Repeated Identical Failure Check
        # Triggered if there are >= max_identical_errors recent failed operations
        # with identical tool, canonical args, failure class/diagnostic,
        # AND workspace state has NOT changed.
        if not fp.success or fp.failure_class:
            incoming_hash = fp.compute_hash()
            consecutive_identical_failures = 0

            # Scan backwards through history
            history_to_scan = self.history[:-1] if not is_incoming else self.history
            for prev in reversed(history_to_scan):
                if prev.success:
                    # An intervening success or meaningful state change breaks the consecutive chain
                    if prev.workspace_mutation_digest != fp.workspace_mutation_digest:
                        break
                    continue

                if prev.compute_hash() == incoming_hash:
                    # Verify workspace has not mutated (i.e. not a repair that happened to fail differently)
                    if prev.workspace_mutation_digest == fp.workspace_mutation_digest:
                        consecutive_identical_failures += 1
                    else:
                        # Workspace state mutated - not identical failure
                        break
                else:
                    break

            total_failures = consecutive_identical_failures + 1
            if total_failures >= self.max_identical_errors:
                return True, (
                    f"STUCK_LOOP_DETECTED: Tool '{fp.tool_name}' failed {total_failures} times "
                    f"with identical arguments and error ({fp.failure_class}) without workspace state change."
                )

        # 2. A-B-A-B Oscillation Check
        # Pattern: [A_fail, B_any, A_fail] where workspace has not mutated across A attempts
        if len(self.history) >= 3 and (not fp.success or fp.failure_class):
            prev_1 = self.history[-1]
            prev_2 = self.history[-2]
            prev_3 = self.history[-3]

            # Current matches prev_2 (Tool A) and prev_1 was Tool B
            is_oscillation = (
                fp.tool_name == prev_2.tool_name
                and fp.compute_hash() == prev_2.compute_hash()
                and prev_1.tool_name == prev_3.tool_name
                and prev_1.tool_name != fp.tool_name
                and fp.workspace_mutation_digest == prev_2.workspace_mutation_digest
            )
            if is_oscillation:
                return True, (
                    f"OSCILLATION_DETECTED: Alternating loop between '{fp.tool_name}' and '{prev_1.tool_name}' "
                    f"with identical arguments and unchanged workspace state."
                )

        # 3. Repeated Unchanged Read Operations Check
        # Detects if a read tool is called repeatedly with identical args and yields identical output
        is_read_tool = any(kw in fp.tool_name.lower() for kw in ("read", "view", "list", "get", "inspect"))
        if is_read_tool and fp.output_hash:
            consecutive_identical_reads = 0
            for prev in reversed(self.history):
                if prev.tool_name == fp.tool_name and prev.compute_hash() == fp.compute_hash():
                    if prev.output_hash == fp.output_hash:
                        consecutive_identical_reads += 1
                    else:
                        break
                else:
                    break
            if consecutive_identical_reads >= (self.max_identical_errors + 1):
                return True, (
                    f"STUCK_LOOP_DETECTED: Repeated redundant read '{fp.tool_name}' called {consecutive_identical_reads + 1} "
                    f"times with identical outputs and no intervening actions."
                )

        return False, None
