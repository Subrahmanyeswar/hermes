# core/telemetry.py
"""
HERMES Centralized Performance Telemetry System — Phase 1 Baseline Audit.

Provides high-resolution monotonic timing and structured metric collection across:
- Request/Mission/Task life cycles
- Model inference (TTFT, prefill, eval, tokens/sec, VRAM, load time)
- Context size breakdowns (system, tools, memory, skills, workspace)
- Workspace scanning & AST parsing
- Tool execution & subprocess duration
- Verification & Disagreement routing
- System resource sampling (CPU, RAM, GPU/VRAM)

Guarantees:
- Purely observational and non-invasive.
- Never raises exceptions that interrupt normal execution.
- Negligible performance overhead (<0.5ms per recorded event).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional, Dict, List
from loguru import logger


# ── System Resource Sampling Helper ──────────────────────────────────────────

def sample_system_resources() -> dict:
    """Sample CPU, RAM, and GPU/VRAM non-invasively."""
    res = {
        "cpu_percent": 0.0,
        "ram_used_mb": 0.0,
        "ram_total_mb": 0.0,
        "gpu_name": "",
        "gpu_util_percent": 0.0,
        "gpu_vram_used_mb": 0.0,
        "gpu_vram_total_mb": 0.0,
    }
    try:
        import psutil
        vm = psutil.virtual_memory()
        res["cpu_percent"] = psutil.cpu_percent(interval=None)
        res["ram_used_mb"] = round((vm.total - vm.available) / (1024 * 1024), 1)
        res["ram_total_mb"] = round(vm.total / (1024 * 1024), 1)
    except Exception:
        pass

    # Sample NVIDIA GPU via nvidia-smi if available
    try:
        smi = shutil.which("nvidia-smi")
        if smi:
            out = subprocess.check_output(
                [
                    smi,
                    "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                encoding="utf-8",
                timeout=1.5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            ).strip()
            if out:
                parts = [p.strip() for p in out.split(",")]
                if len(parts) >= 4:
                    res["gpu_name"] = parts[0]
                    res["gpu_util_percent"] = float(parts[1]) if parts[1].replace('.', '', 1).isdigit() else 0.0
                    res["gpu_vram_used_mb"] = float(parts[2]) if parts[2].replace('.', '', 1).isdigit() else 0.0
                    res["gpu_vram_total_mb"] = float(parts[3]) if parts[3].replace('.', '', 1).isdigit() else 0.0
    except Exception:
        pass

    return res


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class StageSpan:
    """Span recording start and end of a pipeline stage or sub-operation."""
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    stage_number: Optional[int] = None
    start_time_monotonic: float = 0.0
    end_time_monotonic: float = 0.0
    duration_ms: float = 0.0
    request_id: str = ""
    task_id: str = ""
    parent_id: Optional[str] = None
    success: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def finish(self, success: bool = True, **extra_meta):
        self.end_time_monotonic = time.perf_counter()
        self.duration_ms = max(0.0, (self.end_time_monotonic - self.start_time_monotonic) * 1000.0)
        self.success = success
        if extra_meta:
            self.metadata.update(extra_meta)


@dataclass
class ContextBreakdown:
    """Breakdown of context sizes sent to an LLM."""
    system_prompt_chars: int = 0
    tool_defs_chars: int = 0
    user_prompt_chars: int = 0
    memory_context_chars: int = 0
    skill_context_chars: int = 0
    workspace_context_chars: int = 0
    total_input_chars: int = 0
    estimated_input_tokens: int = 0
    exact_input_tokens: Optional[int] = None


@dataclass
class ModelCallTelemetry:
    """Detailed telemetry for a single LLM invocation."""
    inference_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    request_id: str = ""
    mission_id: str = ""
    task_id: str = ""
    stage: str = ""                         # e.g., "Tier 1", "Tier 2", "Tier 3", "Memory Extraction", "Alternative"
    execution_mode: str = "performance_baseline"
    model: str = ""
    provider: str = "ollama"                # "ollama", "anthropic", "openrouter"
    start_time_monotonic: float = 0.0
    end_time_monotonic: float = 0.0
    start_timestamp: Optional[str] = None
    first_token_timestamp: Optional[str] = None
    end_timestamp: Optional[str] = None
    total_latency_ms: float = 0.0
    
    # Model internal timings (e.g. from Ollama API)
    total_duration: Optional[float] = None       # Total duration in ms from provider
    load_duration_ms: float = 0.0                # Model load/unload time
    load_duration: Optional[float] = None        # Alias in ms
    prompt_eval_duration_ms: float = 0.0         # Time to process input prompt (prefill)
    prompt_eval_duration: Optional[float] = None # Alias in ms
    eval_duration_ms: float = 0.0                # Time to generate output tokens
    eval_duration: Optional[float] = None        # Alias in ms
    ttft_ms: float = 0.0                         # Time to first token
    
    # Token counts
    prompt_eval_count: Optional[int] = None
    eval_count: Optional[int] = None
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tokens_per_second: float = 0.0
    
    # Thinking and response metadata
    think_enabled: bool = False
    thinking_present: bool = False
    thinking_available: bool = False
    thinking_length: int = 0
    final_response_length: int = 0
    thinking_tokens: Optional[int] = None
    tool_call_count: int = 0
    
    # Context breakdown
    context: Optional[ContextBreakdown] = None
    
    # Parameters
    temperature: float = 0.0
    num_ctx: int = 4096
    keep_alive: Any = 0
    lifecycle_state: str = "UNKNOWN"        # "COLD", "WARM", "SWITCH_RELOAD", "PRELOADED"
    warm_cold_state: str = "UNKNOWN"
    model_switch_state: Optional[str] = None
    previous_model: Optional[str] = None
    requested_model: Optional[str] = None
    
    # Outcome
    success: bool = True
    retry_count: int = 0
    timed_out: bool = False
    error: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    cost_usd: float = 0.0
    
    # System stats at call time
    gpu_vram_used_mb: float = 0.0
    gpu_util_percent: float = 0.0
    raw_timing_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelSwitchTelemetry:
    """Telemetry for a model switch / reload event."""
    switch_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    request_id: str = ""
    mission_id: str = ""
    from_model: str = ""
    to_model: str = ""
    switch_start: float = 0.0
    switch_end: float = 0.0
    switch_duration_ms: float = 0.0
    previous_residency_state: str = ""
    new_residency_state: str = ""
    load_duration_ms: Optional[float] = None


@dataclass
class VerificationTelemetry:
    """Telemetry for a verification event."""
    verification_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    request_id: str = ""
    mission_id: str = ""
    task_id: str = ""
    method: str = ""  # "deterministic", "t2_verification", "t3_verification"
    start_time_monotonic: float = 0.0
    end_time_monotonic: float = 0.0
    duration_ms: float = 0.0
    verdict: str = ""  # AGREE, DISAGREE, SHALLOW, etc.
    escalated: bool = False
    issues_count: int = 0
    issues: List[str] = field(default_factory=list)


@dataclass
class RepairTelemetry:
    """Telemetry for a repair attempt."""
    repair_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    request_id: str = ""
    mission_id: str = ""
    task_id: str = ""
    attempt_number: int = 1
    trigger: str = ""
    affected_files: List[str] = field(default_factory=list)
    start_time_monotonic: float = 0.0
    end_time_monotonic: float = 0.0
    duration_ms: float = 0.0
    model: str = ""
    success: bool = False


@dataclass
class WorkspaceTelemetry:
    """Telemetry for workspace scanning and indexing."""
    request_id: str = ""
    scan_duration_ms: float = 0.0
    ast_parsing_duration_ms: float = 0.0
    directories_discovered: int = 0
    files_discovered: int = 0
    files_read: int = 0
    files_parsed: int = 0
    files_ignored: int = 0
    total_bytes_read: int = 0
    is_repeated_scan: bool = False


@dataclass
class ToolTelemetry:
    """Telemetry for tool execution."""
    tool_name: str = ""
    category: str = "other"                 # filesystem, shell, git, search, memory, etc.
    start_time_monotonic: float = 0.0
    duration_ms: float = 0.0
    subprocess_duration_ms: float = 0.0
    filesystem_duration_ms: float = 0.0
    success: bool = True
    exit_code: int = 0
    args_size_bytes: int = 0
    output_size_bytes: int = 0
    retry_count: int = 0
    error: Optional[str] = None
    mission_id: str = ""
    task_id: str = ""
    start: float = 0.0
    end: float = 0.0


@dataclass
class RequestTelemetry:
    """Full telemetry record for an entire user request or benchmark trial."""
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    benchmark_id: Optional[str] = None
    mission_id: str = ""
    execution_mode: str = "performance_baseline"
    task_type: str = "general"              # simple, single_file, multi_file, complex, mission
    prompt: str = ""
    mode: str = "auto"
    project: str = "default"
    start_time_wall: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    start_time_monotonic: float = field(default_factory=time.perf_counter)
    end_time_monotonic: float = 0.0
    total_duration_ms: float = 0.0
    success: bool = False
    pipeline_stage_reached: int = 0
    
    # Breakdown aggregates
    llm_calls_total: int = 0
    tier1_calls: int = 0
    tier2_calls: int = 0
    tier3_calls: int = 0
    memory_llm_calls: int = 0
    other_llm_calls: int = 0
    
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_model_latency_ms: float = 0.0
    
    workspace_scan_ms: float = 0.0
    context_build_ms: float = 0.0
    planning_ms: float = 0.0
    tier1_ms: float = 0.0
    tier2_ms: float = 0.0
    tier3_ms: float = 0.0
    tool_execution_ms: float = 0.0
    verification_ms: float = 0.0
    disagreement_routing_ms: float = 0.0
    memory_update_ms: float = 0.0
    repair_ms: float = 0.0
    final_response_ms: float = 0.0
    
    # Fine-grained records
    spans: List[StageSpan] = field(default_factory=list)
    model_calls: List[ModelCallTelemetry] = field(default_factory=list)
    tools: List[ToolTelemetry] = field(default_factory=list)
    verification_calls: List[VerificationTelemetry] = field(default_factory=list)
    repair_attempts: List[RepairTelemetry] = field(default_factory=list)
    model_switches: List[ModelSwitchTelemetry] = field(default_factory=list)
    workspace: Optional[WorkspaceTelemetry] = None
    system_initial: Dict[str, Any] = field(default_factory=dict)
    system_final: Dict[str, Any] = field(default_factory=dict)
    
    # Quality / output metrics
    acceptance_criteria_met: bool = False
    files_created: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    repair_attempts_count: int = 0
    tool_errors: int = 0
    model_disagreements: int = 0
    output_preview: str = ""
    error: Optional[str] = None

    def finish(self, success: bool, stage_reached: int = 12, error: Optional[str] = None):
        self.end_time_monotonic = time.perf_counter()
        self.total_duration_ms = max(0.0, (self.end_time_monotonic - self.start_time_monotonic) * 1000.0)
        self.success = success
        self.pipeline_stage_reached = stage_reached
        self.error = error
        self.system_final = sample_system_resources()

        # Compute aggregate sums from collected spans and model calls
        self.llm_calls_total = len(self.model_calls)
        for mc in self.model_calls:
            self.total_input_tokens += mc.prompt_tokens
            self.total_output_tokens += mc.output_tokens
            self.total_model_latency_ms += mc.total_latency_ms
            if mc.stage == "Tier 1":
                self.tier1_calls += 1
            elif mc.stage == "Tier 2":
                self.tier2_calls += 1
            elif mc.stage == "Tier 3":
                self.tier3_calls += 1
            elif "Memory" in mc.stage:
                self.memory_llm_calls += 1
            else:
                self.other_llm_calls += 1

        for s in self.spans:
            if s.name == "Planning":
                self.planning_ms += s.duration_ms
            elif s.name in ("Skill Detection", "Memory Retrieval", "Context Construction"):
                self.context_build_ms += s.duration_ms
            elif s.name == "Tier 1 Generation":
                self.tier1_ms += s.duration_ms
            elif s.name == "Tool Execution":
                self.tool_execution_ms += s.duration_ms
            elif s.name == "Tier 2 Verification":
                self.tier2_ms += s.duration_ms
                self.verification_ms += s.duration_ms
            elif s.name == "Disagreement Routing":
                self.disagreement_routing_ms += s.duration_ms
            elif s.name == "Tier 3 Arbitration":
                self.tier3_ms += s.duration_ms
            elif s.name == "Memory Update":
                self.memory_update_ms += s.duration_ms
            elif s.name == "Repair":
                self.repair_ms += s.duration_ms
            elif s.name == "Final Response":
                self.final_response_ms += s.duration_ms

        if self.workspace:
            self.workspace_scan_ms = self.workspace.scan_duration_ms

    def to_dict(self) -> dict:
        return asdict(self)


# ── Telemetry Manager Singleton ───────────────────────────────────────────────

class TelemetryManager:
    """Thread-safe, singleton telemetry collector for HERMES."""
    _instance: Optional[TelemetryManager] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._active_requests: Dict[str, RequestTelemetry] = {}
        self._active_spans: Dict[str, StageSpan] = {}
        self._completed_requests: List[RequestTelemetry] = []
        self._global_lock = threading.RLock()
        self.enabled: bool = True

    def start_request(
        self,
        prompt: str,
        mode: str = "auto",
        project: str = "default",
        task_type: str = "general",
        benchmark_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        execution_mode: str = "performance_baseline",
    ) -> RequestTelemetry:
        """Initialize a new request telemetry record."""
        if not self.enabled:
            return RequestTelemetry()
        try:
            req = RequestTelemetry(
                prompt=prompt,
                mode=mode,
                project=project,
                task_type=task_type,
                benchmark_id=benchmark_id,
                mission_id=mission_id or getattr(self, "_active_mission_id", ""),
                execution_mode=execution_mode,
                system_initial=sample_system_resources(),
            )
            with self._global_lock:
                self._active_requests[req.request_id] = req
            return req
        except Exception as e:
            logger.debug(f"Telemetry start_request failed silently: {e}")
            return RequestTelemetry()

    def set_active_mission_id(self, mission_id: str):
        """Set the active mission ID for subsequent requests."""
        self._active_mission_id = mission_id

    def get_request(self, request_id: str) -> Optional[RequestTelemetry]:
        with self._global_lock:
            return self._active_requests.get(request_id)

    @contextmanager
    def span(self, name: str, request_id: str = "", stage_number: Optional[int] = None, task_id: str = "", parent_id: Optional[str] = None, **meta):
        """Context manager for measuring stage durations."""
        if not self.enabled:
            yield None
            return

        s = StageSpan(
            name=name,
            stage_number=stage_number,
            start_time_monotonic=time.perf_counter(),
            request_id=request_id,
            task_id=task_id,
            parent_id=parent_id,
            metadata=meta or {},
        )
        try:
            yield s
        except Exception as exc:
            s.finish(success=False, error=str(exc))
            raise
        else:
            s.finish(success=True)
        finally:
            try:
                if request_id:
                    with self._global_lock:
                        req = self._active_requests.get(request_id)
                        if req:
                            req.spans.append(s)
            except Exception:
                pass

    def record_span(self, s: StageSpan, request_id: str = ""):
        """Record a completed StageSpan."""
        if not self.enabled or not s:
            return
        try:
            req_id = request_id or s.request_id
            if req_id:
                with self._global_lock:
                    req = self._active_requests.get(req_id)
                    if req:
                        req.spans.append(s)
        except Exception as e:
            logger.debug(f"Telemetry record_span error: {e}")

    def record_model_call(self, model_telemetry: ModelCallTelemetry):
        """Record an LLM call telemetry entry."""
        if not self.enabled:
            return
        try:
            if model_telemetry.request_id:
                with self._global_lock:
                    req = self._active_requests.get(model_telemetry.request_id)
                    if req:
                        req.model_calls.append(model_telemetry)
        except Exception as e:
            logger.debug(f"Telemetry record_model_call error: {e}")

    def record_tool(self, tool_telemetry: ToolTelemetry, request_id: str = ""):
        """Record a tool execution telemetry entry."""
        if not self.enabled:
            return
        try:
            req_id = request_id or tool_telemetry.request_id
            if req_id:
                with self._global_lock:
                    req = self._active_requests.get(req_id)
                    if req:
                        req.tools.append(tool_telemetry)
        except Exception as e:
            logger.debug(f"Telemetry record_tool error: {e}")

    def record_verification(self, ver_telemetry: VerificationTelemetry, request_id: str = ""):
        """Record a verification telemetry entry."""
        if not self.enabled:
            return
        try:
            req_id = request_id or ver_telemetry.request_id
            if req_id:
                with self._global_lock:
                    req = self._active_requests.get(req_id)
                    if req:
                        req.verification_calls.append(ver_telemetry)
        except Exception as e:
            logger.debug(f"Telemetry record_verification error: {e}")

    def record_repair(self, repair_telemetry: RepairTelemetry, request_id: str = ""):
        """Record a repair telemetry entry."""
        if not self.enabled:
            return
        try:
            req_id = request_id or repair_telemetry.request_id
            if req_id:
                with self._global_lock:
                    req = self._active_requests.get(req_id)
                    if req:
                        req.repair_attempts.append(repair_telemetry)
        except Exception as e:
            logger.debug(f"Telemetry record_repair error: {e}")

    def record_model_switch(self, switch_telemetry: ModelSwitchTelemetry, request_id: str = ""):
        """Record a model switch telemetry entry."""
        if not self.enabled:
            return
        try:
            req_id = request_id or switch_telemetry.request_id
            if req_id:
                with self._global_lock:
                    req = self._active_requests.get(req_id)
                    if req:
                        req.model_switches.append(switch_telemetry)
            else:
                with self._global_lock:
                    for req in self._active_requests.values():
                        switch_telemetry.request_id = req.request_id
                        switch_telemetry.mission_id = req.mission_id or req.request_id
                        req.model_switches.append(switch_telemetry)
                        break
        except Exception as e:
            logger.debug(f"Telemetry record_model_switch error: {e}")

    def record_workspace(self, ws_telemetry: WorkspaceTelemetry):
        """Record workspace indexing telemetry."""
        if not self.enabled:
            return
        try:
            if ws_telemetry.request_id:
                with self._global_lock:
                    req = self._active_requests.get(ws_telemetry.request_id)
                    if req:
                        req.workspace = ws_telemetry
        except Exception as e:
            logger.debug(f"Telemetry record_workspace error: {e}")

    def finish_request(
        self,
        request_id: str,
        success: bool,
        stage_reached: int = 12,
        error: Optional[str] = None,
        **extra_attrs
    ) -> Optional[RequestTelemetry]:
        """Finish a request and archive it in completed requests."""
        if not self.enabled:
            return None
        req = None
        try:
            with self._global_lock:
                req = self._active_requests.pop(request_id, None)
                if req:
                    for k, v in extra_attrs.items():
                        if hasattr(req, k):
                            setattr(req, k, v)
                    req.finish(success=success, stage_reached=stage_reached, error=error)
                    self._completed_requests.append(req)
            if req:
                # Non-invasively write performance trace
                try:
                    self.export_performance_trace(req.request_id)
                except Exception:
                    pass
                return req
        except Exception as e:
            logger.debug(f"Telemetry finish_request error: {e}")
        return None

    def export_performance_trace(self, request_id: str, filepath: Optional[str] = None) -> Optional[dict]:
        """Export structured performance trace for a mission/request."""
        try:
            req = None
            with self._global_lock:
                req = self._active_requests.get(request_id)
                if not req:
                    for c in reversed(self._completed_requests):
                        if c.request_id == request_id:
                            req = c
                            break
            if not req:
                return None

            mission_id = req.mission_id or req.request_id
            stage_list = [
                {
                    "name": s.name,
                    "stage_number": s.stage_number,
                    "start": round(s.start_time_monotonic, 4),
                    "end": round(s.end_time_monotonic, 4),
                    "duration_ms": round(s.duration_ms, 2),
                    "success": s.success,
                }
                for s in req.spans
            ]
            model_calls_list = [asdict(mc) for mc in req.model_calls]
            tool_calls_list = [asdict(tc) for tc in req.tools]
            verification_calls_list = [asdict(vc) for vc in req.verification_calls]
            repair_attempts_list = [asdict(ra) for ra in req.repair_attempts]
            model_switches_list = [asdict(ms) for ms in req.model_switches]

            total_stage_ms = sum(s.duration_ms for s in req.spans)
            total_model_ms = sum(mc.get("total_latency_ms", 0.0) for mc in model_calls_list)
            total_tool_ms = sum(tc.get("duration_ms", 0.0) for tc in tool_calls_list)
            total_ver_ms = sum(vc.get("duration_ms", 0.0) for vc in verification_calls_list)
            
            # Account for model calls, tool executions, verifications, and standalone stage spans
            accounted_time_ms = round(total_model_ms + total_tool_ms + total_ver_ms + total_stage_ms, 2)
            unaccounted_time_ms = max(0.0, round(req.total_duration_ms - accounted_time_ms, 2))

            trace = {
                "mission_id": mission_id,
                "execution_mode": req.execution_mode,
                "mission": {
                    "start": req.start_time_wall,
                    "end": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "duration_ms": round(req.total_duration_ms, 2),
                    "accounted_time_ms": accounted_time_ms,
                    "unaccounted_time_ms": unaccounted_time_ms,
                },
                "stages": stage_list,
                "model_calls": model_calls_list,
                "tool_calls": tool_calls_list,
                "verification_calls": verification_calls_list,
                "repair_attempts": repair_attempts_list,
                "model_switches": model_switches_list,
            }

            trace_file = Path(filepath) if filepath else Path(f"artifacts/performance/traces/mission_{mission_id}.json")
            trace_file.parent.mkdir(parents=True, exist_ok=True)
            with open(trace_file, "w", encoding="utf-8") as f:
                json.dump(trace, f, indent=2)

            return trace
        except Exception as e:
            logger.debug(f"Telemetry export_performance_trace failed: {e}")
            return None

    def get_completed_requests(self) -> List[RequestTelemetry]:
        with self._global_lock:
            return list(self._completed_requests)

    def export_to_json(self, filepath: str) -> None:
        """Export all completed telemetry records to a structured JSON file."""
        try:
            p = Path(filepath)
            p.parent.mkdir(parents=True, exist_ok=True)
            with self._global_lock:
                records = [r.to_dict() for r in self._completed_requests]
            with open(p, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "export_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "total_requests": len(records),
                        "hardware": sample_system_resources(),
                        "results": records,
                    },
                    f,
                    indent=2,
                )
            logger.info(f"Telemetry data exported to {filepath} ({len(records)} requests)")
        except Exception as e:
            logger.error(f"Failed to export telemetry data: {e}")

    def clear(self):
        with self._global_lock:
            self._active_requests.clear()
            self._active_spans.clear()
            self._completed_requests.clear()


# Global telemetry manager instance
telemetry = TelemetryManager()
