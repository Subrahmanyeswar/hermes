# core/observability/logger.py
"""
Unified Multi-Stream Forensic Telemetry Logger for HERMES 2.x.
Persists structured JSONL logs, specialized domain streams, and live markdown forensic summaries.
Guarantees thread-safety, immediate error flushes, and automatic credential redaction.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import queue
import re
import threading
import time
import traceback
from pathlib import Path
from typing import Dict, Any, Optional, List

from core.observability.schemas import (
    ObservabilityEvent,
    TelemetrySeverity,
    FailureClassification,
)
from core.runtime_state.events import redact_sensitive_payload, redact_sensitive_str


def validate_run_id(run_id: str, base_dir: Optional[Path] = None) -> Path:
    """
    Validate run_id and return resolved safe Path within base_dir.
    Rejects path traversal, separators, invalid characters, and excessive lengths.
    """
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    run_id = run_id.strip()
    if len(run_id) > 128:
        raise ValueError(f"run_id exceeds maximum allowed length of 128 characters (got {len(run_id)})")
    if "/" in run_id or "\\" in run_id or ":" in run_id or "\0" in run_id:
        raise ValueError(f"run_id contains invalid path separators or characters: {run_id!r}")
    if ".." in run_id:
        raise ValueError(f"run_id contains directory traversal sequences: {run_id!r}")
    if not re.match(r"^[a-zA-Z0-9_\-]+(\.[a-zA-Z0-9_\-]+)*$", run_id):
        raise ValueError(f"run_id contains invalid characters: {run_id!r}")

    root = (base_dir or (Path(__file__).resolve().parent.parent.parent / "artifacts" / "observability")).resolve()
    target = (root / run_id).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError(f"run_id path escapes base directory: {run_id!r}")
    if target == root:
        raise ValueError("run_id cannot resolve to the root directory")
    return target


def sanitize_tool_call_id(tool_call_id: Optional[str]) -> str:
    """Sanitize tool_call_id so it cannot inject path separators or escape directories."""
    if not tool_call_id:
        return "call"
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(tool_call_id)).strip("._")
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned[:64] or "call"


class MissionTelemetryLogger:
    """
    Forensic Telemetry Manager for a single execution Run.
    Outputs structured JSON Lines to specialized logs in `artifacts/observability/<run_id>/`.
    """

    def __init__(
        self,
        run_id: str,
        mission_id: str,
        base_dir: Optional[Path] = None,
    ):
        self.run_id: str = run_id
        self.mission_id: str = mission_id
        
        # Base observability directory
        root = base_dir or (Path(__file__).resolve().parent.parent.parent / "artifacts" / "observability")
        self.log_dir: Path = validate_run_id(run_id, root)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Subdirectories for offloaded large payloads
        self.payloads_dir: Path = self.log_dir / "payloads"
        self.payloads_dir.mkdir(exist_ok=True)
        self.tool_outputs_dir: Path = self.log_dir / "tool_outputs"
        self.tool_outputs_dir.mkdir(exist_ok=True)

        # File paths
        self.files: Dict[str, Path] = {
            "events": self.log_dir / "events.jsonl",
            "models": self.log_dir / "models.jsonl",
            "tools": self.log_dir / "tools.jsonl",
            "recovery": self.log_dir / "recovery.jsonl",
            "files": self.log_dir / "files.jsonl",
            "validation": self.log_dir / "validation.jsonl",
            "runtime": self.log_dir / "runtime.jsonl",
            "errors": self.log_dir / "errors.jsonl",
        }
        self.summary_path: Path = self.log_dir / "mission_summary.md"

        self._lock = threading.Lock()
        self._closed = False
        self._event_seq = 0
        self._completed_tool_ops: set[str] = set()
        self._counted_tool_calls: set[str] = set()
        self._stats = {
            "total_events": 0,
            "model_calls": 0,
            "tool_calls": 0,
            "recoveries": 0,
            "errors": 0,
            "start_time": time.time(),
        }

        # Initialize all 8 stream files so all exist deterministically
        for stream_file in self.files.values():
            if not stream_file.exists():
                stream_file.touch()

        # Register in active telemetry loggers registry
        with _TELEMETRY_LOCK:
            _ACTIVE_TELEMETRY_LOGGERS[run_id] = self

        # Initialize streams with runtime header event
        self.record_runtime_snapshot(reason="TELEMETRY_INITIALIZED")

    # ── Core Event Recording ──────────────────────────────────────────────────

    def log_event(
        self,
        event_type: str,
        component: str,
        severity: str = "INFO",
        message: str = "",
        turn: Optional[int] = None,
        tier: Optional[int] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        duration_ms: Optional[float] = None,
        status: Optional[str] = None,
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        destinations: Optional[List[str]] = None,
    ) -> ObservabilityEvent:
        """
        Record a structured event into events.jsonl and optionally into specialized logs.
        """
        clean_payload = redact_sensitive_payload(payload or {})
        clean_msg = redact_sensitive_str(message)

        if event_type in ("TOOL_COMPLETED", "TOOL_FAILED"):
            t_id = clean_payload.get("tool_call_id")
            a_id = clean_payload.get("action_id")
            o_id = clean_payload.get("operation_id")
            keys = {k for k in (t_id, a_id, o_id) if k}
            if not keys and clean_payload.get("tool_name"):
                keys.add(f"{turn}_{clean_payload.get('tool_name')}_{clean_payload.get('target_path')}")
            if keys:
                with self._lock:
                    if any(k in self._completed_tool_ops for k in keys):
                        return ObservabilityEvent(
                            event_type=event_type,
                            component=component,
                            severity=severity,
                            message=clean_msg,
                            run_id=self.run_id,
                            mission_id=self.mission_id,
                            turn=turn,
                            event_seq=self._event_seq,
                            payload=clean_payload,
                        )
                    self._completed_tool_ops.update(keys)
                    if not any(k in self._counted_tool_calls for k in keys):
                        self._counted_tool_calls.update(keys)
                        self._stats["tool_calls"] += 1

        with self._lock:
            self._event_seq += 1
            seq = self._event_seq
            self._stats["total_events"] += 1
            if severity in ("ERROR", "CRITICAL"):
                self._stats["errors"] += 1

        evt = ObservabilityEvent(
            event_type=event_type,
            component=component,
            severity=severity,
            message=clean_msg,
            run_id=self.run_id,
            mission_id=self.mission_id,
            turn=turn,
            event_seq=seq,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            tier=tier,
            provider=provider,
            model=model,
            duration_ms=duration_ms,
            status=status,
            payload=clean_payload,
        )

        dests = set(destinations or [])
        dests.add("events")  # All events always go to events.jsonl

        if severity in ("WARN", "WARNING", "ERROR", "CRITICAL"):
            dests.add("errors")

        line = json.dumps(evt.to_dict(), default=str) + "\n"
        with self._lock:
            for dest in dests:
                if dest in self.files:
                    target_file = self.files[dest]
                    with open(target_file, "a", encoding="utf-8") as f:
                        f.write(line)
                        if severity in ("WARN", "WARNING", "ERROR", "CRITICAL"):
                            f.flush()

        return evt

    # ── Specialized Domain Loggers ───────────────────────────────────────────

    def record_model_call(
        self,
        turn: int,
        tier: int,
        provider: str,
        model: str,
        duration_ms: float,
        status: str,
        params: Dict[str, Any],
        timings: Dict[str, Any],
        response_meta: Dict[str, Any],
        error_details: Optional[Dict[str, Any]] = None,
        raw_prompt: Optional[str] = None,
        raw_response: Optional[str] = None,
    ) -> None:
        """Record model/provider request and response telemetry in models.jsonl."""
        with self._lock:
            self._stats["model_calls"] += 1

        payload_ref = None
        if raw_prompt and len(raw_prompt) > 8000:
            clean_prompt = redact_sensitive_str(raw_prompt)
            h = hashlib.sha256(clean_prompt.encode("utf-8")).hexdigest()
            p_file = self.payloads_dir / f"prompt_{self._event_seq}_{h[:10]}.txt"
            with open(p_file, "w", encoding="utf-8") as pf:
                pf.write(clean_prompt)
            payload_ref = {"prompt_file": str(p_file), "sha256": h, "chars": len(clean_prompt)}

        resp_ref = None
        if raw_response and len(raw_response) > 8000:
            clean_response = redact_sensitive_str(raw_response)
            rh = hashlib.sha256(clean_response.encode("utf-8")).hexdigest()
            r_file = self.payloads_dir / f"response_{self._event_seq}_{rh[:10]}.txt"
            with open(r_file, "w", encoding="utf-8") as rf:
                rf.write(clean_response)
            resp_ref = {"response_file": str(r_file), "sha256": rh, "chars": len(clean_response)}

        payload = {
            "tier": tier,
            "provider": provider,
            "model": model,
            "params": redact_sensitive_payload(params),
            "timings": timings,
            "response": redact_sensitive_payload(response_meta),
            "error_details": redact_sensitive_payload(error_details or {}),
            "prompt_ref": payload_ref,
            "response_ref": resp_ref,
        }

        sev = "INFO" if status == "SUCCESS" else "ERROR"
        self.log_event(
            event_type="MODEL_REQUEST_COMPLETED" if status == "SUCCESS" else "MODEL_REQUEST_FAILED",
            component="model_provider",
            severity=sev,
            message=f"Tier {tier} [{provider}/{model}] {status} in {duration_ms:.1f}ms",
            turn=turn,
            tier=tier,
            provider=provider,
            model=model,
            duration_ms=duration_ms,
            status=status,
            payload=payload,
            destinations=["models"],
        )

    def record_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        turn: Optional[int],
        duration_ms: float,
        success: bool,
        exit_code: Optional[int] = None,
        arguments: Optional[Dict[str, Any]] = None,
        target_path: Optional[str] = None,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Record tool invocation, parameters, and output in tools.jsonl."""
        keys = {k for k in (tool_call_id, target_path) if k}
        already_logged = False
        with self._lock:
            if any(k in self._completed_tool_ops for k in keys):
                already_logged = True

        redacted_stdout = redact_sensitive_str(stdout) if stdout else None
        redacted_stderr = redact_sensitive_str(stderr) if stderr else None
        redacted_error = redact_sensitive_str(error_message) if error_message else None
        safe_tool_id = sanitize_tool_call_id(tool_call_id)

        stdout_ref = None
        if redacted_stdout and len(redacted_stdout) > 6000:
            h = hashlib.sha256(redacted_stdout.encode("utf-8")).hexdigest()
            sf = (self.tool_outputs_dir / f"stdout_{safe_tool_id}_{h[:10]}.txt").resolve()
            try:
                sf.relative_to(self.tool_outputs_dir.resolve())
            except ValueError:
                sf = self.tool_outputs_dir / f"stdout_sanitized_{h[:16]}.txt"
            with open(sf, "w", encoding="utf-8") as f:
                f.write(redacted_stdout)
            stdout_ref = {"file": str(sf), "sha256": h, "chars": len(redacted_stdout)}

        stderr_ref = None
        if redacted_stderr and len(redacted_stderr) > 6000:
            eh = hashlib.sha256(redacted_stderr.encode("utf-8")).hexdigest()
            ef = (self.tool_outputs_dir / f"stderr_{safe_tool_id}_{eh[:10]}.txt").resolve()
            try:
                ef.relative_to(self.tool_outputs_dir.resolve())
            except ValueError:
                ef = self.tool_outputs_dir / f"stderr_sanitized_{eh[:16]}.txt"
            with open(ef, "w", encoding="utf-8") as f:
                f.write(redacted_stderr)
            stderr_ref = {"file": str(ef), "sha256": eh, "chars": len(redacted_stderr)}

        payload = {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "target_path": target_path,
            "arguments": redact_sensitive_payload(arguments or {}),
            "exit_code": exit_code,
            "stdout_summary": (redacted_stdout[:500] + "...") if (redacted_stdout and len(redacted_stdout) > 500) else redacted_stdout,
            "stderr_summary": (redacted_stderr[:500] + "...") if (redacted_stderr and len(redacted_stderr) > 500) else redacted_stderr,
            "stdout_ref": stdout_ref,
            "stderr_ref": stderr_ref,
            "error_message": redacted_error,
        }

        if not already_logged:
            sev = "INFO" if success else "ERROR"
            self.log_event(
                event_type="TOOL_COMPLETED" if success else "TOOL_FAILED",
                component="tool_execution",
                severity=sev,
                message=f"Tool {tool_name} {'succeeded' if success else 'failed'} (exit={exit_code}) in {duration_ms:.1f}ms",
                turn=turn,
                duration_ms=duration_ms,
                status="SUCCESS" if success else "FAILED",
                payload=payload,
                destinations=["tools"],
            )

    def record_recovery_decision(
        self,
        turn: Optional[int],
        failure_class: str,
        fingerprint: str,
        from_tier: int,
        to_tier: int,
        reason: str,
        circuit_state: str,
        recovery_counters: Dict[str, Any],
        is_terminal: bool = False,
    ) -> None:
        """Record failure classification and tier transition in recovery.jsonl."""
        with self._lock:
            self._stats["recoveries"] += 1

        payload = {
            "failure_class": failure_class,
            "fingerprint": fingerprint,
            "from_tier": from_tier,
            "to_tier": to_tier,
            "reason": reason,
            "circuit_state": circuit_state,
            "recovery_counters": recovery_counters,
            "is_terminal": is_terminal,
        }

        sev = "CRITICAL" if is_terminal else "WARN"
        self.log_event(
            event_type="RECOVERY_TERMINATED" if is_terminal else "TIER_TRANSITION_COMPLETED",
            component="recovery_policy",
            severity=sev,
            message=f"Recovery: Tier {from_tier} -> Tier {to_tier} | {failure_class} | {reason}",
            turn=turn,
            tier=to_tier,
            status="TERMINATED" if is_terminal else "ESCALATED",
            payload=payload,
            destinations=["recovery"],
        )

    def record_file_operation(
        self,
        relative_path: str,
        operation: str,
        size_before: Optional[int],
        size_after: Optional[int],
        sha256_before: Optional[str],
        sha256_after: Optional[str],
        content_changed: bool,
        provenance: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record filesystem mutation in files.jsonl."""
        payload = {
            "file": relative_path,
            "operation": operation,
            "size_before": size_before,
            "size_after": size_after,
            "sha256_before": sha256_before,
            "sha256_after": sha256_after,
            "content_changed": content_changed,
            "provenance": provenance or {},
        }
        self.log_event(
            event_type="FILE_WRITE_COMPLETED" if operation == "write" else "FILE_EDIT_COMPLETED",
            component="filesystem",
            severity="INFO",
            message=f"File {operation}: {relative_path} ({size_after or 0} bytes, changed={content_changed})",
            payload=payload,
            destinations=["files"],
        )

    def record_validation_result(
        self,
        validator_name: str,
        target_file: str,
        success: bool,
        duration_ms: float,
        exit_code: Optional[int],
        diagnostic: Optional[Dict[str, Any]] = None,
        raw_output: Optional[str] = None,
    ) -> None:
        """Record validation and compiler checks in validation.jsonl."""
        payload = {
            "validator": validator_name,
            "target_file": target_file,
            "success": success,
            "exit_code": exit_code,
            "diagnostic": diagnostic or {},
            "raw_output": (raw_output[:500] + "...") if (raw_output and len(raw_output) > 500) else raw_output,
        }
        sev = "INFO" if success else "ERROR"
        self.log_event(
            event_type="VALIDATION_PASSED" if success else "VALIDATION_FAILED",
            component="validation",
            severity=sev,
            message=f"Validation [{validator_name}] on {target_file}: {'PASSED' if success else 'FAILED'}",
            duration_ms=duration_ms,
            status="PASSED" if success else "FAILED",
            payload=payload,
            destinations=["validation"],
        )

    def record_runtime_snapshot(self, reason: str = "SNAPSHOT") -> None:
        """Record running backend process state, executable, and code fingerprints."""
        import sys
        from core.server.app import _compute_code_fingerprint, _SERVER_CODE_FINGERPRINT
        disk_fp = _compute_code_fingerprint()
        is_synced = bool(_SERVER_CODE_FINGERPRINT == disk_fp)

        payload = {
            "pid": os.getpid(),
            "python_executable": sys.executable,
            "python_version": sys.version,
            "loaded_fingerprint": _SERVER_CODE_FINGERPRINT,
            "disk_fingerprint": disk_fp,
            "is_synced": is_synced,
            "runtime_status": "SYNCED" if is_synced else "STALE_RUNTIME",
            "reason": reason,
        }
        self.log_event(
            event_type="RUNTIME_SNAPSHOT",
            component="backend_runtime",
            severity="INFO" if is_synced else "WARN",
            message=f"Runtime state: {'SYNCED' if is_synced else 'STALE_RUNTIME'} (PID {os.getpid()})",
            payload=payload,
            destinations=["runtime"],
        )

    def record_exception(
        self,
        component: str,
        exc: Exception,
        failure_class: Optional[str] = None,
        turn: Optional[int] = None,
        recovered: bool = False,
    ) -> None:
        """Record full exception with complete stack trace in errors.jsonl."""
        tb = traceback.format_exc()
        clean_tb = redact_sensitive_str(tb)
        clean_msg = redact_sensitive_str(str(exc))
        payload = {
            "exception_class": type(exc).__name__,
            "message": clean_msg,
            "failure_class": failure_class or "INTERNAL_HERMES_EXCEPTION",
            "recovered": recovered,
            "traceback": clean_tb,
        }
        self.log_event(
            event_type="EXCEPTION_HANDLED" if recovered else "UNHANDLED_EXCEPTION",
            component=component,
            severity="WARN" if recovered else "ERROR",
            message=f"Exception in {component}: {type(exc).__name__}: {clean_msg}",
            turn=turn,
            status="RECOVERED" if recovered else "FAILED",
            payload=payload,
            destinations=["errors"],
        )

    # ── Final Forensic Summary ───────────────────────────────────────────────

    def write_stream_manifest(self) -> Dict[str, Any]:
        """Generate and write stream manifest recording record counts and empty reasons."""
        manifest: Dict[str, Any] = {
            "run_id": self.run_id,
            "mission_id": self.mission_id,
            "streams": {},
        }
        empty_reasons = {
            "recovery": "No tier escalation or recovery transitions were required during this run.",
            "errors": "No warnings or errors occurred during execution.",
            "validation": "No syntax or compiler checks were executed during this run.",
            "files": "No files were modified during this execution.",
            "models": "No model calls were dispatched during this run.",
            "tools": "No tool operations were executed during this run.",
        }
        for name, file_path in self.files.items():
            b_size = file_path.stat().st_size if file_path.exists() else 0
            line_count = 0
            if file_path.exists() and b_size > 0:
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        line_count = sum(1 for line in f if line.strip())
                except Exception:
                    line_count = 1
            manifest["streams"][name] = {
                "file": file_path.name,
                "bytes": b_size,
                "record_count": line_count,
                "enabled": True,
                "reason_if_empty": empty_reasons.get(name, "No events recorded.") if line_count == 0 else None,
            }
        manifest_path = self.log_dir / "stream_manifest.json"
        try:
            with open(manifest_path, "w", encoding="utf-8") as mf:
                json.dump(manifest, mf, indent=2)
        except Exception as e:
            logger.debug(f"Failed to write stream manifest: {e}")
        return manifest

    def write_mission_summary(
        self,
        status: str,
        error: Optional[str] = None,
        total_turns: int = 0,
        elapsed_seconds: float = 0.0,
        final_tier: int = 1,
        written_files: Optional[List[str]] = None,
    ) -> Path:
        self.write_stream_manifest()
        """Write human-readable markdown forensic summary."""
        duration_fmt = f"{elapsed_seconds:.1f}s"
        summary_md = f"""# HERMES Mission Forensic Summary

- **Mission ID:** `{self.mission_id}`
- **Run ID:** `{self.run_id}`
- **Terminal Status:** `{status}`
- **Total Duration:** `{duration_fmt}`
- **Total Turns Executed:** `{total_turns}`
- **Final Active Tier:** `Tier {final_tier}`
- **Telemetry Event Count:** `{self._stats['total_events']}`
- **Model Invocations:** `{self._stats['model_calls']}`
- **Tool Invocations:** `{self._stats['tool_calls']}`
- **Recovery Transitions:** `{self._stats['recoveries']}`
- **Recorded Errors / Warnings:** `{self._stats['errors']}`

---

## Termination Diagnostic
- **Outcome:** {status}
- **Termination Reason / Error:**
```text
{error or "Mission completed successfully"}
```

---

## Artifacts Generated
{chr(10).join(f"- `{f}`" for f in (written_files or [])) if written_files else "- None"}

---

## Specialized Telemetry Log Index
- Full Chronological Stream: [`events.jsonl`](file:///{str(self.files['events']).replace('\\', '/')})
- Model & Provider Latencies: [`models.jsonl`](file:///{str(self.files['models']).replace('\\', '/')})
- Tool Invocations & Stdout/Stderr: [`tools.jsonl`](file:///{str(self.files['tools']).replace('\\', '/')})
- Recovery & Tier Escalations: [`recovery.jsonl`](file:///{str(self.files['recovery']).replace('\\', '/')})
- File Integrity & Provenance: [`files.jsonl`](file:///{str(self.files['files']).replace('\\', '/')})
- Compiler & Browser Validation: [`validation.jsonl`](file:///{str(self.files['validation']).replace('\\', '/')})
- Backend & Process Health: [`runtime.jsonl`](file:///{str(self.files['runtime']).replace('\\', '/')})
- Errors & Tracebacks: [`errors.jsonl`](file:///{str(self.files['errors']).replace('\\', '/')})

*Report automatically generated by HERMES Forensic Telemetry Engine.*
"""
        with open(self.summary_path, "w", encoding="utf-8") as f:
            f.write(summary_md)
        return self.summary_path


# Global Registry of active telemetry loggers: run_id -> MissionTelemetryLogger
_ACTIVE_TELEMETRY_LOGGERS: Dict[str, MissionTelemetryLogger] = {}
_TELEMETRY_LOCK = threading.RLock()


def get_telemetry_logger(run_id: str, mission_id: Optional[str] = None, base_dir: Optional[Path] = None) -> MissionTelemetryLogger:
    """Retrieve or create singleton MissionTelemetryLogger for a given run."""
    with _TELEMETRY_LOCK:
        root = (base_dir or (Path(__file__).resolve().parent.parent.parent / "artifacts" / "observability")).resolve()
        validate_run_id(run_id, root)
        if run_id not in _ACTIVE_TELEMETRY_LOGGERS:
            m_id = mission_id or "default"
            _ACTIVE_TELEMETRY_LOGGERS[run_id] = MissionTelemetryLogger(run_id=run_id, mission_id=m_id, base_dir=base_dir)
        return _ACTIVE_TELEMETRY_LOGGERS[run_id]
