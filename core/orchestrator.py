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
        result = OrchestratorResult(success=False, final_output="")

        try:
            # ── Stage 1: Sanitise input ───────────────────────────────
            result.pipeline_stage_reached = 1
            sanitised = self._sanitise_input(user_request)
            self.session_logger.log_user_input(sanitised)
            logger.debug(f"Stage 1 complete: input sanitised ({len(sanitised)} chars)")

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

            # ── Stage 3: Skill + Memory injection ─────────────────────
            result.pipeline_stage_reached = 3
            skill_ids = self.classifier.classify(sanitised)
            skill_content, loaded_skill_ids = self.classifier.build_skill_prompt_section(skill_ids)
            result.skill_ids_used = loaded_skill_ids
            memory_context = read_context_for_prompt(project=self.project)
            active_skill_name = loaded_skill_ids[0] if loaded_skill_ids else "none"
            logger.debug(
                f"Stage 3 complete: skills={loaded_skill_ids} | "
                f"memory_lines={memory_context.count(chr(10))}"
            )

            # ── Stage 4: Tier 1 generation ────────────────────────────
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
            user_message = build_user_message(sanitised)

            t1_start = time.monotonic()
            tier1_raw = await self.ollama.generate(
                model="qwen2.5-coder:7b",
                prompt=user_message,
                system=system_prompt,
                keep_alive=0
            )
            t1_latency = time.monotonic() - t1_start

            tier1_parsed = self._parse_tier1_response(tier1_raw)
            if tier1_parsed is None:
                # Re-prompt once with stronger instruction
                logger.warning("Stage 4: Tier 1 produced invalid JSON — re-prompting once")
                from core.prompt_builder import build_system_prompt_v2
                retry_system = build_system_prompt_v2(ctx)
                logger.info("Stage 4 retry: switching to v2 prompt with two-shot examples")
                tier1_raw = await self.ollama.generate(
                    model="qwen2.5-coder:7b",
                    prompt=user_message,
                    system=retry_system,
                    keep_alive=0
                )
                tier1_parsed = self._parse_tier1_response(tier1_raw)
                if tier1_parsed is None:
                    result.error = "Tier 1 failed to produce valid JSON after 2 attempts"
                    result.final_output = (
                        "I was unable to understand how to complete this task. "
                        "Please try rephrasing your request."
                    )
                    result.pipeline_stage_reached = 4
                    mark_failed(db_task_id, error=result.error or "Early exit at stage 4", db_path=DB_PATH)
                    return result

            tool_name = tier1_parsed.get("tool", "")
            # Update tool name in task record now that we know it
            from kairos.db import execute_write
            execute_write(
                "UPDATE tasks SET tool_name=? WHERE id=?",
                (tool_name, db_task_id)
            )
            tool_params = tier1_parsed.get("parameters", {})
            tier1_reasoning = tier1_parsed.get("reasoning", "")

            self.session_logger.log_tier1_response(
                "qwen2.5-coder:7b", tier1_raw[:500], t1_latency, tool_name
            )
            logger.debug(f"Stage 4 complete: tool={tool_name} | latency={t1_latency:.2f}s")

            # ── Stage 5: Tool validation + safety gates ───────────────
            result.pipeline_stage_reached = 5
            tool_class = get_tool(tool_name)
            if tool_class is None:
                result.error = f"Unknown tool: {tool_name}"
                result.final_output = (
                    f"I tried to use a tool called '{tool_name}' which doesn't exist. "
                    f"Available tools: {', '.join(list_tools()[:5])}"
                )
                mark_failed(db_task_id, error=result.error or "Early exit at stage 5", db_path=DB_PATH)
                return result

            gate = PermissionGate(self.mode)
            allowed, gate_reason = gate.check(tool_class)
            if not allowed:
                result.final_output = f"Action blocked in {self.mode.upper()} mode: {gate_reason}"
                result.success = False
                mark_failed(db_task_id, error=result.error or "Early exit at stage 5", db_path=DB_PATH)
                return result

            try:
                tool_input = tool_class.Input(**tool_params)
            except Exception as e:
                result.error = f"Tool parameter validation failed: {e}"
                result.final_output = f"Invalid parameters for tool '{tool_name}': {e}"
                mark_failed(db_task_id, error=result.error or "Early exit at stage 5", db_path=DB_PATH)
                return result

            self.session_logger.log_tool_call(tool_name, tool_params, self.mode)
            logger.debug(f"Stage 5 complete: tool={tool_name} validated")

            # ── Stage 6: Tool execution ───────────────────────────────
            result.pipeline_stage_reached = 6
            tool_instance = tool_class()
            t_exec_start = time.monotonic()
            tool_result: ToolResult = tool_instance.execute(tool_input)
            t_exec_dur = time.monotonic() - t_exec_start

            result.tool_name = tool_name
            result.tool_result = tool_result

            self.session_logger.log_tool_result(
                tool_name, tool_result.success, tool_result.exit_code,
                tool_result.output[:300], t_exec_dur
            )
            logger.debug(
                f"Stage 6 complete: tool={tool_name} | "
                f"success={tool_result.success} | exit={tool_result.exit_code}"
            )

            # ── Stage 7: Tier 2 verification ──────────────────────────
            result.pipeline_stage_reached = 7
            verification = await self.verifier.verify(
                task=sanitised,
                tier1_reasoning=tier1_reasoning,
                tool_name=tool_name,
                tool_parameters=tool_params,
                tool_result_output=tool_result.output[:600],
                tool_exit_code=tool_result.exit_code
            )
            self.session_logger.log_tier2_verification(
                "mistral:7b-instruct-q4_K_M",
                verification.agree, verification.confidence,
                verification.critical_issues, verification.risk_score,
                verification.latency_seconds
            )
            logger.debug(f"Stage 7 complete: {verification.summary()}")

            # ── Stage 8: Disagreement router ──────────────────────────
            result.pipeline_stage_reached = 8
            routing = self.router.route(verification, tool_name, self.mode)
            logger.info(f"Stage 8 complete: {routing.summary()}")

            # ── Stage 9: Tier 3 arbitration (conditional) ─────────────
            result.pipeline_stage_reached = 9
            final_decision_text = ""

            if routing.decision == RoutingDecision.BLOCK:
                result.final_output = (
                    f"[WARNING] This action requires your explicit confirmation.\n"
                    f"Tool: {tool_name}\n"
                    f"Reason: {routing.reason}\n"
                    f"Please confirm you want to proceed."
                )
                result.success = False
                mark_failed(db_task_id, error=result.error or "Early exit at stage 8", db_path=DB_PATH)
                return result

            elif routing.decision == RoutingDecision.ESCALATE and routing.tier3_needed:
                tier3_response = await self.claude.arbitrate(
                    task=sanitised,
                    tier1_output=str(tier1_parsed),
                    tier2_issues=verification.critical_issues,
                    tool_result=tool_result.output[:400],
                    escalation_reason=routing.reason
                )
                result.tier3_was_called = True
                self.session_logger.log_tier3_arbitration(
                    tier3_response.content[:200],
                    tier3_response.input_tokens,
                    tier3_response.output_tokens,
                    tier3_response.cost_usd
                )
                final_decision_text = tier3_response.content
                logger.info(
                    f"Stage 9 complete: Tier 3 arbitrated | "
                    f"cost=${tier3_response.cost_usd:.4f}"
                )

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

                if written > 0:
                    self.session_logger.log_memory_update(written, self.project)
                logger.debug(f"Stage 10 complete: {written} facts written to memory")

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

            if final_decision_text:
                result.final_output += f"\n\n[Tier 3 review]: {final_decision_text[:200]}"

            result.total_latency_seconds = time.monotonic() - start_time
            logger.info(
                f"Pipeline complete | success={result.success} | "
                f"stages=12 | tier3={result.tier3_was_called} | "
                f"latency={result.total_latency_seconds:.2f}s"
            )
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
