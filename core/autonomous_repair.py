# core/autonomous_repair.py
"""
Bounded Autonomous Repair Loop for HERMES 2.x (Phase 4).
Prevents endless repair loops by capping interventions to at most 2 focused cycles
per failed acceptance stage.

Invariants:
1. Every repair identifies the root cause and responsible source files.
2. Interventions are focused and minimal.
3. Max 2 focused repair cycles per failed gate.
4. A repair attempt does NOT count as a passing result.
5. Only verified new evidence may change a gate from FAIL to PASS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger


@dataclass
class RepairCycleRecord:
    gate_name: str
    cycle_number: int
    issues_diagnosed: List[str]
    responsible_files: List[str]
    repair_instruction: str
    timestamp: float
    verified_pass_after: bool = False


class AutonomousRepairGovernor:
    """
    Governs bounded autonomous repair workflows for failed acceptance gates.
    """

    MAX_REPAIR_CYCLES_PER_GATE: int = 2

    def __init__(self, max_cycles: int = 2) -> None:
        self.max_cycles = max_cycles
        self._cycles_count: Dict[str, int] = {}
        self._repair_history: List[RepairCycleRecord] = []

    def get_cycle_count(self, gate_name: str) -> int:
        return self._cycles_count.get(gate_name, 0)

    def can_attempt_repair(self, gate_name: str) -> bool:
        """True if the gate has remaining repair cycles in its budget."""
        return self.get_cycle_count(gate_name) < self.max_cycles

    def diagnose_and_prescribe(
        self,
        gate_name: str,
        issues: List[str],
        workspace_root: Path | str,
    ) -> Dict[str, Any]:
        """
        Diagnoses failures, maps issues to responsible source files,
        and generates a focused repair directive.
        """
        ws = Path(workspace_root).resolve()
        responsible_files: List[str] = []
        instructions: List[str] = []

        combined = " ".join(issues).lower()

        if "asset" in gate_name.lower() or "image" in combined:
            responsible_files.extend(["index.html", "style.css", "assets/images/"])
            instructions.append("Verify local image paths match pre-provisioned assets. Ensure decodable JPEG/PNG files exist.")
        elif "responsive" in gate_name.lower() or "overflow" in combined:
            responsible_files.append("style.css")
            instructions.append("Fix horizontal overflow. Set max-width: 100%, box-sizing: border-box, and responsive media queries.")
        elif "functional" in gate_name.lower() or "binding" in combined or "event" in combined:
            responsible_files.extend(["app.js", "main.js", "index.html"])
            instructions.append("Ensure event listeners update the DOM/state rather than merely logging to console. Fix absent DOM element queries.")
        elif "structural" in gate_name.lower() or "doctype" in combined:
            responsible_files.append("index.html")
            instructions.append("Ensure standard HTML5 structure with <!DOCTYPE html>, <html>, <head>, <body>, and properly linked styles.")
        elif "accessibility" in gate_name.lower() or "alt" in combined:
            responsible_files.append("index.html")
            instructions.append("Add descriptive alt attributes to all <img> tags and labels/placeholders to form inputs.")
        else:
            responsible_files.append("index.html")
            instructions.append("Address acceptance check failures.")

        return {
            "gate_name": gate_name,
            "issues": issues,
            "responsible_files": sorted(list(set(responsible_files))),
            "repair_instruction": " ".join(instructions),
            "cycle_number": self.get_cycle_count(gate_name) + 1,
            "max_cycles": self.max_cycles,
        }

    def record_repair_cycle(
        self,
        gate_name: str,
        issues: List[str],
        responsible_files: List[str],
        repair_instruction: str,
    ) -> Tuple[bool, str]:
        """
        Records a repair attempt and increments the gate's repair cycle count.
        Returns:
            (allowed: bool, reason: str)
        """
        import time

        curr = self.get_cycle_count(gate_name)
        if curr >= self.max_cycles:
            msg = f"Autonomous repair budget exhausted for gate '{gate_name}' ({self.max_cycles} cycles reached). Stopping."
            logger.warning(msg)
            return False, msg

        self._cycles_count[gate_name] = curr + 1
        record = RepairCycleRecord(
            gate_name=gate_name,
            cycle_number=curr + 1,
            issues_diagnosed=issues,
            responsible_files=responsible_files,
            repair_instruction=repair_instruction,
            timestamp=time.time(),
            verified_pass_after=False,
        )
        self._repair_history.append(record)
        msg = f"Repair cycle {curr + 1}/{self.max_cycles} recorded for gate '{gate_name}'. Re-verification required."
        logger.info(msg)
        return True, msg

    def register_verified_outcome(self, gate_name: str, passed: bool) -> None:
        """
        Updates the latest repair record with verified new outcome.
        A repair attempt cannot turn into PASS without verified evidence.
        """
        for rec in reversed(self._repair_history):
            if rec.gate_name == gate_name:
                rec.verified_pass_after = passed
                break
