# core/agent_loop/decisions.py
"""
Decision Interpreter for HERMES 2.x Agent Loop.
Classifies model outputs (native tool calls, structured JSON, conversational text)
into semantic agent decisions:
    ACT, ASK_USER, VERIFY, DELEGATE, COMPLETE, CONTINUE_REASONING, ABORT, INVALID
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple
from loguru import logger

from core.agent_loop.types import AgentDecision, AgentDecisionType
from core.response_parser import ResponseParser


class DecisionInterpreter:
    """
    Translates raw model responses into canonical AgentDecision objects.
    Enforces native tool calling preference and handles conversational fallbacks.
    """

    def __init__(self) -> None:
        self._parser = ResponseParser()

    def interpret(self, response: Any, turn_id: Optional[str] = None) -> AgentDecision:
        """
        Interpret model response into an AgentDecision.
        Accepts NormalizedModelResponse, dict, or raw text.
        """
        raw_val = getattr(response, "text", None) or getattr(response, "content", None)
        if raw_val is not None and not hasattr(raw_val, "assert_called"):
            raw_text = str(raw_val).strip()
        else:
            raw_text = ""
        # Redact hidden chain of thought for decision processing
        clean_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()

        # ── 1. Check Native Tool Calls (OpenAI/NIM format) ───────────────────
        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls and isinstance(tool_calls, list) and len(tool_calls) > 0:
            parsed_calls = []
            for tc in tool_calls:
                call_id = tc.get("id") or tc.get("tool_call_id")
                fn = tc.get("function", {})
                name = fn.get("name") or tc.get("name") or tc.get("tool")
                args_raw = fn.get("arguments") or tc.get("arguments") or tc.get("parameters", {})
                if isinstance(args_raw, str):
                    try:
                        args = json.loads(args_raw)
                    except Exception:
                        args = {"raw_arguments": args_raw}
                elif isinstance(args_raw, dict):
                    args = args_raw
                else:
                    args = {}
                parsed_calls.append({"id": call_id, "name": name, "arguments": args})

            primary_call = parsed_calls[0]
            dec = self._classify_tool_call(
                tool_name=primary_call["name"],
                arguments=primary_call["arguments"],
                tool_call_id=primary_call["id"],
                reasoning=clean_text,
                turn_id=turn_id,
                raw_text=raw_text
            )
            dec.tool_calls = parsed_calls
            return dec

        # ── 2. Parse Text / JSON via ResponseParser ──────────────────────────
        parsed_result = self._parser.parse(response)

        if hasattr(parsed_result, "to_dict"):  # ParseSuccess
            p_dict = parsed_result.to_dict()
            tool_name = p_dict.get("tool")
            parameters = p_dict.get("parameters", {})
            explanation = p_dict.get("explanation", "")
            reasoning = p_dict.get("reasoning", "")

            # If tool is None or explicit conversational indicator
            if not tool_name or tool_name.lower() in ("none", "null", "no_tool", "finish", "done"):
                return self._classify_text_response(
                    text=explanation or clean_text,
                    reasoning=reasoning,
                    turn_id=turn_id,
                    raw_text=raw_text
                )

            return self._classify_tool_call(
                tool_name=tool_name,
                arguments=parameters,
                tool_call_id=None,
                reasoning=reasoning or explanation,
                turn_id=turn_id,
                raw_text=raw_text
            )

        # ── 3. Parse Failure: Evaluate if conversational or invalid ──────────
        # Check if the output contains a malformed/partial tool JSON attempt
        if getattr(parsed_result, "has_json_fragment", False) or clean_text.startswith("{") or '"tool"' in clean_text or "'tool'" in clean_text:
            failure_reason = getattr(parsed_result, "failure_reason", "Malformed or incomplete tool JSON")
            logger.warning(f"DecisionInterpreter: malformed tool JSON detected | reason={failure_reason}")
            return AgentDecision(
                decision_type=AgentDecisionType.INVALID,
                reasoning=f"Invalid or malformed tool JSON: {failure_reason}. Please emit valid JSON matching the tool schema.",
                raw_text=raw_text,
                turn_id=turn_id
            )

        if getattr(parsed_result, "is_plain_text", False) or len(clean_text) > 0:
            # Check if this plain text represents an answer, question, or completion
            return self._classify_text_response(
                text=clean_text,
                reasoning="Plain text response without JSON schema",
                turn_id=turn_id,
                raw_text=raw_text
            )

        # Completely uninterpretable output
        failure_reason = getattr(parsed_result, "failure_reason", "Unable to parse model output")
        logger.warning(f"DecisionInterpreter: parse failed | reason={failure_reason}")
        return AgentDecision(
            decision_type=AgentDecisionType.INVALID,
            reasoning=f"Parse failure: {failure_reason}",
            raw_text=raw_text,
            turn_id=turn_id
        )

    def _classify_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_call_id: Optional[str],
        reasoning: str,
        turn_id: Optional[str],
        raw_text: str
    ) -> AgentDecision:
        """Classify a proposed tool call into semantic decision."""
        t_lower = tool_name.lower().strip() if tool_name else ""

        # Special semantic tools
        if t_lower in ("ask_user", "ask_question", "user_prompt"):
            q = arguments.get("question") or arguments.get("prompt") or arguments.get("message") or reasoning
            return AgentDecision(
                decision_type=AgentDecisionType.ASK_USER,
                tool_name=tool_name,
                arguments=arguments,
                tool_call_id=tool_call_id,
                user_question=q,
                reasoning=reasoning,
                turn_id=turn_id,
                raw_text=raw_text
            )

        if t_lower in ("complete", "finish_task", "mark_complete", "mission_complete"):
            return AgentDecision(
                decision_type=AgentDecisionType.COMPLETE,
                tool_name=tool_name,
                arguments=arguments,
                tool_call_id=tool_call_id,
                explanation=arguments.get("summary") or reasoning,
                reasoning=reasoning,
                turn_id=turn_id,
                raw_text=raw_text
            )

        if t_lower in ("verify", "verify_task", "run_verification"):
            return AgentDecision(
                decision_type=AgentDecisionType.VERIFY,
                tool_name=tool_name,
                arguments=arguments,
                tool_call_id=tool_call_id,
                verification_target=arguments.get("target") or arguments.get("file"),
                reasoning=reasoning,
                turn_id=turn_id,
                raw_text=raw_text
            )

        if t_lower in ("delegate", "delegate_subagent", "invoke_subagent"):
            return AgentDecision(
                decision_type=AgentDecisionType.DELEGATE,
                tool_name=tool_name,
                arguments=arguments,
                tool_call_id=tool_call_id,
                delegation_target=arguments.get("agent_type") or arguments.get("target"),
                reasoning=reasoning,
                turn_id=turn_id,
                raw_text=raw_text
            )

        # Standard tool execution
        return AgentDecision(
            decision_type=AgentDecisionType.ACT,
            tool_name=tool_name,
            arguments=arguments,
            tool_call_id=tool_call_id,
            reasoning=reasoning,
            turn_id=turn_id,
            raw_text=raw_text
        )

    def _classify_text_response(
        self,
        text: str,
        reasoning: str,
        turn_id: Optional[str],
        raw_text: str
    ) -> AgentDecision:
        """Classify non-tool textual responses."""
        lower = text.lower().strip()

        # Check for explicit user questions
        is_question = lower.endswith("?") and any(
            lower.startswith(w) for w in (
                "would you", "could you", "do you want", "should i", "which",
                "can you clarify", "please specify", "what would you", "how would you"
            )
        )
        if is_question:
            return AgentDecision(
                decision_type=AgentDecisionType.ASK_USER,
                user_question=text,
                reasoning=reasoning,
                explanation=text,
                turn_id=turn_id,
                raw_text=raw_text
            )

        # Check for explicit completion claims
        completion_cues = (
            "task complete", "mission complete", "i have completed", "everything is implemented",
            "all requirements are satisfied", "here is the completed", "build is complete",
            "the implementation is done", "all done", "created and verified", "is created", "has been created",
            "completed and verified", "successfully created", "is complete", "are complete", "done.", "finished.",
        )
        if any(cue in lower for cue in completion_cues):
            return AgentDecision(
                decision_type=AgentDecisionType.COMPLETE,
                explanation=text,
                reasoning=reasoning,
                turn_id=turn_id,
                raw_text=raw_text
            )

        # General conversational response or thought continuation
        return AgentDecision(
            decision_type=AgentDecisionType.CONTINUE_REASONING,
            explanation=text,
            reasoning=reasoning,
            turn_id=turn_id,
            raw_text=raw_text
        )
