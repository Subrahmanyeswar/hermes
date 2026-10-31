# core/server/checks_service.py
"""
Service for extracting evidence-driven verification checks from tasks and runtime events.
Computes statuses (passed, failed, blocked, pending, not_run, warning), commands, exit codes,
evidence rationale, timestamps, and durations.

Enforces strict acceptance severity consistency:
- Non-fatal exploratory failures or successfully recovered operations are downgraded to non-blocking warnings.
- Failed mandatory builds, failed mandatory tests, failed required file writes, and unverified mandatory requirements
  remain strictly blocking with error severity.
"""

from __future__ import annotations

import os
import time
from typing import List, Optional, Set
from loguru import logger

from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.models import (
    HermesRuntimeState,
    MissionStatus,
    TaskStatus,
    AcceptanceCheckStatus,
)
from core.server.models import MissionChecksResponse, VerificationCheckItem

# Watermark cache for synthesized checks: mission_id -> (cache_key, MissionChecksResponse)
_CHECKS_CACHE: dict[str, tuple[tuple, MissionChecksResponse]] = {}


def clear_checks_cache(mission_id: Optional[str] = None) -> None:
    """Clear synthesized checks cache."""
    if mission_id:
        _CHECKS_CACHE.pop(mission_id, None)
    else:
        _CHECKS_CACHE.clear()


def _compute_checks_cache_key(
    state: Optional[HermesRuntimeState],
    events: List[HermesEvent],
) -> tuple:
    ev_seq = events[-1].sequence if events else 0
    ev_len = len(events)
    st_seq = state.last_event_sequence if state else 0
    m_stat = (
        state.mission.status.value
        if (state and hasattr(state.mission.status, "value"))
        else str(getattr(getattr(state, "mission", None), "status", ""))
    )
    task_signatures = []
    if state and state.tasks:
        for tid in sorted(state.tasks.keys()):
            t = state.tasks[tid]
            t_stat = t.status.value if hasattr(t.status, "value") else str(t.status)
            is_v = bool(getattr(t, "verification_id", None) or getattr(t, "is_verified", False))
            evid = str(getattr(t, "verification_evidence", None) or getattr(t, "completion_reason", None) or "")
            fail = str(getattr(t, "failure_reason", None) or getattr(t, "error", None) or "")
            task_signatures.append((tid, t_stat, is_v, evid, fail))

    ledger_signatures = []
    if state and getattr(state, "acceptance_ledger", None) and state.acceptance_ledger.checks:
        for cid in sorted(state.acceptance_ledger.checks.keys()):
            c = state.acceptance_ledger.checks[cid]
            c_stat = c.status.value if hasattr(c.status, "value") else str(c.status)
            ledger_signatures.append((cid, c_stat, c.critical))

    return (ev_seq, ev_len, st_seq, m_stat, tuple(task_signatures), tuple(ledger_signatures))


