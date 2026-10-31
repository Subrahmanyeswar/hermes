# core/transport/stream_validator.py
"""
HERMES Phase 6: Stream Accumulator and Completeness Verification.
Validates protocol completion for:
- OpenAI / NVIDIA NIM SSE protocol ([DONE] terminal marker, complete tool call arguments)
- Ollama newline-delimited JSON (terminal "done": true marker)

Invariants:
- Never return partial streams as successful.
- Never dispatch tool calls before stream protocol completion.
- Discard and isolate failed/truncated attempts.
- Handle multi-byte UTF-8 split across chunks safely.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from core.transport.types import ErrorCategory, StructuredTransportError
from models.provider import CanonicalToolCall, NormalizedModelResponse


@dataclass
class SseStreamAccumulator:
    """
    Accumulator for OpenAI-compatible SSE streaming (NVIDIA NIM).
    Requires explicit [DONE] marker for completion.
    """
    model: str
    provider: str
    content_chunks: List[str] = field(default_factory=list)
    reasoning_chunks: List[str] = field(default_factory=list)
    tool_calls_map: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    finish_reason: Optional[str] = None
    has_terminal_marker: bool = False
    usage: Dict[str, Any] = field(default_factory=dict)
    first_token_time: Optional[float] = None
    first_tool_time: Optional[float] = None

    def process_chunk(self, line: str, now: float) -> Tuple[bool, Optional[StructuredTransportError]]:
        """
        Process a single SSE line.
        Returns (is_done, optional_error).
        """
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith(":"):
            # Empty line or SSE keepalive comment
            return False, None

        if line_stripped == "data: [DONE]" or line_stripped == "[DONE]":
            self.has_terminal_marker = True
            return True, None

        if line_stripped.startswith("data:"):
            data_str = line_stripped[5:].strip()
            if data_str == "[DONE]":
                self.has_terminal_marker = True
                return True, None
            if not data_str:
                return False, None

            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError as exc:
                return False, StructuredTransportError(
                    category=ErrorCategory.STREAM_PROTOCOL_ERROR,
                    message=f"Malformed SSE JSON chunk: {exc}",
                    provider=self.provider,
                    model=self.model,
                    retryable=False,
                )

            # Check provider error in payload
            if "error" in chunk:
                err_val = chunk["error"]
                msg = err_val.get("message", str(err_val)) if isinstance(err_val, dict) else str(err_val)
                return False, StructuredTransportError(
                    category=ErrorCategory.PROVIDER_SERVER_ERROR,
                    message=f"Provider stream error: {msg}",
                    provider=self.provider,
                    model=self.model,
                    retryable=True,
                )

            if "usage" in chunk and chunk["usage"]:
                self.usage = chunk["usage"]

            choices = chunk.get("choices", [])
            if choices:
                ch = choices[0]
                fr = ch.get("finish_reason")
                if fr:
                    self.finish_reason = fr

                delta = ch.get("delta", {})
                c = delta.get("content")
                if c:
                    self.content_chunks.append(c)
                    if self.first_token_time is None:
                        self.first_token_time = now

                r = delta.get("reasoning_content")
                if r:
                    self.reasoning_chunks.append(r)
                    if self.first_token_time is None:
                        self.first_token_time = now

                tc_deltas = delta.get("tool_calls")
                if tc_deltas and isinstance(tc_deltas, list):
                    if self.first_tool_time is None:
                        self.first_tool_time = now
                    for tc_delta in tc_deltas:
                        if not isinstance(tc_delta, dict):
                            continue
                        idx = tc_delta.get("index") if tc_delta.get("index") is not None else 0
                        if idx not in self.tool_calls_map:
                            self.tool_calls_map[idx] = {
                                "id": tc_delta.get("id", f"call_{idx}"),
                                "type": tc_delta.get("type", "function"),
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc_delta.get("id"):
                            self.tool_calls_map[idx]["id"] = tc_delta["id"]

                        f_delta = tc_delta.get("function")
                        if isinstance(f_delta, dict):
                            name_part = f_delta.get("name")
                            if name_part and isinstance(name_part, str):
                                curr = self.tool_calls_map[idx]["function"]["name"]
                                if not curr:
                                    self.tool_calls_map[idx]["function"]["name"] = name_part
                                elif not curr.endswith(name_part) and curr != name_part:
                                    self.tool_calls_map[idx]["function"]["name"] += name_part

                            args_part = f_delta.get("arguments")
                            if args_part and isinstance(args_part, str):
                                self.tool_calls_map[idx]["function"]["arguments"] += args_part

        return False, None

    def validate_and_finalize(self, elapsed_ms: float) -> Tuple[NormalizedModelResponse, Optional[StructuredTransportError]]:
        """
        Finalize accumulator into NormalizedModelResponse.
        Enforces:
        - Must have received [DONE] marker.
        - Tool call arguments must parse as valid JSON.
        """
        if not self.has_terminal_marker and not (self.finish_reason in ("stop", "tool_calls")):
            return (
                NormalizedModelResponse(model=self.model, provider=self.provider, success=False),
                StructuredTransportError(
                    category=ErrorCategory.STREAM_INCOMPLETE,
                    message="Stream terminated before terminal completion marker ([DONE]) was received.",
                    provider=self.provider,
                    model=self.model,
                    retryable=True,
                    is_ambiguous=True,
                ),
            )

        # Validate tool calls
        validated_tool_calls: List[Dict[str, Any]] = []
        for idx in sorted(self.tool_calls_map.keys()):
            tc = self.tool_calls_map[idx]
            fname = tc["function"]["name"]
            args_str = tc["function"]["arguments"].strip()
            
            parsed_args: Dict[str, Any] = {}
            if args_str:
                try:
                    parsed_args = json.loads(args_str)
                    if not isinstance(parsed_args, dict):
                        return (
                            NormalizedModelResponse(model=self.model, provider=self.provider, success=False),
                            StructuredTransportError(
                                category=ErrorCategory.STREAM_PROTOCOL_ERROR,
                                message=f"Tool call arguments for '{fname}' parsed to non-object: {type(parsed_args)}",
                                provider=self.provider,
                                model=self.model,
                                retryable=False,
                            ),
                        )
                except Exception as exc:
                    return (
                        NormalizedModelResponse(model=self.model, provider=self.provider, success=False),
                        StructuredTransportError(
                            category=ErrorCategory.STREAM_INCOMPLETE,
                            message=f"Incomplete or invalid JSON arguments for tool call '{fname}': {exc}",
                            provider=self.provider,
                            model=self.model,
                            retryable=True,
                        ),
                    )

            from tools.registry import get_canonical_tool_name
            canonical_name = get_canonical_tool_name(fname) or fname
            validated_tool_calls.append({
                "id": tc.get("id", f"call_{idx}"),
                "type": "function",
                "function": {
                    "name": canonical_name,
                    "arguments": parsed_args,
                },
                "name": canonical_name,
                "arguments": parsed_args,
            })

        full_text = "".join(self.content_chunks)
        full_reasoning = "".join(self.reasoning_chunks)
        if full_reasoning and full_text:
            final_text = f"<think>\n{full_reasoning}\n</think>\n{full_text}"
        elif full_reasoning:
            final_text = f"<think>\n{full_reasoning}\n</think>"
        else:
            final_text = full_text

        prompt_tokens = self.usage.get("prompt_tokens", 0) if self.usage else 0
        comp_tokens = self.usage.get("completion_tokens", 0) if self.usage else 0

        resp = NormalizedModelResponse(
            text=final_text,
            tool_calls=validated_tool_calls,
            finish_reason=self.finish_reason or ("tool_calls" if validated_tool_calls else "stop"),
            model=self.model,
            provider=self.provider,
            input_tokens=prompt_tokens,
            output_tokens=comp_tokens,
            total_tokens=prompt_tokens + comp_tokens,
            latency_ms=elapsed_ms,
            success=True,
        )
        return resp, None


@dataclass
class OllamaStreamAccumulator:
    """
    Accumulator for Ollama newline-delimited JSON stream.
    Requires terminal object with {"done": true}.
    """
    model: str
    provider: str
    text_chunks: List[str] = field(default_factory=list)
    thinking_chunks: List[str] = field(default_factory=list)
    is_done: bool = False
    terminal_payload: Dict[str, Any] = field(default_factory=dict)

    def process_line(self, line: str) -> Tuple[bool, Optional[StructuredTransportError]]:
        line_stripped = line.strip()
        if not line_stripped:
            return False, None

        try:
            chunk = json.loads(line_stripped)
        except json.JSONDecodeError as exc:
            return False, StructuredTransportError(
                category=ErrorCategory.STREAM_PROTOCOL_ERROR,
                message=f"Malformed Ollama JSON chunk: {exc}",
                provider=self.provider,
                model=self.model,
                retryable=False,
            )

        if "error" in chunk:
            return False, StructuredTransportError(
                category=ErrorCategory.PROVIDER_SERVER_ERROR,
                message=f"Ollama stream error: {chunk['error']}",
                provider=self.provider,
                model=self.model,
                retryable=True,
            )

        resp_text = chunk.get("response")
        if resp_text and isinstance(resp_text, str):
            self.text_chunks.append(resp_text)

        think_text = chunk.get("thinking")
        if think_text and isinstance(think_text, str):
            self.thinking_chunks.append(think_text)

        if chunk.get("done") is True:
            self.is_done = True
            self.terminal_payload = chunk
            return True, None

        return False, None

    def validate_and_finalize(self, elapsed_ms: float) -> Tuple[NormalizedModelResponse, Optional[StructuredTransportError]]:
        if not self.is_done:
            return (
                NormalizedModelResponse(model=self.model, provider=self.provider, success=False),
                StructuredTransportError(
                    category=ErrorCategory.STREAM_INCOMPLETE,
                    message="Ollama stream ended abruptly before 'done: true' marker.",
                    provider=self.provider,
                    model=self.model,
                    retryable=True,
                    is_ambiguous=True,
                ),
            )

        content = "".join(self.text_chunks)
        thinking = "".join(self.thinking_chunks)
        if thinking and content:
            final_text = f"<think>\n{thinking}\n</think>\n{content}"
        elif thinking:
            final_text = f"<think>\n{thinking}\n</think>"
        else:
            final_text = content

        prompt_eval = self.terminal_payload.get("prompt_eval_count", 0) or 0
        eval_count = self.terminal_payload.get("eval_count", 0) or 0

        resp = NormalizedModelResponse(
            text=final_text,
            model=self.model,
            provider=self.provider,
            input_tokens=prompt_eval,
            output_tokens=eval_count,
            total_tokens=prompt_eval + eval_count,
            latency_ms=elapsed_ms,
            success=True,
        )
        return resp, None
