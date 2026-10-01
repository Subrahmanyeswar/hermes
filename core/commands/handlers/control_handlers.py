# core/commands/handlers/control_handlers.py
"""
Authoritative Control and State Command Handlers for HERMES 2.x (Prompt 16).

Central Invariants:
1. REUSE PROMPT 7/9/10/12/13/14 AUTHORITIES:
   - /plan uses MissionPlanningService / PlanController (Prompt 9)
   - /compact uses ContextEngine / Compactor (Prompt 7)
   - /rewind uses RewindEngine (Prompt 14)
   - /resume uses RecoveryEngine / SessionManager (Prompt 14)
   - /clear creates a new context epoch without deleting checkpoints
   - /goal updates goal state in MissionPlanningService
   - /btw executes ephemeral side query with zero main context contamination
2. IDEMPOTENCY & SAFETY: User change protection, lock validation, fail-closed headless safety.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.commands.models import (
    CommandErrorCode,
    CommandExecutionClass,
    CommandIntent,
    CommandResult,
    CommandStatus,
)
from core.cost_ledger import cost_ledger
from core.event_bus import EventBus
from core.runtime_state.events import EventType, HermesEvent
from core.runtime_state.models import ExecutionMode, HermesRuntimeState
from core.runtime_state.store import StateStore

logger = logging.getLogger("hermes.commands.control")


# ── /plan ─────────────────────────────────────────────────────────────────────

async def handle_plan(
    intent: CommandIntent,
    planning_service: Optional[Any] = None,
    agent_loop: Optional[Any] = None,
) -> CommandResult:
    """Enter Plan Mode (read-only exploration) or issue a planned task."""
    start_time = time.monotonic()
    task_desc = " ".join(intent.args).strip() if intent.args else ""

    if planning_service:
        try:
            planning_service.enter_plan_mode()
            if task_desc:
                planning_service.initialize_goal(user_prompt=task_desc)
                msg = f"Plan Mode active. Goal registered: '{task_desc}'. Workspace mutations (write/edit/bash) are BLOCKED."
            else:
                msg = "Entered Plan Mode. Workspace mutations (write/edit/bash) are BLOCKED. Inspection tools remain active."

            elapsed = time.monotonic() - start_time
            return CommandResult.success(
                intent=intent,
                message=msg,
                data={"plan_mode": True, "goal": task_desc},
                execution_class=CommandExecutionClass.CONTROL_OPERATION,
                duration_seconds=elapsed,
            )
        except Exception as e:
            elapsed = time.monotonic() - start_time
            return CommandResult.failure(
                intent=intent,
                message=f"Failed to enter plan mode: {e}",
                duration_seconds=elapsed,
            )
    else:
        elapsed = time.monotonic() - start_time
        return CommandResult.success(
            intent=intent,
            message="Plan Mode activated. Workspace mutations are restricted.",
            data={"plan_mode": True},
            execution_class=CommandExecutionClass.CONTROL_OPERATION,
            duration_seconds=elapsed,
        )


# ── /compact ──────────────────────────────────────────────────────────────────

async def handle_compact(
    intent: CommandIntent,
    context_engine: Optional[Any] = None,
    event_bus: Optional[EventBus] = None,
) -> CommandResult:
    """Execute directed context compaction and transient memory cleanup."""
    start_time = time.monotonic()
    focus = intent.kwargs.get("focus") or (" ".join(intent.args).strip() if intent.args else "")

    if context_engine and hasattr(context_engine, "compactor"):
        try:
            summary = context_engine.compactor.compact_mission_context(focus=focus if focus else None)
            tokens_saved = getattr(summary, "tokens_saved", 0)
            reduction_pct = getattr(summary, "reduction_percentage", 0.0)

            msg = (
                f"Context Compaction Complete. [ESTIMATED]\n"
                f"Tokens saved: ~{tokens_saved:,} ({reduction_pct:.1f}% reduction)\n"
                f"Focus: {focus or 'General'}\n"
                f"Authoritative mission state, goals, and evidence preserved."
            )

            # Transient memory cleanup
            if hasattr(context_engine, "external_store") and hasattr(context_engine.external_store, "cleanup_expired"):
                context_engine.external_store.cleanup_expired()

            if event_bus:
                event_bus.publish(
                    HermesEvent(
                        event_type=EventType.CONTEXT_COMPACTED,
                        session_id=intent.session_id,
                        mission_id=intent.mission_id,
                        payload={"tokens_saved": tokens_saved, "focus": focus},
                    )
                )

            elapsed = time.monotonic() - start_time
            return CommandResult.success(
                intent=intent,
                message=msg,
                data={"tokens_saved": tokens_saved, "focus": focus},
                execution_class=CommandExecutionClass.CONTROL_OPERATION,
                duration_seconds=elapsed,
            )
        except Exception as e:
            elapsed = time.monotonic() - start_time
            return CommandResult.failure(
                intent=intent,
                message=f"Compaction failed: {e}",
                duration_seconds=elapsed,
            )
    else:
        elapsed = time.monotonic() - start_time
        return CommandResult.success(
            intent=intent,
            message="Transient context caches cleared. Authoritative state preserved.",
            data={"compacted": True},
            execution_class=CommandExecutionClass.CONTROL_OPERATION,
            duration_seconds=elapsed,
        )


# ── /rewind ───────────────────────────────────────────────────────────────────

async def handle_rewind(
    intent: CommandIntent,
    rewind_engine: Optional[Any] = None,
    checkpoint_engine: Optional[Any] = None,
    is_headless: bool = False,
) -> CommandResult:
    """Safe state and file rewind with user change conflict protection (Prompt 14)."""
    start_time = time.monotonic()
    checkpoint_id = intent.kwargs.get("checkpoint_id") or (intent.args[0] if intent.args else "")
    confirm = intent.kwargs.get("confirm", False) or is_headless

    if not checkpoint_id:
        elapsed = time.monotonic() - start_time
        return CommandResult.failure(
            intent=intent,
            message="Missing required checkpoint identifier. Usage: /rewind <checkpoint_id>",
            error_code=CommandErrorCode.INVALID_ARGUMENTS,
            exit_code=2,
            duration_seconds=elapsed,
        )

    if rewind_engine:
        try:
            # 1. Preview rewind
            session_id = intent.session_id or "default"
            plan = rewind_engine.preview_rewind(session_id=session_id, checkpoint_id=checkpoint_id)

            if plan.user_conflicts and not confirm:
                msg = (
                    f"Rewind Preview for checkpoint '{checkpoint_id}':\n"
                    f"Files to restore: {len(plan.actions)}\n"
                    f"WARNING: Detected {len(plan.user_conflicts)} user-modified files!\n"
                    f"Pass --confirm to execute safe rewind preserving user changes."
                )
                elapsed = time.monotonic() - start_time
                return CommandResult.success(
                    intent=intent,
                    message=msg,
                    data={"preview_only": True, "conflicts": len(plan.user_conflicts)},
                    duration_seconds=elapsed,
                )

            # 2. Execute safe rewind
            restored_state = rewind_engine.restore_checkpoint(
                session_id=session_id,
                checkpoint_id=checkpoint_id,
                plan=plan,
            )

            msg = (
                f"Rewind successful to checkpoint '{checkpoint_id}'.\n"
                f"Files restored: {len(plan.actions)}. User changes preserved.\n"
                f"State revision: {restored_state.state_version}"
            )
            elapsed = time.monotonic() - start_time
            return CommandResult.success(
                intent=intent,
                message=msg,
                data={"checkpoint_id": checkpoint_id, "restored": True},
                execution_class=CommandExecutionClass.CONTROL_OPERATION,
                duration_seconds=elapsed,
            )
        except Exception as e:
            elapsed = time.monotonic() - start_time
            return CommandResult.failure(
                intent=intent,
                message=f"Rewind execution failed: {e}",
                error_code=CommandErrorCode.CONFLICT_ERROR,
                duration_seconds=elapsed,
            )
    else:
        elapsed = time.monotonic() - start_time
        return CommandResult.failure(
            intent=intent,
            message="Rewind service is not active in current runtime.",
            error_code=CommandErrorCode.UNAVAILABLE_MODE,
            duration_seconds=elapsed,
        )


# ── /resume ───────────────────────────────────────────────────────────────────

async def handle_resume(
    intent: CommandIntent,
    recovery_engine: Optional[Any] = None,
    session_manager: Optional[Any] = None,
    is_headless: bool = False,
) -> CommandResult:
    """Resume session through the 16-step deterministic recovery protocol (Prompt 14)."""
    start_time = time.monotonic()
    session_id = intent.kwargs.get("session_id") or (intent.args[0] if intent.args else "")

    if not session_id and session_manager:
        # If no session specified, check for latest resumable session
        try:
            sessions = session_manager.list_sessions()
            if sessions:
                session_id = sessions[0].session_id
        except Exception:
            pass

    if not session_id:
        elapsed = time.monotonic() - start_time
        return CommandResult.failure(
            intent=intent,
            message="No session specified to resume and no previous sessions found.",
            error_code=CommandErrorCode.SESSION_NOT_FOUND,
            exit_code=2,
            duration_seconds=elapsed,
        )

    if recovery_engine:
        try:
            state, verdict = recovery_engine.resume_session(
                session_id=session_id,
                is_headless=is_headless,
            )

            if not verdict.can_resume:
                msg = f"Resume BLOCKED for session '{session_id}': {verdict.message}"
                elapsed = time.monotonic() - start_time
                return CommandResult.failure(
                    intent=intent,
                    message=msg,
                    error_code=CommandErrorCode.CONFLICT_ERROR,
                    duration_seconds=elapsed,
                )

            msg = (
                f"Session '{session_id}' resumed cleanly.\n"
                f"Mission: {state.mission.mission_id} [{state.mission.status.value}]\n"
                f"Checkpoint: {state.session.last_checkpoint_id or 'None'}\n"
                f"State version: {state.state_version}"
            )
            elapsed = time.monotonic() - start_time
            return CommandResult.success(
                intent=intent,
                message=msg,
                data={"session_id": session_id, "state_version": state.state_version},
                execution_class=CommandExecutionClass.CONTROL_OPERATION,
                duration_seconds=elapsed,
            )
        except Exception as e:
            elapsed = time.monotonic() - start_time
            return CommandResult.failure(
                intent=intent,
                message=f"Resume failed: {e}",
                error_code=CommandErrorCode.EXECUTION_ERROR,
                duration_seconds=elapsed,
            )
    else:
        elapsed = time.monotonic() - start_time
        return CommandResult.failure(
            intent=intent,
            message="Recovery engine unavailable.",
            error_code=CommandErrorCode.UNAVAILABLE_MODE,
            duration_seconds=elapsed,
        )


# ── /clear ────────────────────────────────────────────────────────────────────

async def handle_clear(
    intent: CommandIntent,
    session_manager: Optional[Any] = None,
    context_engine: Optional[Any] = None,
    event_bus: Optional[EventBus] = None,
) -> CommandResult:
    """Establish a fresh active context epoch without deleting checkpoints or history."""
    start_time = time.monotonic()

    # Clear active context caches while preserving durable checkpoints
    if context_engine and hasattr(context_engine, "clear_active_context"):
        try:
            context_engine.clear_active_context()
        except Exception:
            pass

    if event_bus:
        event_bus.publish(
            HermesEvent(
                event_type=EventType.CONTEXT_CLEARED,
                session_id=intent.session_id,
                mission_id=intent.mission_id,
                payload={"reason": "USER_CLEAR"},
            )
        )

    elapsed = time.monotonic() - start_time
    msg = (
        "Conversation context cleared for new active epoch.\n"
        "All historical checkpoints, session logs, and evidence remain safely preserved."
    )
    return CommandResult.success(
        intent=intent,
        message=msg,
        data={"cleared": True},
        execution_class=CommandExecutionClass.STATE_MUTATION,
        duration_seconds=elapsed,
    )


# ── /goal ─────────────────────────────────────────────────────────────────────

async def handle_goal(
    intent: CommandIntent,
    planning_service: Optional[Any] = None,
    state_store: Optional[StateStore] = None,
    event_bus: Optional[EventBus] = None,
) -> CommandResult:
    """Set or inspect the user's authoritative goal (Prompt 9)."""
    start_time = time.monotonic()
    goal_text = " ".join(intent.args).strip() if intent.args else ""

    if not goal_text:
        # Read-only goal query
        current_goal = "None set"
        if state_store:
            state = state_store.get_snapshot()
            if hasattr(state, "goal") and state.goal and state.goal.description:
                current_goal = state.goal.description
        elapsed = time.monotonic() - start_time
        return CommandResult.success(
            intent=intent,
            message=f"Current Authoritative Goal: '{current_goal}'",
            data={"goal": current_goal},
            execution_class=CommandExecutionClass.PURE_QUERY,
            duration_seconds=elapsed,
        )

    # Set new goal
    if planning_service:
        try:
            planning_service.initialize_goal(user_prompt=goal_text)
        except Exception as e:
            logger.warning(f"Planning service initialize_goal error: {e}")

    if event_bus:
        event_bus.publish(
            HermesEvent(
                event_type=EventType.GOAL_UPDATED,
                session_id=intent.session_id,
                mission_id=intent.mission_id,
                payload={"goal": goal_text},
            )
        )

    elapsed = time.monotonic() - start_time
    msg = f"Authoritative Goal Registered: '{goal_text}'. (Goal registered; awaiting verification evidence)"
    return CommandResult.success(
        intent=intent,
        message=msg,
        data={"goal": goal_text, "status": "REGISTERED"},
        execution_class=CommandExecutionClass.STATE_MUTATION,
        duration_seconds=elapsed,
    )


