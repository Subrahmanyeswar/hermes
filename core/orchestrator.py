# core/orchestrator.py
# The HERMES Master Orchestrator — implements the full 12-stage pipeline.
# Every user request flows through this exactly once, top to bottom.
# Stage 1:  Sanitise user input
# Stage 2:  Task planner -> Task object
# Stage 3:  Skill + Memory injection -> enriched system prompt
# Stage 4:  Tier 1 generation -> JSON tool call
# Stage 5:  Tool validation + safety gates
# Stage 6:  Tool execution
# Stage 7:  Tier 2 verification
# Stage 8:  Disagreement router -> decision
# Stage 9:  Tier 3 arbitration (conditional)
# Stage 10: Memory update (only if exit_code == 0)
# Stage 11: Task queue update
# Stage 12: Build and return final output

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any

from loguru import logger

from core.error_handler import ErrorHandler, FailureMode, RecoveryAction
from utils.logging import (
    generate_trace_id, setup_logging,
    log_pipeline_start, log_pipeline_complete,
    log_tier1_call, log_tier2_call, log_tier3_call,
    log_tool_call, log_tool_result, log_memory_event,
    log_security_gate, get_trace_logger
)

from models.ollama_client import OllamaClient
from models.claude_client import ClaudeClient
from core.verifier import Tier2Verifier
from core.disagreement_router import DisagreementRouter, RoutingDecision
from core.planner import TaskPlanner, Task
from core.intent_classifier import IntentClassifier
from core.prompt_builder import PromptContext, build_system_prompt, build_user_message
import tools  # Triggers tool registration
from tools.registry import get_tool, tool_schema_for_prompt, list_tools, PermissionGate
from tools.base import ToolResult
from memory.store import read_context_for_prompt
from memory.extractor import confirm_and_write_facts, extract_memories
from memory.session_logger import SessionLogger
from kairos.db import init_db, DB_PATH
from kairos.task_queue import register_task, mark_running, mark_completed, mark_failed
from kairos.daemon import KairosDaemon


# ──────────────────────────────────────────────────────────────────────
# Result type
# ──────────────────────────────────────────────────────────────────────

@dataclass
class OrchestratorResult:
    """The complete result of one orchestrator pipeline run."""
    success: bool
    final_output: str                    # What to show the user
    tool_name: Optional[str] = None
    tool_result: Optional[ToolResult] = None
    task: Optional[Task] = None
    skill_ids_used: list[str] = field(default_factory=list)
    tier3_was_called: bool = False
    total_latency_seconds: float = 0.0
    error: Optional[str] = None
    pipeline_stage_reached: int = 0      # Which stage completed last
    trace_id: str = ""                   # Unique trace ID for this pipeline run


# ──────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────

