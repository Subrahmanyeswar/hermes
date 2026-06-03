# utils/logging.py
# Centralised structured logging for HERMES.
# Every pipeline run gets a unique trace_id that flows through all 12 stages.
# All log records are emitted in two formats simultaneously:
#   1. Human-readable to stderr (for debugging during development)
#   2. Structured JSONL to data/sessions/ (for Layer 3 archive and grep)
#
# Log levels used across HERMES:
#   DEBUG:   Stage completions, tool details, model latencies
#   INFO:    Pipeline start/end, tool calls, memory writes, cost events
#   WARNING: Parse failures, retry attempts, degraded operation
#   ERROR:   Hard failures, exceptions, API errors
#
# NEVER log:
#   - ANTHROPIC_API_KEY or GITHUB_TOKEN values
#   - User file contents beyond first 100 characters
#   - Raw model responses beyond first 200 characters

import json
import sys
import uuid
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from loguru import logger

# ── Constants ─────────────────────────────────────────────────────────

SESSION_LOG_DIR = Path("data/sessions")
LOG_ROTATION_SIZE = "50 MB"
LOG_RETENTION_DAYS = "7 days"
_CURRENT_TRACE_ID: Optional[str] = None
_SESSION_ID: Optional[str] = None
_PIPELINE_START_TIME: Optional[float] = None


# ── ID Generation ─────────────────────────────────────────────────────

def generate_trace_id() -> str:
    """Generate a short unique trace ID for one pipeline run. Format: 8 hex characters."""
    return uuid.uuid4().hex[:8]


def generate_session_id() -> str:
    """Generate a session ID that persists for the entire application lifetime."""
    return uuid.uuid4().hex[:12]


# ── JSONL Sink Filter ─────────────────────────────────────────────────

def _jsonl_sink_filter(record) -> bool:
    """Filter for the JSONL sink. Emits all records as structured JSON lines."""
    # Build the JSONL record
    jsonl_record = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "session_id": _SESSION_ID,
        "trace_id": record["extra"].get("trace_id", ""),
        "message": record["message"],
        "module": record["name"],
        "function": record["function"],
        "line": record["line"],
    }

    # Merge any extra structured fields
    for key, value in record["extra"].items():
        if key != "trace_id":
            try:
                json.dumps(value)  # Only include JSON-serialisable values
                jsonl_record[key] = value
            except (TypeError, ValueError):
                jsonl_record[key] = str(value)[:200]

    # Write the JSONL line
    record["message"] = json.dumps(jsonl_record, ensure_ascii=False)
    return True


# ── Setup ─────────────────────────────────────────────────────────────

def setup_logging(session_id: Optional[str] = None, debug: bool = False, tui: bool = False) -> str:
    """Configure Loguru for HERMES. Call once at application startup. Returns the session_id."""
    global _SESSION_ID

    _SESSION_ID = session_id or generate_session_id()

    # ── Remove all default Loguru handlers ───────────────────────────────
    logger.remove()

    log_level = "DEBUG" if debug else "INFO"

    if not tui:
        # ── Handler 1: Human-readable to stderr ──────────────────────────────
        logger.add(
            sys.stderr,
            level=log_level,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{extra[trace_id]}</cyan> | "
                "{message}"
            ),
            colorize=True,
            filter=lambda record: "trace_id" in record["extra"]
        )

        # Also add a handler without trace_id filter for records that don't have it
        logger.add(
            sys.stderr,
            level=log_level,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<dim>--------</dim> | "
                "{message}"
            ),
            colorize=True,
            filter=lambda record: "trace_id" not in record["extra"]
        )
    else:
        # TUI custom sink to route logs to active app
        def tui_sink(message):
            try:
                from textual.app import App
                app = App.get_current_app()
                if app and hasattr(app, "handle_log_record"):
                    app.call_from_thread(app.handle_log_record, message.record)
            except Exception:
                pass

        logger.add(
            tui_sink,
            level=log_level,
            serialize=False,
        )

    # ── Handler 2: Structured JSONL to session file ───────────────────────
    SESSION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    log_file = SESSION_LOG_DIR / f"{date_str}_{_SESSION_ID}.jsonl"

    logger.add(
        str(log_file),
        level="DEBUG",
        format="{message}",              # We format manually in the sink
        rotation=LOG_ROTATION_SIZE,
        retention=LOG_RETENTION_DAYS,
        serialize=False,                 # We handle JSON serialisation ourselves
        filter=_jsonl_sink_filter,
        catch=True                       # Never crash due to logging errors
    )

    logger.info(f"HERMES logging initialised | session={_SESSION_ID} | debug={debug} | log={log_file}")
    return _SESSION_ID