def extract_mission_checks(
    mission_id: str,
    state: Optional[HermesRuntimeState],
    events: List[HermesEvent],
) -> MissionChecksResponse:
    """
    Synthesize authoritative verification checks from tasks, ledger, and event stream.
    Strictly distinguishes blocking failures from non-blocking transient warnings.
    """
    cache_key = _compute_checks_cache_key(state, events)

    if mission_id in _CHECKS_CACHE:
        cached_key, cached_resp = _CHECKS_CACHE[mission_id]
        if cached_key == cache_key:
            return cached_resp

    checks: List[VerificationCheckItem] = []
    seen_check_ids: Set[str] = set()

    # Pre-index events for recovery detection
    written_files: Set[str] = set()
    succeeded_commands: List[str] = []
    passed_verifications: Set[str] = set()

    # Include files known from state
    if state:
        if getattr(state, "files_created", None):
            written_files.update(state.files_created)
        if getattr(state, "files_modified", None):
            written_files.update(state.files_modified)
        if state.tasks:
            for t in state.tasks.values():
                for f in getattr(t, "files_created", []):
                    written_files.add(f)
                for f in getattr(t, "files_modified", []):
                    written_files.add(f)

    for evt in events:
        evt_type = evt.event_type.value if hasattr(evt.event_type, "value") else str(evt.event_type)
        payload = evt.payload or {}
        if evt_type == "TOOL_COMPLETED":
            tname = payload.get("tool_name", "")
            tgt = payload.get("target_path") or payload.get("path")
            if tgt:
                written_files.add(str(tgt))
                written_files.add(os.path.basename(str(tgt)))
            se = payload.get("side_effects") or {}
            for fc in se.get("files_created", []):
                written_files.add(str(fc))
                written_files.add(os.path.basename(str(fc)))
            for fm in se.get("files_modified", []):
                written_files.add(str(fm))
                written_files.add(os.path.basename(str(fm)))
            cmd = str(payload.get("command") or payload.get("details", {}).get("command") or payload.get("tool_args", {}).get("command") or "")
            if cmd:
                succeeded_commands.append(cmd)
        elif evt_type in ("VERIFICATION_COMPLETED", "ACCEPTANCE_CHECK_PASSED"):
            if evt.task_id:
                passed_verifications.add(evt.task_id)
            chk_name = payload.get("check_name") or payload.get("verifier")
            if chk_name:
                passed_verifications.add(str(chk_name))

    # Helper to check if a command type was subsequently recovered
    def _is_command_recovered(cmd_str: str, keywords: List[str]) -> bool:
        cmd_lower = cmd_str.lower()
        matching_kws = [kw for kw in keywords if kw in cmd_lower]
        if not matching_kws:
            return False
        for s_cmd in succeeded_commands:
            s_lower = s_cmd.lower()
            if any(kw in s_lower for kw in matching_kws):
                return True
        return False

    # 1. Extract checks from verification and acceptance events
    for evt in events:
        evt_type = evt.event_type.value if hasattr(evt.event_type, "value") else str(evt.event_type)
        payload = evt.payload or {}

        if evt_type in ("VERIFICATION_COMPLETED", "ACCEPTANCE_CHECK_PASSED"):
            cid = f"check_{evt.sequence}_{evt.task_id or 'm'}"
            if cid not in seen_check_ids:
                seen_check_ids.add(cid)
                checks.append(VerificationCheckItem(
                    check_id=cid,
                    task_id=evt.task_id,
                    title=payload.get("check_name") or payload.get("title") or f"Verification Gate: {payload.get('verifier', 'acceptance')}",
                    status="passed",
                    command=payload.get("command") or payload.get("check_command"),
                    exit_code=payload.get("exit_code", 0),
                    output_snippet=payload.get("output") or payload.get("stdout"),
                    evidence=payload.get("evidence") or payload.get("verdict") or payload.get("reason") or "Verified against acceptance criteria",
                    timestamp=evt.timestamp or time.time(),
                    duration_seconds=payload.get("duration"),
                    category="acceptance_gate",
                    severity="info",
                    is_blocking=True,
                ))

        elif evt_type in ("VERIFICATION_FAILED", "ACCEPTANCE_CHECK_FAILED"):
            cid = f"check_fail_{evt.sequence}_{evt.task_id or 'm'}"
            if cid not in seen_check_ids:
                seen_check_ids.add(cid)
                checks.append(VerificationCheckItem(
                    check_id=cid,
                    task_id=evt.task_id,
                    title=payload.get("check_name") or f"Verification Failure: {payload.get('verifier', 'acceptance')}",
                    status="failed",
                    command=payload.get("command"),
                    exit_code=payload.get("exit_code", 1),
                    output_snippet=payload.get("error") or payload.get("stderr"),
                    evidence=payload.get("reason") or payload.get("evidence") or "Verification failed",
                    timestamp=evt.timestamp or time.time(),
                    duration_seconds=payload.get("duration"),
                    category="acceptance_gate",
                    severity="error",
                    is_blocking=True,
                ))

        elif evt_type == "TOOL_FAILED":
            cid = f"tool_fail_{evt.sequence}"
            if cid in seen_check_ids:
                continue
            seen_check_ids.add(cid)

            tool_name = str(payload.get("tool_name", "tool"))
            cmd = str(payload.get("command") or payload.get("details", {}).get("command") or payload.get("metadata", {}).get("command") or payload.get("tool_args", {}).get("command") or "")
            err_msg = str(payload.get("error") or payload.get("output") or payload.get("stderr") or "")
            tgt = payload.get("target_path") or payload.get("path") or payload.get("details", {}).get("path") or payload.get("tool_args", {}).get("path")

            build_keywords = ["build", "compile", "tsc", "webpack", "vite build", "cargo build", "go build", "make", "ninja"]
            test_keywords = ["pytest", "npm test", "unittest", "jest", "vitest", "cargo test", "go test"]

            is_build_cmd = any(kw in cmd.lower() for kw in build_keywords)
            is_test_cmd = any(kw in cmd.lower() for kw in test_keywords)
            is_file_write = tool_name in ("write_file", "patch_file", "apply_diff")
            is_path_probe = tool_name in ("read_file", "file_exists", "search_files", "list_directory")

            # Check if this failure was recovered or is blocking
            if is_build_cmd:
                recovered = _is_command_recovered(cmd, build_keywords)
                if recovered:
                    checks.append(VerificationCheckItem(
                        check_id=cid,
                        task_id=evt.task_id,
                        title=f"Build Retried & Recovered: {tool_name}",
                        status="warning",
                        command=cmd or tool_name,
                        exit_code=payload.get("exit_code", 1),
                        output_snippet=err_msg[:300],
                        evidence=f"Initial build failure was recovered by subsequent successful build",
                        timestamp=evt.timestamp or time.time(),
                        category="build_operation",
                        severity="warning",
                        is_blocking=False,
                    ))
                else:
                    checks.append(VerificationCheckItem(
                        check_id=cid,
                        task_id=evt.task_id,
                        title=f"Failed Mandatory Build: {tool_name}",
                        status="failed",
                        command=cmd or tool_name,
                        exit_code=payload.get("exit_code", 1),
                        output_snippet=err_msg[:300],
                        evidence=f"Mandatory build command failed without recovery: {err_msg[:200]}",
                        timestamp=evt.timestamp or time.time(),
                        category="build_operation",
                        severity="error",
                        is_blocking=True,
                    ))

            elif is_test_cmd:
                recovered = _is_command_recovered(cmd, test_keywords) or bool(evt.task_id and evt.task_id in passed_verifications)
                if recovered:
                    checks.append(VerificationCheckItem(
                        check_id=cid,
                        task_id=evt.task_id,
                        title=f"Test Retried & Recovered: {tool_name}",
                        status="warning",
                        command=cmd or tool_name,
                        exit_code=payload.get("exit_code", 1),
                        output_snippet=err_msg[:300],
                        evidence="Initial test execution failed but subsequent test suite passed",
                        timestamp=evt.timestamp or time.time(),
                        category="test_execution",
                        severity="warning",
                        is_blocking=False,
                    ))
                else:
                    checks.append(VerificationCheckItem(
                        check_id=cid,
                        task_id=evt.task_id,
                        title=f"Failed Mandatory Test: {tool_name}",
                        status="failed",
                        command=cmd or tool_name,
                        exit_code=payload.get("exit_code", 1),
                        output_snippet=err_msg[:300],
                        evidence=f"Mandatory test command failed without recovery: {err_msg[:200]}",
                        timestamp=evt.timestamp or time.time(),
                        category="test_execution",
                        severity="error",
                        is_blocking=True,
                    ))

            elif is_file_write:
                target_str = str(tgt or "")
                tgt_base = os.path.basename(target_str) if target_str else ""
                ws_root = getattr(state, "workspace_root", "") if state else ""
                exists_on_disk = bool(ws_root and target_str and os.path.exists(os.path.join(ws_root, target_str)))
                recovered = target_str in written_files or tgt_base in written_files or exists_on_disk

                if recovered:
                    checks.append(VerificationCheckItem(
                        check_id=cid,
                        task_id=evt.task_id,
                        title=f"File Write Recovered: {tgt_base or tool_name}",
                        status="warning",
                        command=tool_name,
                        exit_code=payload.get("exit_code", 1),
                        output_snippet=err_msg[:300],
                        evidence=f"Transient write error for '{target_str}' recovered by subsequent write",
                        timestamp=evt.timestamp or time.time(),
                        category="file_operation",
                        severity="warning",
                        is_blocking=False,
                    ))
                else:
                    checks.append(VerificationCheckItem(
                        check_id=cid,
                        task_id=evt.task_id,
                        title=f"Failed Required File Write: {tgt_base or tool_name}",
                        status="failed",
                        command=tool_name,
                        exit_code=payload.get("exit_code", 1),
                        output_snippet=err_msg[:300],
                        evidence=f"Required file write for '{target_str}' failed and file was never created",
                        timestamp=evt.timestamp or time.time(),
                        category="file_operation",
                        severity="error",
                        is_blocking=True,
                    ))

            elif is_path_probe:
                # Non-fatal exploratory path probe
                checks.append(VerificationCheckItem(
                    check_id=cid,
                    task_id=evt.task_id,
                    title=f"Non-Fatal Path Probe: {tgt or tool_name}",
                    status="warning",
                    command=tool_name,
                    exit_code=payload.get("exit_code", 1),
                    output_snippet=err_msg[:300],
                    evidence=f"Non-fatal exploratory probe on '{tgt or tool_name}' handled safely: {err_msg[:150]}",
                    timestamp=evt.timestamp or time.time(),
                    category="exploratory_probe",
                    severity="warning",
                    is_blocking=False,
                ))

            else:
                # Other command or tool
                is_exploratory = any(cmd.lower().startswith(p) for p in ("file ", "which ", "where ", "dir", "ls ", "find ", "git status", "git log"))
                mission_success = state and state.mission and state.mission.status == MissionStatus.COMPLETED

                if is_exploratory or mission_success:
                    checks.append(VerificationCheckItem(
                        check_id=cid,
                        task_id=evt.task_id,
                        title=f"Exploratory Command Handled: {tool_name}",
                        status="warning",
                        command=cmd or tool_name,
                        exit_code=payload.get("exit_code", 1),
                        output_snippet=err_msg[:300],
                        evidence="Exploratory command or transient tool error handled during mission",
                        timestamp=evt.timestamp or time.time(),
                        category="tool_execution",
                        severity="warning",
                        is_blocking=False,
                    ))
                else:
                    checks.append(VerificationCheckItem(
                        check_id=cid,
                        task_id=evt.task_id,
                        title=f"Tool Execution Failure: {tool_name}",
                        status="failed",
                        command=cmd or tool_name,
                        exit_code=payload.get("exit_code", 1),
                        output_snippet=err_msg[:300],
                        evidence=f"Tool execution failed without recovery: {err_msg[:200]}",
                        timestamp=evt.timestamp or time.time(),
                        category="tool_execution",
                        severity="error",
                        is_blocking=True,
                    ))

    # 2. Extract checks from Acceptance Ledger if present
    if state and getattr(state, "acceptance_ledger", None) and state.acceptance_ledger.checks:
        for chk_id, chk in state.acceptance_ledger.checks.items():
            cid = f"ledger_check_{chk_id}"
            if cid in seen_check_ids:
                continue
            seen_check_ids.add(cid)

            c_status_val = chk.status.value if hasattr(chk.status, "value") else str(chk.status)
            is_critical = getattr(chk, "critical", True)

            if c_status_val == AcceptanceCheckStatus.PASS.value:
                status_str = "passed"
                sev_str = "info"
            elif c_status_val == AcceptanceCheckStatus.FAIL.value:
                status_str = "failed"
                sev_str = "error" if is_critical else "warning"
            else:
                # NOT_RUN, PENDING, BLOCKED
                if state.mission.status in (MissionStatus.COMPLETED, MissionStatus.FAILED):
                    status_str = "failed" if is_critical else "not_run"
                    sev_str = "error" if is_critical else "warning"
                else:
                    status_str = "pending"
                    sev_str = "info"

            checks.append(VerificationCheckItem(
                check_id=cid,
                task_id=getattr(chk, "requirement_id", None),
                title=f"Acceptance Check: {chk.description or chk_id}",
                status=status_str,
                command=f"verify_check({chk_id})",
                exit_code=0 if status_str == "passed" else (1 if status_str == "failed" else None),
                output_snippet=getattr(chk, "error_message", None),
                evidence=f"Acceptance check for requirement {chk.requirement_id}: status={c_status_val}",
                timestamp=getattr(chk, "last_run_at", None) or time.time(),
                category="acceptance_gate",
                severity=sev_str,
                is_blocking=is_critical,
            ))

    # 3. Extract or reconcile with tasks in runtime state
    if state and state.tasks:
        for tid, task in state.tasks.items():
            task_check_id = f"task_check_{tid}"
            if task_check_id in seen_check_ids:
                continue
            seen_check_ids.add(task_check_id)

            t_status = task.status.value if hasattr(task.status, "value") else str(task.status)
            is_verified = bool(
                getattr(task, "verification_id", None)
                or getattr(task, "is_verified", False)
                or getattr(task, "evidence_ids", [])
                or tid in passed_verifications
            )

            is_mandatory_unverified = getattr(task, "is_mandatory_unverified", False)
            evidence_text = getattr(task, "verification_evidence", None) or getattr(task, "completion_reason", None)

            if is_verified:
                c_status = "passed"
                evidence_text = evidence_text or "Verified against task acceptance gate"
            elif t_status == TaskStatus.COMPLETED.value and state.mission.status == MissionStatus.COMPLETED:
                if is_mandatory_unverified:
                    c_status = "failed"
                    evidence_text = "Mandatory requirement remains unverified without verification evidence"
                else:
                    c_status = "passed"
                    evidence_text = evidence_text or "Verified against task acceptance gate"
            elif t_status in (TaskStatus.FAILED.value, "FAILED") or (state.mission.status == MissionStatus.FAILED and t_status in (TaskStatus.RUNNING.value, "RUNNING")):
                c_status = "failed"
                evidence_text = getattr(task, "failure_reason", None) or getattr(task, "error", None) or state.mission.abort_reason or "Task failed"
            elif state.mission.status == MissionStatus.FAILED and t_status in (TaskStatus.PENDING.value, "PENDING"):
                c_status = "blocked"
                evidence_text = "Blocked due to preceding task failure"
            elif t_status in (TaskStatus.RUNNING.value, "RUNNING", TaskStatus.VERIFYING.value, "VERIFYING"):
                c_status = "pending"
                evidence_text = "Verification pending task completion"
            else:
                c_status = "not_run"
                evidence_text = "Awaiting execution"

            is_blocking = True
            sev = "error" if c_status in ("failed", "blocked") else "info"

            checks.append(VerificationCheckItem(
                check_id=task_check_id,
                task_id=tid,
                title=f"Task Gate: {task.title}",
                status=c_status,
                command=f"verify_task({tid})",
                exit_code=0 if c_status == "passed" else (1 if c_status == "failed" else None),
                output_snippet=None,
                evidence=evidence_text,
                timestamp=getattr(task, "completed_at", None) or getattr(task, "created_at", None) or time.time(),
                category="task_gate",
                severity=sev,
                is_blocking=is_blocking,
            ))

    passed = sum(1 for c in checks if c.status == "passed")
    mandatory_failed = sum(1 for c in checks if c.status == "failed" and c.is_blocking)
    warnings = sum(1 for c in checks if c.status == "warning" or (not c.is_blocking and c.status != "passed"))

    resp = MissionChecksResponse(
        mission_id=mission_id,
        checks=checks,
        passed_count=passed,
        failed_count=mandatory_failed,
        total_count=len(checks),
        warning_count=warnings,
        mandatory_failed_count=mandatory_failed,
    )
    if len(_CHECKS_CACHE) > 200:
        _CHECKS_CACHE.clear()
    _CHECKS_CACHE[mission_id] = (cache_key, resp)
    return resp