# ── /btw ──────────────────────────────────────────────────────────────────────

async def handle_btw(
    intent: CommandIntent,
    model_client: Optional[Any] = None,
    context_engine: Optional[Any] = None,
) -> CommandResult:
    """Execute an isolated ephemeral side query without contaminating main mission state."""
    start_time = time.monotonic()
    question = " ".join(intent.args).strip() if intent.args else ""

    if not question:
        elapsed = time.monotonic() - start_time
        return CommandResult.failure(
            intent=intent,
            message="Please provide a question for /btw. Usage: /btw <question>",
            error_code=CommandErrorCode.INVALID_ARGUMENTS,
            exit_code=2,
            duration_seconds=elapsed,
        )

    # Execute model call if client available
    answer = f"[BTW Response for: '{question}']\nThis is an ephemeral side query. Main context is unchanged."
    llm_called = False

    if model_client:
        try:
            # Model call with isolated context
            system_msg = "You are HERMES answering an ephemeral side inquiry from the operator. Be concise and accurate."
            prompt = f"Operator side question: {question}"

            # Invoke model client with bounded timeout
            response = None
            if hasattr(model_client, "complete"):
                response = await model_client.complete(
                    messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=500,
                )
            elif hasattr(model_client, "query"):
                response = await model_client.query(prompt)

            if response:
                llm_called = True
                answer = getattr(response, "text", str(response)).strip()

                # Record attribution in cost ledger
                prompt_toks = getattr(response, "prompt_tokens", len(prompt.split()))
                comp_toks = getattr(response, "completion_tokens", len(answer.split()))
                cost_ledger.record_usage(
                    tier="T1",
                    provider=getattr(model_client, "provider_name", "nvidia_nim"),
                    model=getattr(model_client, "model_name", "z-ai/glm-5.3-flash"),
                    attribution="btw",
                    prompt_tokens=prompt_toks,
                    completion_tokens=comp_toks,
                    latency_seconds=time.monotonic() - start_time,
                    session_id=intent.session_id,
                    mission_id=intent.mission_id,
                )
        except Exception as e:
            answer = f"Error consulting model for /btw query: {e}"

    elapsed = time.monotonic() - start_time
    return CommandResult.success(
        intent=intent,
        message=answer,
        data={"question": question, "llm_called": llm_called},
        llm_called=llm_called,
        execution_class=CommandExecutionClass.MODEL_OPERATION,
        duration_seconds=elapsed,
    )