# ── TraceContext ──────────────────────────────────────────────────────

class TraceContext:
    """
    Context manager that sets a trace_id for all log calls within its scope.

    Usage:
        with TraceContext(trace_id="abc12345") as ctx:
            logger.bind(trace_id=ctx.trace_id).info("This has a trace_id")

    Or use the module-level get_trace_logger() function for convenience.
    """

    def __init__(self, trace_id: Optional[str] = None):
        self.trace_id = trace_id or generate_trace_id()
        self._start_time = time.monotonic()

    def __enter__(self):
        global _CURRENT_TRACE_ID, _PIPELINE_START_TIME
        _CURRENT_TRACE_ID = self.trace_id
        _PIPELINE_START_TIME = self._start_time
        return self

    def __exit__(self, *args):
        global _CURRENT_TRACE_ID, _PIPELINE_START_TIME
        elapsed = time.monotonic() - self._start_time
        _CURRENT_TRACE_ID = None
        _PIPELINE_START_TIME = None
        return False  # Never suppress exceptions

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._start_time

    def get_logger(self):
        """Return a Loguru logger bound with this trace_id."""
        return logger.bind(trace_id=self.trace_id)


# ── Trace Logger ──────────────────────────────────────────────────────

def get_trace_logger(trace_id: str):
    """Return a Loguru logger bound with the given trace_id. Use this everywhere in the pipeline."""
    return logger.bind(trace_id=trace_id)


# ── Structured Log Functions ─────────────────────────────────────────

def log_pipeline_start(trace_id: str, user_request: str, mode: str, project: str, session_id: str) -> None:
    """Log the start of a pipeline run."""
    tlog = get_trace_logger(trace_id)
    tlog.info(
        "PIPELINE_START",
        extra={
            "trace_id": trace_id,
            "event": "pipeline_start",
            "user_request_preview": user_request[:100],
            "mode": mode,
            "project": project,
            "session_id": session_id,
        }
    )


def log_pipeline_complete(trace_id: str, success: bool, stage_reached: int,
                          total_latency: float, tool_name: Optional[str],
                          tier3_called: bool, cost_usd: float) -> None:
    """Log the completion of a pipeline run."""
    tlog = get_trace_logger(trace_id)
    tlog.info(
        f"PIPELINE_COMPLETE | success={success} | stage={stage_reached}/12 | "
        f"latency={total_latency:.2f}s | tool={tool_name} | tier3={tier3_called} | cost=${cost_usd:.4f}",
        extra={
            "trace_id": trace_id,
            "event": "pipeline_complete",
            "success": success,
            "stage_reached": stage_reached,
            "total_latency_seconds": round(total_latency, 3),
            "tool_name": tool_name,
            "tier3_called": tier3_called,
            "cost_usd": round(cost_usd, 6),
        }
    )


def log_tier1_call(trace_id: str, model: str, prompt_tokens_estimate: int,
                   latency: float, parsed_tool: Optional[str], parse_method: str) -> None:
    """Log a Tier 1 LLM call."""
    tlog = get_trace_logger(trace_id)
    tlog.debug(
        f"T1 | model={model} | latency={latency:.2f}s | tool={parsed_tool} | parse={parse_method}",
        extra={
            "trace_id": trace_id,
            "event": "tier1_call",
            "model": model,
            "prompt_tokens_estimate": prompt_tokens_estimate,
            "latency_seconds": round(latency, 3),
            "parsed_tool": parsed_tool,
            "parse_method": parse_method,
        }
    )


def log_tier2_call(trace_id: str, model: str, latency: float, agree: bool,
                   confidence: float, risk_score: float, escalated: bool) -> None:
    """Log a Tier 2 verification call."""
    tlog = get_trace_logger(trace_id)
    tlog.debug(
        f"T2 | model={model} | latency={latency:.2f}s | agree={agree} | "
        f"confidence={confidence:.2f} | risk={risk_score:.2f} | escalate={escalated}",
        extra={
            "trace_id": trace_id,
            "event": "tier2_call",
            "model": model,
            "latency_seconds": round(latency, 3),
            "agree": agree,
            "confidence": round(confidence, 3),
            "risk_score": round(risk_score, 3),
            "escalated": escalated,
        }
    )


