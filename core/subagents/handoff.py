# core/subagents/handoff.py
"""
Subagent Handoff & Observation Formatting for HERMES 2.x.

Core Invariants:
1. Subagent SUCCESS != Requirement VERIFIED != Goal COMPLETE:
   A successful subagent result is evidence, not automatic goal completion.
2. Bounded Context: Handoff messages are strictly bounded (default 50KB); larger artifacts
   are externalized to file-backed artifact paths.
3. Clean Loop Integration: Converts SubagentResult into the canonical AgentLoop Observation format.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.agent_loop.types import Observation
from core.runtime_state.models import (
    SubagentResult,
    SubagentStatus,
)


class HandoffManager:
    """
    Formats subagent results into bounded, structured observations for the parent AgentLoop.
    """

    @classmethod
    def format_observation(
        cls,
        result: SubagentResult,
        turn_id: str,
        workspace_root: Path | str,
        max_bytes: int = 50_000,
    ) -> Observation:
        """
        Convert a SubagentResult into an AgentLoop Observation.
        Externalizes large outputs to disk if they exceed max_bytes.
        """
        obs_id = f"obs_sub_{result.agent_id[:6]}_{uuid.uuid4().hex[:6]}"
        is_success = (result.status == SubagentStatus.SUCCEEDED)

        # Build clean markdown content
        lines = [
            f"### SUBAGENT EXECUTION REPORT: [{result.status.value}]",
            f"**Task ID:** `{result.task_id}` | **Agent ID:** `{result.agent_id}`",
            "",
            f"**Summary:** {result.summary}",
        ]

        if result.findings:
            lines.append("\n**Key Findings:**")
            for f in result.findings:
                lines.append(f"- {f}")

        if result.files:
            lines.append("\n**Modified/Generated Files:**")
            for fl in result.files:
                lines.append(f"- `{fl}`")

        if result.tests:
            lines.append(f"\n**Test Results:** {json.dumps(result.tests)}")

        if result.evidence_refs:
            lines.append(f"\n**Evidence References:** {', '.join(result.evidence_refs)}")

        if result.errors:
            lines.append("\n**Reported Errors:**")
            for err in result.errors:
                lines.append(f"- ⚠️ {err}")

        if result.next_recommendation:
            lines.append(f"\n**Recommended Next Action:** {result.next_recommendation}")

        raw_content = "\n".join(lines)

        # Check output boundedness
        encoded = raw_content.encode("utf-8")
        if len(encoded) > max_bytes:
            # Externalize full payload to disk
            art_dir = Path(workspace_root) / ".hermes" / "artifacts"
            art_dir.mkdir(parents=True, exist_ok=True)
            art_file = art_dir / f"subagent_{result.agent_id}_result.json"

            with open(art_file, "w", encoding="utf-8") as f:
                json.dump(result.to_dict(), f, indent=2)

            truncated_text = encoded[:max_bytes].decode("utf-8", errors="replace")
            content = (
                f"{truncated_text}\n\n"
                f"... [TRUNCATED — Full subagent payload externalized to `{art_file.as_posix()}`]"
            )
        else:
            content = raw_content

        return Observation(
            observation_id=obs_id,
            mission_id="",  # Injected by loop
            turn_id=turn_id,
            source_type="subagent",
            source_id=result.agent_id,
            success=is_success,
            summary=result.summary[:200] if result.summary else f"Subagent {result.status.value}",
            content=content,
            full_result_ref=result.artifact_refs[0] if result.artifact_refs else None,
            metadata={"artifact_refs": result.artifact_refs},
            exit_code=0 if is_success else 1,
        )