class Orchestrator:
    """
    Master 12-stage pipeline controller for HERMES.
    Every user request flows through this exactly once, top to bottom.
    Never raises — always returns an OrchestratorResult.
    """

    def __init__(self, mode: str = "auto", project: str = "default"):
        self.mode = mode        # "safe", "plan", or "auto"
        self.project = project
        self.ollama = OllamaClient()
        self.claude = ClaudeClient()
        self.verifier = Tier2Verifier(self.ollama)
        self.router = DisagreementRouter()
        self.planner = TaskPlanner()
        self.classifier = IntentClassifier("skills/")
        self.session_logger = SessionLogger()
        logger.info(
            f"Orchestrator ready | mode={mode} | project={project} | "
            f"session={self.session_logger.session_id}"
        )
        self.error_handler = ErrorHandler()
        # Initialise database and KAIROS daemon
        init_db()
        self.kairos = KairosDaemon(db_path=DB_PATH)
        self._kairos_started = False
        logger.info("Orchestrator: KAIROS daemon attached (not yet started)")

    async def start_kairos(self) -> None:
        """Start the KAIROS background daemon. Call this once after creating the Orchestrator."""
        if not self._kairos_started:
            await self.kairos.start()
            self._kairos_started = True
            logger.info("Orchestrator: KAIROS daemon running in background")

    async def stop_kairos(self) -> None:
        """Stop the KAIROS daemon gracefully. Call this on application shutdown."""
        if self._kairos_started:
            await self.kairos.stop()
            self._kairos_started = False

    async def run(self, user_request: str) -> OrchestratorResult:
        """
        Run the full 12-stage pipeline for one user request.
        Never raises — always returns OrchestratorResult.
        """
        start_time = time.monotonic()
        # Generate unique trace ID for this pipeline run
        trace_id = generate_trace_id()
        tlog = get_trace_logger(trace_id)
        result = OrchestratorResult(success=False, final_output="", trace_id=trace_id)

        try:
            # ── Stage 1: Sanitise input ───────────────────────────────
            result.pipeline_stage_reached = 1
            sanitised = self._sanitise_input(user_request)
            self.session_logger.log_user_input(sanitised)
            log_pipeline_start(
                trace_id=trace_id,
                user_request=sanitised,
                mode=self.mode,
                project=self.project,
                session_id=self.session_logger.session_id
            )
            tlog.debug(f"Stage 1 complete | sanitised_length={len(sanitised)}")

            # ── Stage 2: Task planner ─────────────────────────────────
            result.pipeline_stage_reached = 2
            task = self.planner.plan(sanitised, session_id=self.session_logger.session_id)
            result.task = task
            logger.debug(f"Stage 2 complete: task planned | complexity={task.complexity_score:.2f}")

            # Register task in SQLite queue
            db_task_id = register_task(
                session_id=self.session_logger.session_id,
                title=sanitised[:100],
                description=sanitised,
                priority=task.priority,
                complexity=task.complexity_score,
                max_retries=task.max_retries,
                tool_name=None,  # Will be updated after Stage 4
                db_path=DB_PATH
            )
            mark_running(db_task_id, db_path=DB_PATH)
            logger.debug(f"Stage 2: task registered in queue as db_task_id={db_task_id}")

            # ── Stage 3: Skill + Memory injection (with memory parse error fallback) ──
            result.pipeline_stage_reached = 3

            skill_ids = self.classifier.classify(sanitised)
            skill_content, loaded_skill_ids = self.classifier.build_skill_prompt_section(skill_ids)
            result.skill_ids_used = loaded_skill_ids
            active_skill_name = loaded_skill_ids[0] if loaded_skill_ids else "none"

            try:
                memory_context = read_context_for_prompt(project=self.project)
            except Exception as mem_exc:
                mem_err = self.error_handler.memory_parse_error(str(mem_exc), self.project)
                logger.warning(f"Stage 3: {mem_err.technical_detail}")
                memory_context = ""  # Empty fallback — session continues normally

            logger.debug(f"Stage 3 complete: skills={loaded_skill_ids} | memory_lines={memory_context.count(chr(10))}")

            # ── Stage 4: Tier 1 generation (with JSON parse failure handling) ──────
            result.pipeline_stage_reached = 4

            ctx = PromptContext(
                user_task=sanitised,
                mode=self.mode,
                available_tools=list_tools(),
                tool_descriptions=tool_schema_for_prompt(),
                memory_context=memory_context,
                skill_context=skill_content,
                active_skill_name=active_skill_name
            )
            system_prompt = build_system_prompt(ctx)
            user_message_text = build_user_message(sanitised)

            # ── Attempt 1: standard prompt ──────────────────────────────────────
            t1_start = time.monotonic()
            try:
                tier1_raw = await self.ollama.generate(
                    model="qwen2.5-coder:7b",
                    prompt=user_message_text,
                    system=system_prompt,
                    keep_alive=0
                )
                t1_latency = time.monotonic() - t1_start
            except Exception as t1_exc:
                # Check if this is a timeout
                t1_latency = time.monotonic() - t1_start
                from models.ollama_client import OllamaTimeoutError
                if isinstance(t1_exc, OllamaTimeoutError):
                    err = self.error_handler.ollama_timeout("qwen2.5-coder:7b", 120, "stage_4_attempt_1")
                else:
                    err = self.error_handler.unknown_error(t1_exc, "stage_4_t1_generation")
                result.final_output = err.tagged_output(err.user_message)
                result.error = err.technical_detail
                mark_failed(db_task_id, error=err.technical_detail[:300], db_path=DB_PATH)
                return result

            tier1_parsed = self._parse_tier1_response(tier1_raw)

            # ── Attempt 2: V2 prompt on parse failure ───────────────────────────
            if tier1_parsed is None:
                parse_err = self.error_handler.json_parse_failure(tier1_raw, attempt=0)
                logger.warning(f"Stage 4: {parse_err.technical_detail}")
                self.session_logger.log_tier1_response("qwen2.5-coder:7b", tier1_raw[:300], t1_latency, None)

                from core.prompt_builder import build_system_prompt_v2
                retry_system = build_system_prompt_v2(ctx)
                retry_user = user_message_text + "\n\n" + parse_err.context_for_retry

                t1_retry_start = time.monotonic()
                try:
                    tier1_raw = await self.ollama.generate(
                        model="qwen2.5-coder:7b",
                        prompt=retry_user,
                        system=retry_system,
                        keep_alive=0
                    )
                    t1_latency = time.monotonic() - t1_retry_start
                except Exception as retry_exc:
                    t1_latency = time.monotonic() - t1_retry_start
                    from models.ollama_client import OllamaTimeoutError
                    if isinstance(retry_exc, OllamaTimeoutError):
                        err = self.error_handler.ollama_timeout("qwen2.5-coder:7b", 120, "stage_4_attempt_2")
                    else:
                        err = self.error_handler.unknown_error(retry_exc, "stage_4_t1_retry")
                    result.final_output = err.tagged_output(err.user_message)
                    result.error = err.technical_detail
                    mark_failed(db_task_id, error=err.technical_detail[:300], db_path=DB_PATH)
                    return result

                tier1_parsed = self._parse_tier1_response(tier1_raw)

                if tier1_parsed is None:
                    # Both attempts failed
                    final_err = self.error_handler.json_parse_failure(tier1_raw, attempt=1)
                    result.final_output = final_err.user_message
                    result.error = final_err.technical_detail
                    mark_failed(db_task_id, error=final_err.technical_detail[:300], db_path=DB_PATH)
                    return result

            tool_name = tier1_parsed.get("tool", "")
            tool_params = tier1_parsed.get("parameters", {})
            tier1_reasoning = tier1_parsed.get("reasoning", "")

            self.session_logger.log_tier1_response(
                "qwen2.5-coder:7b", tier1_raw[:500], t1_latency, tool_name
            )
            log_tier1_call(
                trace_id=trace_id,
                model="qwen2.5-coder:7b",
                prompt_tokens_estimate=len(system_prompt) // 4,
                latency=t1_latency,
                parsed_tool=tool_name,
                parse_method=getattr(
                    getattr(tier1_parsed, '_parse_method', None),
                    '__name__', 'direct'
                ) if hasattr(tier1_parsed, '_parse_method') else "parsed"
            )
            tlog.debug(f"Stage 4 complete | tool={tool_name} | latency={t1_latency:.2f}s")

            # ── Stage 5: Tool validation + safety gates (with tool-not-found handling) ──
            result.pipeline_stage_reached = 5

            # ── Tool registry lookup ──────────────────────────────────────────────
            tool_class = get_tool(tool_name)
            if tool_class is None:
                tool_err = self.error_handler.tool_not_found(tool_name, list_tools(), attempt=0)
                logger.warning(f"Stage 5: {tool_err.technical_detail}")

                # Re-prompt once with correction injected
                correction_prompt = build_user_message(sanitised) + "\n\n" + tool_err.context_for_retry

                try:
                    tier1_raw_retry = await self.ollama.generate(
                        model="qwen2.5-coder:7b",
                        prompt=correction_prompt,
                        system=system_prompt,
                        keep_alive=0
                    )
                except Exception as retry_exc:
                    final_tool_err = self.error_handler.unknown_error(retry_exc, "stage_5_tool_retry")
                    result.final_output = final_tool_err.tagged_output(final_tool_err.user_message)
                    result.error = final_tool_err.technical_detail
                    mark_failed(db_task_id, error=final_tool_err.technical_detail[:300], db_path=DB_PATH)
                    return result

                tier1_parsed_retry = self._parse_tier1_response(tier1_raw_retry)
                if tier1_parsed_retry is None:
                    final_tool_err = self.error_handler.tool_not_found(tool_name, list_tools(), attempt=1)
                    result.final_output = final_tool_err.user_message
                    result.error = final_tool_err.technical_detail
                    mark_failed(db_task_id, error=final_tool_err.technical_detail[:300], db_path=DB_PATH)
                    return result

                tool_name = tier1_parsed_retry.get("tool", "")
                tool_params = tier1_parsed_retry.get("parameters", {})
                tier1_reasoning = tier1_parsed_retry.get("reasoning", "")
                tool_class = get_tool(tool_name)

                if tool_class is None:
                    final_tool_err = self.error_handler.tool_not_found(tool_name, list_tools(), attempt=1)
                    result.final_output = final_tool_err.user_message
                    result.error = final_tool_err.technical_detail
                    mark_failed(db_task_id, error=final_tool_err.technical_detail[:300], db_path=DB_PATH)
                    return result

            # ── Permission gate check ─────────────────────────────────────────────
            from tools.registry import PermissionGate
            gate = PermissionGate(self.mode)
            allowed, gate_reason = gate.check(tool_class)
            if not allowed:
                result.final_output = f"Action blocked in {self.mode.upper()} mode: {gate_reason}"
                result.success = False
                mark_failed(db_task_id, error=f"Permission gate: {gate_reason}", db_path=DB_PATH)
                return result

            # ── Pydantic schema validation ─────────────────────────────────────────
            try:
                tool_input = tool_class.Input(**tool_params)
            except Exception as validation_exc:
                validation_err = self.error_handler.unknown_error(
                    validation_exc, f"stage_5_validation_{tool_name}"
                )
                result.final_output = f"Invalid parameters for tool '{tool_name}': {str(validation_exc)[:200]}"
                result.error = validation_err.technical_detail
                mark_failed(db_task_id, error=validation_err.technical_detail[:300], db_path=DB_PATH)
                return result

            self.session_logger.log_tool_call(tool_name, tool_params, self.mode)
            log_tool_call(
                trace_id=trace_id,
                tool_name=tool_name,
                mode=self.mode,
                risk_score=getattr(tool_class, 'risk_score', 0.0),
                parameters_preview=json.dumps(tool_params)[:200]
            )
            tlog.debug(f"Stage 5 complete | tool={tool_name} validated")

            # ── Stage 6: Tool execution (with up-to-3 retries on exit_code != 0) ──
            result.pipeline_stage_reached = 6

            tool_instance = tool_class()
            tool_exec_retry_count = 0
            tool_result = None

            while tool_exec_retry_count <= 3:
                t_exec_start = time.monotonic()
                try:
                    current_tool_result = tool_instance.execute(tool_input)
                    t_exec_dur = time.monotonic() - t_exec_start
                except Exception as exec_exc:
                    t_exec_dur = time.monotonic() - t_exec_start
                    exec_err = self.error_handler.unknown_error(exec_exc, f"stage_6_{tool_name}_execute")
                    result.final_output = exec_err.tagged_output(exec_err.user_message)
                    result.error = exec_err.technical_detail
                    self.session_logger.log_tool_result(tool_name, False, 1, str(exec_exc)[:200], t_exec_dur)
                    mark_failed(db_task_id, error=exec_err.technical_detail[:300], db_path=DB_PATH)
                    return result

                self.session_logger.log_tool_result(
                    tool_name, current_tool_result.success,
                    current_tool_result.exit_code,
                    current_tool_result.output[:300],
                    t_exec_dur
                )
                log_tool_result(
                    trace_id=trace_id,
                    tool_name=tool_name,
                    success=current_tool_result.success,
                    exit_code=current_tool_result.exit_code,
                    duration=t_exec_dur,
                    output_preview=current_tool_result.output[:200] if current_tool_result.output else "",
                    retry_count=tool_exec_retry_count
                )

                if current_tool_result.success or current_tool_result.exit_code == 0:
                    # Success — exit the retry loop
                    tool_result = current_tool_result
                    logger.debug(
                        f"Stage 6: tool={tool_name} succeeded | "
                        f"exit={current_tool_result.exit_code} | attempt={tool_exec_retry_count + 1}"
                    )
                    break

                # Tool failed — decide whether to retry
                stderr = current_tool_result.error or current_tool_result.output or "Unknown error"
                exec_failure = self.error_handler.tool_execution_failure(
                    tool_name, current_tool_result.exit_code, stderr, retry_count=tool_exec_retry_count
                )

                logger.warning(
                    f"Stage 6: tool failure | tool={tool_name} | "
                    f"exit={current_tool_result.exit_code} | "
                    f"retry={tool_exec_retry_count}/3 | stderr={stderr[:80]!r}"
                )

                if exec_failure.is_final:
                    # Max retries exceeded
                    tool_result = current_tool_result
                    result.final_output = exec_failure.tagged_output(exec_failure.user_message)
                    result.error = exec_failure.technical_detail
                    result.tool_name = tool_name
                    result.tool_result = current_tool_result
                    mark_failed(db_task_id, error=exec_failure.technical_detail[:300], db_path=DB_PATH)
                    return result

                # Retry: ask T1 to fix the error
                tool_exec_retry_count += 1
                correction_sys = build_system_prompt(ctx)
                correction_prompt = (
                    build_user_message(sanitised) + "\n\n" +
                    exec_failure.context_for_retry
                )

                logger.info(f"Stage 6: retrying with error context (attempt {tool_exec_retry_count}/3)")

                try:
                    tier1_retry_raw = await self.ollama.generate(
                        model="qwen2.5-coder:7b",
                        prompt=correction_prompt,
                        system=correction_sys,
                        keep_alive=0
                    )
                except Exception as retry_gen_exc:
                    from models.ollama_client import OllamaTimeoutError
                    if isinstance(retry_gen_exc, OllamaTimeoutError):
                        timeout_err = self.error_handler.ollama_timeout("qwen2.5-coder:7b", 120, f"stage_6_retry_{tool_exec_retry_count}")
                        result.final_output = timeout_err.tagged_output(timeout_err.user_message)
                    else:
                        unk_err = self.error_handler.unknown_error(retry_gen_exc, f"stage_6_retry_{tool_exec_retry_count}")
                        result.final_output = unk_err.tagged_output(unk_err.user_message)
                    mark_failed(db_task_id, error=str(retry_gen_exc)[:300], db_path=DB_PATH)
                    return result

                retry_parsed = self._parse_tier1_response(tier1_retry_raw)
                if retry_parsed:
                    tool_name_retry = retry_parsed.get("tool", tool_name)
                    tool_params_retry = retry_parsed.get("parameters", tool_params)
                    retry_tool_class = get_tool(tool_name_retry)
                    if retry_tool_class:
                        try:
                            tool_input = retry_tool_class.Input(**tool_params_retry)
                            tool_instance = retry_tool_class()
                            tool_name = tool_name_retry
                        except Exception:
                            pass  # Keep existing tool_input if retry parse fails

            if tool_result is None:
                # Should never happen but defensive fallback
                result.final_output = "Tool execution produced no result. Please try again."
                mark_failed(db_task_id, error="tool_result is None after loop", db_path=DB_PATH)
                return result

            result.tool_name = tool_name
            result.tool_result = tool_result
            logger.debug(f"Stage 6 complete: tool={tool_name} | success={tool_result.success} | exit={tool_result.exit_code}")

            # ── Stage 7: Tier 2 verification (with timeout handling) ──────────────
            result.pipeline_stage_reached = 7

            try:
                verification = await self.verifier.verify(
                    task=sanitised,
                    tier1_reasoning=tier1_reasoning,
                    tool_name=tool_name,
                    tool_parameters=tool_params,
                    tool_result_output=tool_result.output[:600],
                    tool_exit_code=tool_result.exit_code
                )
            except Exception as t2_exc:
                from models.ollama_client import OllamaTimeoutError
                if isinstance(t2_exc, OllamaTimeoutError):
                    t2_err = self.error_handler.ollama_timeout("mistral:7b-instruct-q4_K_M", 120, "stage_7")
                else:
                    t2_err = self.error_handler.unknown_error(t2_exc, "stage_7_tier2")
                logger.warning(f"Stage 7: Tier 2 failed — {t2_err.technical_detail}. Proceeding with T1 output.")
                # Fall through with a synthetic "agree" verification so pipeline continues
                from core.verifier import VerificationResult
                verification = VerificationResult(
                    agree=True,
                    confidence=0.5,
                    critical_issues=[f"T2 unavailable: {t2_err.failure_mode.value}"],
                    risk_score=0.3,
                    reasoning="Tier 2 verification unavailable — proceeding with reduced confidence."
                )

            self.session_logger.log_tier2_verification(
                "mistral:7b-instruct-q4_K_M",
                verification.agree, verification.confidence,
                verification.critical_issues, verification.risk_score,
                verification.latency_seconds if hasattr(verification, 'latency_seconds') else 0.0
            )
            log_tier2_call(
                trace_id=trace_id,
                model="mistral:7b-instruct-q4_K_M",
                latency=verification.latency_seconds if hasattr(verification, 'latency_seconds') else 0.0,
                agree=verification.agree,
                confidence=verification.confidence,
                risk_score=verification.risk_score,
                escalated=verification.should_escalate
            )
            tlog.debug(f"Stage 7 complete | {verification.summary()}")

            # ── Stage 8: Disagreement router ──────────────────────────
            result.pipeline_stage_reached = 8
            routing = self.router.route(verification, tool_name, self.mode)
            logger.info(f"Stage 8 complete: {routing.summary()}")

            # ── Stage 9: Tier 3 arbitration (with API failure handling) ──────────
            result.pipeline_stage_reached = 9

            tier3_decision_text = ""

            if routing.decision == RoutingDecision.BLOCK:
                result.final_output = (
                    f"⚠ This action requires your explicit confirmation.\n"
                    f"Tool: {tool_name}\n"
                    f"Reason: {routing.reason}\n"
                    f"Please confirm you want to proceed."
                )
                result.success = False
                mark_failed(db_task_id, error=f"Blocked: {routing.reason}", db_path=DB_PATH)
                return result

            elif routing.decision == RoutingDecision.ESCALATE and routing.tier3_needed:
                try:
                    tier3_response = await self.claude.arbitrate(
                        task=sanitised,
                        tier1_output=str(tier1_parsed),
                        tier2_issues=verification.critical_issues,
                        tool_result=tool_result.output[:400],
                        escalation_reason=routing.reason
                    )
                    result.tier3_was_called = True

                    if not tier3_response.success:
                        # Tier 3 API failed — use T1 output with UNVERIFIED tag
                        t3_err = self.error_handler.tier3_api_failure(
                            "APIError",
                            tier3_response.error or "unknown error",
                            tier1_parsed.get("explanation", "Action proceeding with T1 output.")
                        )
                        logger.warning(f"Stage 9: {t3_err.technical_detail}")
                        tier3_decision_text = f"[{t3_err.tag}] {t3_err.user_message}"
                    else:
                        self.session_logger.log_tier3_arbitration(
                            tier3_response.content[:200],
                            tier3_response.input_tokens,
                            tier3_response.output_tokens,
                            tier3_response.cost_usd
                        )
                        tier3_decision_text = tier3_response.content
                        log_tier3_call(
                            trace_id=trace_id,
                            latency=tier3_response.latency_seconds,
                            input_tokens=tier3_response.input_tokens,
                            output_tokens=tier3_response.output_tokens,
                            cost_usd=tier3_response.cost_usd,
                            success=True,
                            escalation_reason=routing.reason
                        )
                        logger.info(f"Stage 9 complete: Tier 3 arbitrated | cost=${tier3_response.cost_usd:.4f}")

                except Exception as t3_exc:
                    t3_err = self.error_handler.tier3_api_failure(
                        type(t3_exc).__name__,
                        str(t3_exc)[:200],
                        tier1_parsed.get("explanation", "Action proceeding.")
                    )
                    logger.warning(f"Stage 9: Tier 3 exception — {t3_err.technical_detail}")
                    tier3_decision_text = t3_err.tagged_output(t3_err.user_message)
                    result.tier3_was_called = True

            # ── Stage 10: Memory update ───────────────────────────────
            result.pipeline_stage_reached = 10
            if tool_result.exit_code == 0 and tool_result.success:
                conversation_for_extraction = [
                    {"role": "user", "content": sanitised},
                    {"role": "assistant", "content": tier1_raw[:300]}
                ]
                tool_results_for_extraction = [
                    {
                        "tool": tool_name,
                        "exit_code": tool_result.exit_code,
                        "success": tool_result.success
                    }
                ]

                facts = await extract_memories(
                    task_description=sanitised,
                    conversation_history=conversation_for_extraction,
                    tool_results=tool_results_for_extraction,
                    ollama_client=self.ollama
                )

                written = confirm_and_write_facts(
                    facts, tool_name=tool_name,
                    exit_code=tool_result.exit_code,
                    project=self.project
                )
                log_memory_event(
                    trace_id=trace_id,
                    event_type="write",
                    facts_count=written,
                    project=self.project,
                    detail=f"tool={tool_name} exit_code={tool_result.exit_code}"
                )

                if written > 0:
                    self.session_logger.log_memory_update(written, self.project)
                tlog.debug(f"Stage 10 complete | {written} facts written to memory")

            # ── Stage 11: Task queue update ───────────────────────────
            result.pipeline_stage_reached = 11
            # KAIROS handles the SQLite task queue — orchestrator just logs completion
            logger.debug(f"Stage 11 complete: task {task.task_id} processed")

            # ── Stage 12: Build final output ──────────────────────────
            result.pipeline_stage_reached = 12
            result.success = tool_result.success

            explanation = tier1_parsed.get("explanation", "Task completed.")

            if tool_result.success:
                output_preview = tool_result.output[:400] if tool_result.output else ""
                result.final_output = (
                    f"{explanation}\n\n{output_preview}" if output_preview else explanation
                )
            else:
                error_msg = tool_result.error or "Unknown error"
                result.final_output = (
                    f"The action did not complete successfully.\n"
                    f"Tool: {tool_name}\n"
                    f"Error: {error_msg[:300]}"
                )

            if tier3_decision_text:
                result.final_output += f"\n\n[Tier 3 review]: {tier3_decision_text[:200]}"

            total_latency = time.monotonic() - start_time
            log_pipeline_complete(
                trace_id=trace_id,
                success=result.success,
                stage_reached=12,
                total_latency=total_latency,
                tool_name=result.tool_name,
                tier3_called=result.tier3_was_called,
                cost_usd=self.claude.get_cost_summary().get("total_spent", 0.0)
            )
            tlog.info(f"Pipeline complete | success={result.success} | latency={total_latency:.2f}s")
            result.total_latency_seconds = total_latency
            # Update task queue status
            if result.success:
                mark_completed(db_task_id, db_path=DB_PATH)
            else:
                mark_failed(db_task_id, error=result.error or result.final_output[:200], db_path=DB_PATH)

            return result

        except Exception as e:
            result.total_latency_seconds = time.monotonic() - start_time
            result.error = str(e)
            result.final_output = (
                f"An unexpected error occurred at stage "
                f"{result.pipeline_stage_reached}: {str(e)[:200]}"
            )
            log_pipeline_complete(
                trace_id=trace_id,
                success=False,
                stage_reached=result.pipeline_stage_reached,
                total_latency=time.monotonic() - start_time,
                tool_name=None,
                tier3_called=False,
                cost_usd=0.0
            )
            logger.error(
                f"Orchestrator error at stage {result.pipeline_stage_reached}: "
                f"{type(e).__name__}: {e}"
            )
            return result

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    def _sanitise_input(self, user_input: str) -> str:
        """Strip HTML/XML tags, replace backticks, cap length."""
        sanitised = user_input
        sanitised = re.sub(r'<[^>]+>', '', sanitised)   # Remove HTML/XML tags
        sanitised = sanitised.replace('`', "'")          # Replace backticks
        sanitised = sanitised.strip()
        if not sanitised:
            sanitised = "Please describe what you want me to do."
        return sanitised[:2000]  # Hard cap on input length

    def _parse_tier1_response(self, response: str) -> Optional[dict]:
        """Parse Tier 1 response using the hardened ResponseParser."""
        from core.response_parser import ResponseParser
        parser = ResponseParser()
        result = parser.parse(response)
        
        if hasattr(result, 'to_dict'):  # ParseSuccess
            if result.method_used != "direct_parse":
                logger.info(f"ResponseParser: used fallback strategy '{result.method_used}'")
            return result.to_dict()
        else:  # ParseFailure
            logger.warning(
                f"ResponseParser: all strategies failed | "
                f"reason={result.failure_reason} | "
                f"plain_text={result.is_plain_text} | "
                f"has_fragment={result.has_json_fragment}"
            )
            return None

    def set_mode(self, mode: str) -> None:
        """Change the operating mode. Raises ValueError for invalid modes."""
        if mode not in ("safe", "plan", "auto"):
            raise ValueError(f"Invalid mode '{mode}'. Must be: safe, plan, auto")
        self.mode = mode
        logger.info(f"Orchestrator mode changed to: {mode}")