def log_tier3_call(trace_id: str, latency: float, input_tokens: int,
                   output_tokens: int, cost_usd: float, success: bool,
                   escalation_reason: str) -> None:
    """Log a Tier 3 (Claude) API call."""
    tlog = get_trace_logger(trace_id)
    level = "info" if success else "warning"
    getattr(tlog, level)(
        f"T3 | latency={latency:.2f}s | tokens={input_tokens}+{output_tokens} | "
        f"cost=${cost_usd:.4f} | success={success}",
        extra={
            "trace_id": trace_id,
            "event": "tier3_call",
            "latency_seconds": round(latency, 3),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 6),
            "success": success,
            "escalation_reason": escalation_reason[:200],
        }
    )


def log_tool_call(trace_id: str, tool_name: str, mode: str, risk_score: float,
                  parameters_preview: str) -> None:
    """Log a tool invocation."""
    tlog = get_trace_logger(trace_id)
    tlog.info(
        f"TOOL_CALL | tool={tool_name} | mode={mode} | risk={risk_score:.2f}",
        extra={
            "trace_id": trace_id,
            "event": "tool_call",
            "tool_name": tool_name,
            "mode": mode,
            "risk_score": round(risk_score, 2),
            "parameters_preview": parameters_preview[:200],
        }
    )


def log_tool_result(trace_id: str, tool_name: str, success: bool, exit_code: int,
                    duration: float, output_preview: str, retry_count: int) -> None:
    """Log the result of a tool execution."""
    tlog = get_trace_logger(trace_id)
    level = "debug" if success else "warning"
    getattr(tlog, level)(
        f"TOOL_RESULT | tool={tool_name} | success={success} | exit={exit_code} | "
        f"duration={duration:.2f}s | retry={retry_count}",
        extra={
            "trace_id": trace_id,
            "event": "tool_result",
            "tool_name": tool_name,
            "success": success,
            "exit_code": exit_code,
            "duration_seconds": round(duration, 3),
            "output_preview": output_preview[:200],
            "retry_count": retry_count,
        }
    )


def log_memory_event(trace_id: str, event_type: str, facts_count: int,
                     project: str, detail: str = "") -> None:
    """Log a memory system event. event_type: 'read', 'write', 'consolidation', 'parse_error', 'fallback'."""
    tlog = get_trace_logger(trace_id)
    tlog.debug(
        f"MEMORY | type={event_type} | facts={facts_count} | project={project}",
        extra={
            "trace_id": trace_id,
            "event": f"memory_{event_type}",
            "event_type": event_type,
            "facts_count": facts_count,
            "project": project,
            "detail": detail[:200],
        }
    )


def log_security_gate(trace_id: str, command_preview: str, blocked: bool,
                      gate_name: str) -> None:
    """Log a security gate check."""
    tlog = get_trace_logger(trace_id)
    level = "warning" if blocked else "debug"
    getattr(tlog, level)(
        f"SECURITY | gate={gate_name} | blocked={blocked} | cmd={command_preview[:60]!r}",
        extra={
            "trace_id": trace_id,
            "event": "security_gate",
            "gate_name": gate_name,
            "blocked": blocked,
            "command_preview": command_preview[:100],
        }
    )


def log_kairos_event(event_type: str, detail: str, stats: Optional[dict] = None) -> None:
    """Log a KAIROS daemon event. These don't have a trace_id — they're background events."""
    logger.bind(trace_id="kairos").info(
        f"KAIROS | type={event_type} | {detail[:100]}",
        extra={
            "trace_id": "kairos",
            "event": f"kairos_{event_type}",
            "event_type": event_type,
            "detail": detail[:300],
            "stats": stats or {},
        }
    )


# ── Layer 3 Grep Access ──────────────────────────────────────────────

def search_session_logs(query: str, session_log_dir: Path = SESSION_LOG_DIR,
                        max_results: int = 20) -> list[dict]:
    """Layer 3 grep access — search all JSONL session logs for a query string. Returns parsed matching records."""
    results = []
    if not session_log_dir.exists():
        return results

    for log_file in sorted(session_log_dir.glob("*.jsonl"), reverse=True):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or query.lower() not in line.lower():
                        continue
                    try:
                        record = json.loads(line)
                        results.append(record)
                        if len(results) >= max_results:
                            return results
                    except json.JSONDecodeError:
                        # Raw loguru line that wasn't JSONL — skip
                        continue
        except (IOError, PermissionError):
            continue

    return results


def get_session_log_path(session_id: Optional[str] = None) -> Optional[Path]:
    """Get the path to a session's log file."""
    sid = session_id or _SESSION_ID
    if not sid:
        return None
    for f in SESSION_LOG_DIR.glob(f"*{sid}*.jsonl"):
        return f
    return None
