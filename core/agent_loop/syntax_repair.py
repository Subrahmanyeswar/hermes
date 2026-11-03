# core/agent_loop/syntax_repair.py
"""
Targeted Syntax Repair Controller for HERMES 2.x.
Ensures application syntax defects generate structured repair tickets,
pin file tail context, block unhelpful re-reads, and drive deterministic
repair convergence without false tier escalations.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from core.structured_observation import extract_syntax_diagnostic
from core.js_syntax_validator import validate_javascript_file

logger = logging.getLogger(__name__)


@dataclass
class SyntaxRepairTicket:
    """Structured repair ticket tracking a concrete deliverable syntax defect."""
    failure_type: str = "APPLICATION_SYNTAX_ERROR"
    target_file: str = ""
    validator: str = ""
    exit_code: int = 1
    error_class: str = "SyntaxError"
    line: Optional[int] = None
    column: Optional[int] = None
    message: str = ""
    file_hash: str = ""
    candidate_hash: str = ""
    tail_lines: List[str] = field(default_factory=list)
    failure_fingerprint: str = ""
    failure_id: str = ""
    mission_id: str = ""
    run_id: str = ""
    required_next_action: str = "Issue fs.write or fs.edit to repair JavaScript syntax defect"
    repair_attempts: int = 0
    max_attempts: int = 2
    is_active: bool = True
    raw_stderr: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_type": self.failure_type,
            "target_file": self.target_file,
            "validator": self.validator,
            "exit_code": self.exit_code,
            "error_class": self.error_class,
            "line": self.line,
            "column": self.column,
            "message": self.message,
            "file_hash": self.file_hash,
            "candidate_hash": self.candidate_hash,
            "tail_lines": self.tail_lines,
            "failure_fingerprint": self.failure_fingerprint,
            "failure_id": self.failure_id,
            "mission_id": self.mission_id,
            "run_id": self.run_id,
            "required_next_action": self.required_next_action,
            "repair_attempts": self.repair_attempts,
            "max_attempts": self.max_attempts,
            "is_active": self.is_active,
        }


class SyntaxRepairController:
    """Manages active syntax repair tickets and generates targeted model directives."""

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root
        self.active_tickets: Dict[str, SyntaxRepairTicket] = {}  # target_file -> ticket

    def create_or_update_ticket(
        self,
        target_file: str,
        validator: str,
        stderr_or_output: str,
        exit_code: int = 1,
        workspace_root: Optional[Path] = None,
        candidate_content: Optional[str] = None,
        mission_id: str = "",
        run_id: str = "",
    ) -> SyntaxRepairTicket:
        """Create or update a structured syntax repair ticket for target_file."""
        ws = workspace_root or self.workspace_root or Path.cwd()
        target_p = ws / target_file if not Path(target_file).is_absolute() else Path(target_file)
        
        file_hash = ""
        tail_lines: List[str] = []
        if target_p.exists() and target_p.is_file():
            try:
                content = target_p.read_text(encoding="utf-8", errors="replace")
                file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                all_lines = content.splitlines()
                tail_lines = all_lines[-30:] if len(all_lines) > 30 else all_lines
            except Exception as e:
                logger.debug(f"Failed to read file tail for syntax ticket: {e}")
        elif candidate_content is not None:
            try:
                file_hash = hashlib.sha256(candidate_content.encode("utf-8")).hexdigest()
                all_lines = candidate_content.splitlines()
                tail_lines = all_lines[-30:] if len(all_lines) > 30 else all_lines
            except Exception as e:
                logger.debug(f"Failed to parse candidate content tail: {e}")

        # Parse error details
        diag = extract_syntax_diagnostic(stderr_or_output) or {}
        line_num = diag.get("line")
        col_num = diag.get("column")
        err_class = diag.get("error_class", "SyntaxError")
        err_msg = diag.get("message", stderr_or_output.strip().splitlines()[-1] if stderr_or_output.strip() else "Syntax error")

        # Stable normalized fingerprint based on target file, line, and message
        fp_raw = f"{Path(target_file).name.lower()}:{line_num or 0}:{err_class}:{err_msg}"
        failure_fp = hashlib.sha256(fp_raw.encode("utf-8")).hexdigest()[:12]
        failure_id = f"fail_{failure_fp}"

        ticket_key = Path(target_file).name.lower()
        existing = self.active_tickets.get(ticket_key)
        if existing and existing.failure_fingerprint == failure_fp and existing.file_hash == file_hash:
            # Same failure still active
            existing.raw_stderr = stderr_or_output
            existing.mission_id = mission_id or existing.mission_id
            existing.run_id = run_id or existing.run_id
            return existing

        ticket = SyntaxRepairTicket(
            failure_type="APPLICATION_SYNTAX_ERROR",
            target_file=str(target_file),
            validator=validator,
            exit_code=exit_code,
            error_class=err_class,
            line=line_num,
            column=col_num,
            message=err_msg,
            file_hash=file_hash,
            candidate_hash=file_hash,
            tail_lines=tail_lines,
            failure_fingerprint=failure_fp,
            failure_id=failure_id,
            mission_id=mission_id,
            run_id=run_id,
            required_next_action="Issue fs.write or fs.edit immediately to repair JavaScript syntax defect",
            repair_attempts=0,
            max_attempts=2,
            is_active=True,
            raw_stderr=stderr_or_output,
        )
        self.active_tickets[ticket_key] = ticket
        return ticket

    def build_repair_directive(self, ticket: SyntaxRepairTicket) -> str:
        """Construct unambiguous, pinned model context instruction for targeted repair."""
        tail_numbered = []
        start_idx = max(1, (ticket.line or 1) - 15) if ticket.line else 1
        for i, l in enumerate(ticket.tail_lines, start=max(1, start_idx)):
            tail_numbered.append(f"{i:4d} | {l}")
        tail_str = "\n".join(tail_numbered) if tail_numbered else "(empty file)"

        directive = (
            f"=== CRITICAL APPLICATION SYNTAX REPAIR DIRECTIVE ===\n"
            f"Target File: {ticket.target_file} (SHA-256: {ticket.file_hash[:8]})\n"
            f"Failed Validator: {ticket.validator}\n"
            f"Error: Line {ticket.line or 'unknown'}: {ticket.error_class}: {ticket.message}\n"
            f"Repair Attempt: {ticket.repair_attempts + 1} of {ticket.max_attempts}\n\n"
            f"Source Tail ({len(ticket.tail_lines)} lines before EOF):\n"
            f"--------------------------------------------------\n"
            f"{tail_str}\n"
            f"--------------------------------------------------\n\n"
            f"MANDATORY ACTION REQUIRED:\n"
            f"1. Calling fs.read on '{ticket.target_file}' is PROHIBITED because the file context is already provided above.\n"
            f"2. You MUST use fs.write or fs.edit to repair '{ticket.target_file}' immediately.\n"
            f"3. Provide complete, valid JavaScript/code that properly closes all functions, expressions, and blocks.\n"
            f"4. Do NOT switch model tiers or request other informational tools until this syntax error is resolved."
        )
        return directive

    def resolve_ticket(self, target_file: str) -> Optional[SyntaxRepairTicket]:
        """Mark a syntax ticket resolved after successful validation."""
        ticket_key = Path(target_file).name.lower()
        ticket = self.active_tickets.pop(ticket_key, None)
        if ticket:
            ticket.is_active = False
        return ticket

    def has_unresolved_syntax_errors(self) -> bool:
        """Check if any active syntax repair tickets remain."""
        return any(t.is_active for t in self.active_tickets.values())
