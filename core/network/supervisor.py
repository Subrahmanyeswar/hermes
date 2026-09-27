# core/network/supervisor.py
"""
NetworkSupervisor for HERMES 2.x
Authoritative coordinator of network requests, streaming watchdogs,
provider health, retry policies, fallbacks, and zero-silent-hang enforcement.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set
from loguru import logger

from models.provider import NormalizedModelResponse
from core.runtime_state.events import EventSeverity, EventType, HermesEvent
from core.network.adapters import (
    BaseProviderAdapter,
    classify_httpx_exception,
)
from core.network.health import ProviderHealthState
from core.network.models import (
    DeadlineBudget,
    FailureClassification,
    LogicalRequest,
    RequestAttempt,
    RequestPhase,
    StreamDelta,
    is_retryable_failure,
)
from core.network.retry import RetryPolicy
from core.network.watchdog import StreamWatchdog


class NetworkSupervisor:
    """
    Supervises all model generation requests.
    Guarantees no silent hangs, bounded timeouts, fresh-connection retries,
    stream stall recovery, non-streaming fallback, and tool replay safety.
    """

    def __init__(
        self,
        event_bus: Optional[Any] = None,
        retry_policy: Optional[RetryPolicy] = None,
        default_connect_timeout: float = 10.0,
        default_first_delta_timeout: float = 15.0,
        default_idle_timeout: float = 15.0,
        default_attempt_timeout: float = 45.0,
        default_logical_timeout: float = 90.0,
    ) -> None:
        self.event_bus = event_bus
        self.retry_policy = retry_policy or RetryPolicy()
        self.default_connect_timeout = default_connect_timeout
        self.default_first_delta_timeout = default_first_delta_timeout
        self.default_idle_timeout = default_idle_timeout
        self.default_attempt_timeout = default_attempt_timeout
        self.default_logical_timeout = default_logical_timeout

        self._health_states: Dict[str, ProviderHealthState] = {}
        self._executed_tool_ids: Set[str] = set()
        self._executed_action_keys: Set[str] = set()
        self._active_requests: Dict[str, LogicalRequest] = {}

    def get_provider_health(self, provider_name: str) -> ProviderHealthState:
        """Get or create the health tracker for a provider."""
        if provider_name not in self._health_states:
            self._health_states[provider_name] = ProviderHealthState(provider_name=provider_name)
        return self._health_states[provider_name]

    def register_executed_tool_call(
        self,
        tool_call_id: str,
        turn_id: Optional[str] = None,
        action_key: Optional[str] = None,
    ) -> None:
        """Register that a tool call or semantic action was already executed to prevent duplicate replay."""
        if tool_call_id:
            key = f"{turn_id}:{tool_call_id}" if turn_id else tool_call_id
            self._executed_tool_ids.add(key)
        if action_key:
            act_key = f"{turn_id}:{action_key}" if turn_id else action_key
            self._executed_action_keys.add(act_key)

    def is_tool_call_executed(
        self,
        tool_call_id: str,
        turn_id: Optional[str] = None,
        action_key: Optional[str] = None,
    ) -> bool:
        """Check if a tool call or semantic action was already executed in this turn/session."""
        if tool_call_id:
            if turn_id and f"{turn_id}:{tool_call_id}" in self._executed_tool_ids:
                return True
            if tool_call_id in self._executed_tool_ids:
                return True
        if action_key:
            if turn_id and f"{turn_id}:{action_key}" in self._executed_action_keys:
                return True
            if action_key in self._executed_action_keys:
                return True
        return False

    def _publish_event(
        self,
        event_type: EventType,
        mission_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        severity: EventSeverity = EventSeverity.INFO,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self.event_bus is None:
            return
        payload = payload or {}
        event = HermesEvent(
            event_type=event_type,
            mission_id=mission_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            severity=severity,
            source="network_supervisor",
            payload=payload,
        )
        try:
            self.event_bus.publish(event)
        except Exception as exc:
            logger.warning(f"NetworkSupervisor: Failed to publish event {event_type}: {exc}")

    async def execute_request(
        self,
        adapter: BaseProviderAdapter,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        turn_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        turn_deadline: Optional[float] = None,
        mission_deadline: Optional[float] = None,
        stream: bool = True,
        on_delta_callback: Optional[Callable[[StreamDelta], Any]] = None,
        cancel_event: Optional[asyncio.Event] = None,
        **kwargs: Any,
    ) -> NormalizedModelResponse:
        """
        Execute a model generation request with end-to-end resilience.
        """
        provider_name = adapter.provider_name
        health = self.get_provider_health(provider_name)

        # 1. Initialize budget
        budget = DeadlineBudget(
            connect_timeout=self.default_connect_timeout,
            first_delta_timeout=self.default_first_delta_timeout,
            idle_timeout=self.default_idle_timeout,
            attempt_timeout=self.default_attempt_timeout,
            logical_request_timeout=self.default_logical_timeout,
            turn_deadline_monotonic=turn_deadline,
            mission_deadline_monotonic=mission_deadline,
        )

        # 2. Check circuit breaker
        if not health.can_attempt():
            err_msg = (
                f"Provider {provider_name} circuit breaker is OPEN (consecutive failures: "
                f"{health.consecutive_failures}, reason: {health.last_failure_reason})"
            )
            logger.error(f"NetworkSupervisor: {err_msg}")
            self._publish_event(
                EventType.NETWORK_FAILED,
                mission_id=mission_id,
                turn_id=turn_id,
                severity=EventSeverity.ERROR,
                payload={"provider": provider_name, "error": err_msg},
            )
            return NormalizedModelResponse(
                text="",
                model=model,
                provider=provider_name,
                error=err_msg,
                success=False,
            )

        # 3. Create Logical Request
        logical_req = LogicalRequest(
            turn_id=turn_id,
            mission_id=mission_id,
            provider=provider_name,
            model=model,
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            total_timeout=budget.logical_request_timeout,
        )
        self._active_requests[logical_req.request_id] = logical_req

        self._publish_event(
            EventType.NETWORK_CONNECTING,
            mission_id=mission_id,
            turn_id=turn_id,
            payload={
                "request_id": logical_req.request_id,
                "provider": provider_name,
                "model": model,
                "streaming": stream,
            },
        )

        use_streaming = stream and adapter.capabilities.streaming
        attempt_index = 0

        while True:
            # Check deadline before starting attempt
            rem_budget = budget.remaining_budget()
            if rem_budget <= 0.0 or (cancel_event is not None and cancel_event.is_set()):
                reason = "CANCELLED" if (cancel_event and cancel_event.is_set()) else "DEADLINE_EXCEEDED"
                classification = (
                    FailureClassification.CANCELLED
                    if reason == "CANCELLED"
                    else FailureClassification.DEADLINE_EXCEEDED
                )
                logical_req.mark_failed(classification, f"Request aborted: {reason}")
                self._publish_event(
                    EventType.NETWORK_FAILED,
                    mission_id=mission_id,
                    turn_id=turn_id,
                    severity=EventSeverity.ERROR,
                    payload={"request_id": logical_req.request_id, "error": reason},
                )
                break

            attempt_index += 1
            attempt = logical_req.start_new_attempt(is_streaming=use_streaming)

            self._publish_event(
                EventType.NETWORK_CONNECTING,
                mission_id=mission_id,
                turn_id=turn_id,
                payload={
                    "request_id": logical_req.request_id,
                    "attempt_id": attempt.attempt_id,
                    "attempt_index": attempt_index,
                    "is_streaming": use_streaming,
                },
            )

            # Fresh connection guarantee on retries
            if attempt_index > 1:
                logger.info(
                    f"NetworkSupervisor: Closing stale connection pool for fresh connection retry ({provider_name})"
                )
                await adapter.aclose()

            effective_timeout = budget.effective_attempt_timeout()
            attempt_result: Optional[NormalizedModelResponse] = None
            attempt_failure: Optional[FailureClassification] = None
            attempt_error: Optional[str] = None

            try:
                if use_streaming:
                    attempt_result = await self._execute_streaming_attempt(
                        adapter=adapter,
                        attempt=attempt,
                        logical_req=logical_req,
                        model=model,
                        prompt=prompt,
                        system=system,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        budget=budget,
                        timeout=effective_timeout,
                        on_delta_callback=on_delta_callback,
                        cancel_event=cancel_event,
                        mission_id=mission_id,
                        turn_id=turn_id,
                        **kwargs,
                    )
                else:
                    attempt_result = await self._execute_non_streaming_attempt(
                        adapter=adapter,
                        attempt=attempt,
                        logical_req=logical_req,
                        model=model,
                        prompt=prompt,
                        system=system,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout=effective_timeout,
                        cancel_event=cancel_event,
                        mission_id=mission_id,
                        turn_id=turn_id,
                        **kwargs,
                    )

            except Exception as exc:
                classification = classify_httpx_exception(exc)
                attempt_failure = classification
                attempt_error = str(exc)
                attempt.fail(classification, attempt_error)
                logger.warning(
                    f"NetworkSupervisor: Attempt {attempt_index} failed ({classification.value}): {exc}"
                )

            # If attempt succeeded
            if attempt_result is not None and attempt_result.success:
                attempt.complete()
                logical_req.mark_completed()
                health.record_success()

                self._publish_event(
                    EventType.NETWORK_RESTORED if attempt_index > 1 else EventType.MODEL_COMPLETED,
                    mission_id=mission_id,
                    turn_id=turn_id,
                    payload={
                        "request_id": logical_req.request_id,
                        "attempt_id": attempt.attempt_id,
                        "attempts_count": attempt_index,
                        "provider": provider_name,
                    },
                )
                # Filter out any tool calls already executed to enforce tool replay safety
                filtered_tool_calls = []
                for tc in attempt_result.tool_calls:
                    tc_id = tc.get("id")
                    if tc_id and self.is_tool_call_executed(tc_id, turn_id=turn_id):
                        logger.warning(
                            f"NetworkSupervisor: Tool call {tc_id} already executed, suppressing duplicate replay"
                        )
                        continue
                    filtered_tool_calls.append(tc)
                attempt_result.tool_calls = filtered_tool_calls
                return attempt_result

            # Attempt failed: update health
            failure_cls = attempt_failure or FailureClassification.UNKNOWN_NETWORK_ERROR
            error_str = attempt_error or "Attempt failed without result"
            health.record_failure(error_str, classification=failure_cls)

            # Check if non-streaming fallback should be attempted
            if use_streaming and adapter.capabilities.non_streaming_fallback:
                logger.info(
                    f"NetworkSupervisor: Streaming attempt failed, falling back to non-streaming for next attempt"
                )
                use_streaming = False
                self._publish_event(
                    EventType.NETWORK_DEGRADED,
                    mission_id=mission_id,
                    turn_id=turn_id,
                    payload={
                        "request_id": logical_req.request_id,
                        "reason": "FALLBACK_TO_NON_STREAMING",
                    },
                )

            # Evaluate retry policy
            rem_budget = budget.remaining_budget()
            should_retry = self.retry_policy.should_retry(
                attempt_index=attempt_index,
                failure=failure_cls,
                remaining_budget=rem_budget,
            )

            if not should_retry:
                logical_req.mark_failed(failure_cls, error_str)
                self._publish_event(
                    EventType.NETWORK_FAILED,
                    mission_id=mission_id,
                    turn_id=turn_id,
                    severity=EventSeverity.ERROR,
                    payload={
                        "request_id": logical_req.request_id,
                        "error": error_str,
                        "classification": failure_cls.value,
                    },
                )
                return NormalizedModelResponse(
                    text="",
                    model=model,
                    provider=provider_name,
                    error=error_str,
                    success=False,
                )

            # Compute backoff delay and wait
            delay = self.retry_policy.compute_delay(attempt_index, remaining_budget=rem_budget)
            logger.info(
                f"NetworkSupervisor: Retrying request in {delay:.2f}s (attempt {attempt_index + 1}/{self.retry_policy.max_attempts})..."
            )
            self._publish_event(
                EventType.NETWORK_RECONNECTING,
                mission_id=mission_id,
                turn_id=turn_id,
                payload={
                    "request_id": logical_req.request_id,
                    "attempt_index": attempt_index,
                    "delay_seconds": delay,
                    "reason": failure_cls.value,
                },
            )
            try:
                if cancel_event is not None:
                    try:
                        await asyncio.wait_for(cancel_event.wait(), timeout=delay)
                        logical_req.mark_failed(FailureClassification.CANCELLED, "Cancelled during retry backoff")
                        return NormalizedModelResponse(
                            text="",
                            model=model,
                            provider=provider_name,
                            error="Cancelled during retry backoff",
                            success=False,
                        )
                    except asyncio.TimeoutError:
                        pass
                else:
                    await asyncio.sleep(delay)
            except asyncio.CancelledError:
                logical_req.mark_failed(FailureClassification.CANCELLED, "Sleep cancelled")
                return NormalizedModelResponse(
                    text="",
                    model=model,
                    provider=provider_name,
                    error="Cancelled during retry backoff",
                    success=False,
                )

        return NormalizedModelResponse(
            text="",
            model=model,
            provider=provider_name,
            error=logical_req.final_error or "Request failed",
            success=False,
        )

    async def _execute_streaming_attempt(
        self,
        adapter: BaseProviderAdapter,
        attempt: RequestAttempt,
        logical_req: LogicalRequest,
        model: str,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: Optional[int],
        budget: DeadlineBudget,
        timeout: float,
        on_delta_callback: Optional[Callable[[StreamDelta], Any]],
        cancel_event: Optional[asyncio.Event],
        mission_id: Optional[str],
        turn_id: Optional[str],
        **kwargs: Any,
    ) -> NormalizedModelResponse:
        """
        Execute streaming attempt monitored by StreamWatchdog.
        Aborts promptly on stall or cancel.
        """
        watchdog = StreamWatchdog(
            first_delta_timeout=min(budget.first_delta_timeout, timeout),
            idle_timeout=min(budget.idle_timeout, timeout),
        )
        watchdog.start()

        content_parts: List[str] = []
        reasoning_parts: List[str] = []
        tool_calls_accumulator: Dict[int, Dict[str, Any]] = {}
        finish_reason: Optional[str] = None

        self._publish_event(
            EventType.NETWORK_CONNECTED,
            mission_id=mission_id,
            turn_id=turn_id,
            payload={"request_id": logical_req.request_id, "attempt_id": attempt.attempt_id},
        )

        stream_gen = adapter.open_stream(
            model=model,
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            **kwargs,
        )

        aiter = stream_gen.__aiter__()

        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise asyncio.CancelledError("Cancellation requested during stream")

                remaining_attempt_time = max(0.01, timeout - (time.monotonic() - attempt.started_at))
                if (time.monotonic() - attempt.started_at) >= timeout:
                    raise TimeoutError(f"Attempt timeout exceeded ({timeout:.2f}s)")

                # Calculate allowed wait time for next chunk
                if not watchdog.has_first_delta:
                    allowed_wait = min(remaining_attempt_time, watchdog.first_delta_timeout)
                else:
                    gap_so_far = time.monotonic() - (watchdog._last_delta_at or attempt.started_at)
                    allowed_wait = min(remaining_attempt_time, max(0.01, watchdog.idle_timeout - gap_so_far))

                try:
                    delta: StreamDelta = await asyncio.wait_for(aiter.__anext__(), timeout=allowed_wait)
                except asyncio.TimeoutError:
                    if (time.monotonic() - attempt.started_at) >= timeout:
                        raise TimeoutError(f"Attempt timeout exceeded ({timeout:.2f}s)")
                    stall_reason = watchdog.check_stall() or "STREAM_STALL"
                    self._publish_event(
                        EventType.NETWORK_DISCONNECTED,
                        mission_id=mission_id,
                        turn_id=turn_id,
                        payload={
                            "request_id": logical_req.request_id,
                            "attempt_id": attempt.attempt_id,
                            "stall_reason": stall_reason,
                        },
                    )
                    raise TimeoutError(f"Stream stall detected: {stall_reason}")
                except StopAsyncIteration:
                    break

                # Delta arrived: record progress
                if not watchdog.has_first_delta:
                    watchdog.record_first_delta()
                    attempt.mark_first_delta()
                    self._publish_event(
                        EventType.MODEL_FIRST_TOKEN,
                        mission_id=mission_id,
                        turn_id=turn_id,
                        payload={
                            "request_id": logical_req.request_id,
                            "ttft_seconds": attempt.time_to_first_delta,
                        },
                    )
                else:
                    progress_len = len(delta.content) + len(delta.reasoning_content) + len(delta.tool_calls)
                    watchdog.record_delta(max(1, progress_len))
                    attempt.record_delta(max(1, progress_len))

                if delta.content:
                    content_parts.append(delta.content)
                if delta.reasoning_content:
                    reasoning_parts.append(delta.reasoning_content)
                if delta.finish_reason:
                    finish_reason = delta.finish_reason

                # Aggregate tool calls
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.get("index", 0)
                        if idx not in tool_calls_accumulator:
                            tool_calls_accumulator[idx] = {
                                "id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                                "name": tc.get("function", {}).get("name") or tc.get("name", ""),
                                "arguments_str": "",
                            }
                        if "function" in tc and "arguments" in tc["function"]:
                            tool_calls_accumulator[idx]["arguments_str"] += tc["function"]["arguments"]
                        elif "arguments" in tc and isinstance(tc["arguments"], str):
                            tool_calls_accumulator[idx]["arguments_str"] += tc["arguments"]

                if on_delta_callback is not None:
                    try:
                        res = on_delta_callback(delta)
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception as cb_err:
                        logger.warning(f"NetworkSupervisor: on_delta_callback error: {cb_err}")

        finally:
            watchdog.stop()

        if not content_parts and not tool_calls_accumulator and finish_reason is None:
            raise TimeoutError("Stream completed without producing any output or finish reason")

        # Build finalized tool calls
        final_tool_calls: List[Dict[str, Any]] = []
        for idx in sorted(tool_calls_accumulator.keys()):
            tc_dict = tool_calls_accumulator[idx]
            args_str = tc_dict.get("arguments_str", "")
            args_obj = {}
            if args_str:
                import json
                try:
                    args_obj = json.loads(args_str)
                except Exception:
                    args_obj = {"raw": args_str}
            final_tool_calls.append({
                "id": tc_dict["id"],
                "name": tc_dict["name"],
                "arguments": args_obj,
            })

        accumulated_text = "".join(content_parts)
        accumulated_reasoning = "".join(reasoning_parts)

        logical_req.accumulated_content = accumulated_text
        logical_req.accumulated_reasoning = accumulated_reasoning
        logical_req.accumulated_tool_calls = final_tool_calls
        logical_req.finish_reason = finish_reason

        return NormalizedModelResponse(
            text=accumulated_text,
            tool_calls=final_tool_calls,
            finish_reason=finish_reason,
            model=model,
            provider=adapter.provider_name,
            success=True,
        )

    async def _execute_non_streaming_attempt(
        self,
        adapter: BaseProviderAdapter,
        attempt: RequestAttempt,
        logical_req: LogicalRequest,
        model: str,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: Optional[int],
        timeout: float,
        cancel_event: Optional[asyncio.Event],
        mission_id: Optional[str],
        turn_id: Optional[str],
        **kwargs: Any,
    ) -> NormalizedModelResponse:
        """
        Execute non-streaming attempt bounded by hard timeout.
        """
        self._publish_event(
            EventType.NETWORK_CONNECTED,
            mission_id=mission_id,
            turn_id=turn_id,
            payload={"request_id": logical_req.request_id, "attempt_id": attempt.attempt_id},
        )

        resp_coro = adapter.execute_non_stream(
            model=model,
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            **kwargs,
        )

        if cancel_event is not None:
            # Race execution against cancellation
            task = asyncio.create_task(resp_coro)
            while not task.done():
                if cancel_event.is_set():
                    task.cancel()
                    raise asyncio.CancelledError("Cancellation requested during non-stream request")
                await asyncio.sleep(0.1)
            resp = await task
        else:
            resp = await asyncio.wait_for(resp_coro, timeout=timeout)

        logical_req.accumulated_content = resp.text
        logical_req.accumulated_tool_calls = resp.tool_calls
        logical_req.finish_reason = resp.finish_reason
        return resp
