# memory/session_logger.py
# Layer 3 session logging for HERMES.
# Every request, response, and tool execution is logged to a JSONL file.
# One file per session (day + session ID).
# These logs are NEVER loaded into the context window.
# They are used only for: grep search, KAIROS consolidation input, debugging.
# Format: one JSON object per line (JSONL).

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from loguru import logger

SESSION_LOG_DIR = Path("data/sessions")

from dataclasses import dataclass, field

@dataclass
class SessionEvent:
    """A single event in a HERMES session."""
    event_type: str          # "user_input", "tier1_response", "tool_call", "tool_result",
                             # "tier2_verification", "tier3_arbitration", "memory_update"
    session_id: str
    content: dict[str, Any]  # event-specific data
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_jsonl_line(self) -> str:
        """Serialize to a single-line JSON string for JSONL format."""
        return json.dumps({
            "event_type": self.event_type,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            **self.content
        }, ensure_ascii=False)

class SessionLogger:
    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.log_dir = SESSION_LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")
        self.log_path = self.log_dir / f"{date_str}_{self.session_id}.jsonl"
        logger.info(f"Session started: {self.session_id} | log: {self.log_path}")
        
    def _append_event(self, event: SessionEvent) -> None:
        try:
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(event.to_jsonl_line() + '\n')
        except Exception as e:
            logger.warning(f"Failed to write to session log: {e}")
            
    def log_user_input(self, prompt: str) -> None:
        event = SessionEvent(
            event_type="user_input",
            session_id=self.session_id,
            content={"prompt": prompt}
        )
        self._append_event(event)
        
    def log_tier1_response(self, model: str, response: str, latency_seconds: float, parsed_tool: Optional[str] = None) -> None:
        event = SessionEvent(
            event_type="tier1_response",
            session_id=self.session_id,
            content={
                "model": model,
                "response": response[:500],
                "latency_seconds": round(latency_seconds, 3),
                "parsed_tool": parsed_tool
            }
        )
        self._append_event(event)
        
    def log_tool_call(self, tool_name: str, parameters: dict, mode: str) -> None:
        event = SessionEvent(
            event_type="tool_call",
            session_id=self.session_id,
            content={
                "tool_name": tool_name,
                "parameters": parameters,
                "mode": mode
            }
        )
        self._append_event(event)
        
    def log_tool_result(self, tool_name: str, success: bool, exit_code: int, output_preview: str, duration_seconds: float) -> None:
        event = SessionEvent(
            event_type="tool_result",
            session_id=self.session_id,
            content={
                "tool_name": tool_name,
                "success": success,
                "exit_code": exit_code,
                "output_preview": output_preview[:300],
                "duration_seconds": round(duration_seconds, 3)
            }
        )
        self._append_event(event)
        
    def log_tier2_verification(self, model: str, agree: bool, confidence: float, issues: list[str], risk_score: float, latency_seconds: float) -> None:
        event = SessionEvent(
            event_type="tier2_verification",
            session_id=self.session_id,
            content={
                "model": model,
                "agree": agree,
                "confidence": confidence,
                "issues": issues,
                "risk_score": risk_score,
                "latency_seconds": latency_seconds
            }
        )
        self._append_event(event)
        
    def log_tier3_arbitration(self, decision: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        event = SessionEvent(
            event_type="tier3_arbitration",
            session_id=self.session_id,
            content={
                "decision": decision,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd
            }
        )
        self._append_event(event)
        
    def log_memory_update(self, facts_written: int, project: str) -> None:
        event = SessionEvent(
            event_type="memory_update",
            session_id=self.session_id,
            content={
                "facts_written": facts_written,
                "project": project
            }
        )
        self._append_event(event)
        
    def get_recent_events(self, event_type: Optional[str] = None, limit: int = 20) -> list[dict]:
        if not self.log_path.exists():
            return []
            
        events = []
        try:
            with open(self.log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        parsed = json.loads(line)
                        if event_type and parsed.get("event_type") != event_type:
                            continue
                        events.append(parsed)
                    except json.JSONDecodeError:
                        continue
                        
            return events[-limit:] if limit > 0 else events
        except Exception as e:
            logger.warning(f"Failed to read session log: {e}")
            return []
