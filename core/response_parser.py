# core/response_parser.py
# Hardened response parser for HERMES.
# Handles every known Tier 1 response failure mode:
#   1. Clean JSON (ideal case)
#   2. JSON wrapped in markdown fences
#   3. JSON embedded in prose explanation
#   4. JSON with Python-style single quotes instead of double quotes
#   5. JSON missing the outer braces (just key-value pairs)
#   6. Partial JSON (truncated response)
# If none of the above work, returns a structured ParseFailure object.
# Never raises. Always returns either a ParseSuccess or ParseFailure.

import json
import re
from dataclasses import dataclass
from typing import Optional, Union
from loguru import logger


@dataclass
class ParseSuccess:
    """Successful parse result."""
    tool: str
    parameters: dict
    reasoning: str
    explanation: str
    method_used: str           # Which parsing strategy worked
    raw_response: str

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "parameters": self.parameters,
            "reasoning": self.reasoning,
            "explanation": self.explanation
        }


@dataclass
class ParseFailure:
    """Failed parse result with diagnostic information."""
    raw_response: str
    failure_reason: str
    methods_tried: list[str]
    response_length: int
    
    @property
    def is_plain_text(self) -> bool:
        """The model responded with a plain text explanation instead of JSON."""
        r = self.raw_response.strip()
        return (r.startswith("I ") or r.startswith("Sure") or
                r.startswith("Of course") or (r.count("{") == 0))
    
    @property
    def has_json_fragment(self) -> bool:
        """The response contains some JSON but it could not be parsed."""
        return "{" in self.raw_response and "}" in self.raw_response


class ResponseParser:
    """Parse a Tier 1 response into a structured result. Never raises. Tries 6 strategies in order."""

    def parse(self, response: str) -> Union[ParseSuccess, ParseFailure]:
        if not response or not response.strip():
            return ParseFailure(
                raw_response=response,
                failure_reason="empty_response",
                methods_tried=[],
                response_length=0
            )

        methods_tried = []

        # ── Strategy 1: Direct JSON parse ────────────────────────────────────
        methods_tried.append("direct_parse")
        result = self._try_direct_parse(response)
        if result:
            return result

        # ── Strategy 2: Strip markdown fences ────────────────────────────────
        methods_tried.append("strip_markdown_fences")
        result = self._try_strip_fences(response)
        if result:
            return result

        # ── Strategy 3: Extract first complete JSON object ───────────────────
        methods_tried.append("extract_first_json_object")
        result = self._try_extract_json_object(response)
        if result:
            return result

        # ── Strategy 4: Fix single quotes → double quotes ────────────────────
        methods_tried.append("fix_single_quotes")
        result = self._try_fix_single_quotes(response)
        if result:
            return result

        # ── Strategy 5: Reconstruct from fragments ───────────────────────────
        methods_tried.append("reconstruct_from_fragments")
        result = self._try_reconstruct(response)
        if result:
            return result

        # ── Strategy 6: Emergency minimal extraction ─────────────────────────
        methods_tried.append("emergency_extraction")
        result = self._try_emergency_extraction(response)
        if result:
            return result

        # ── All strategies failed ─────────────────────────────────────────────
        reason = self._diagnose_failure(response)
        logger.warning(f"ResponseParser: all 6 strategies failed | reason={reason} | response={response[:100]!r}")
        return ParseFailure(
            raw_response=response,
            failure_reason=reason,
            methods_tried=methods_tried,
            response_length=len(response)
        )

    def _validate_and_build(self, data: dict, method: str, raw: str) -> Optional[ParseSuccess]:
        if not isinstance(data, dict):
            return None
        tool = data.get("tool") or data.get("action") or data.get("tool_name")
        if not tool or not isinstance(tool, str):
            return None
        parameters = data.get("parameters") or data.get("params") or data.get("args") or {}
        if not isinstance(parameters, dict):
            parameters = {}
        reasoning = str(data.get("reasoning") or data.get("thought") or data.get("reason") or "")
        explanation = str(data.get("explanation") or data.get("message") or data.get("output") or "")
        logger.debug(f"ResponseParser: success via {method} | tool={tool}")
        return ParseSuccess(
            tool=tool,
            parameters=parameters,
            reasoning=reasoning,
            explanation=explanation,
            method_used=method,
            raw_response=raw
        )

    def _try_direct_parse(self, response: str) -> Optional[ParseSuccess]:
        try:
            data = json.loads(response.strip())
            return self._validate_and_build(data, "direct_parse", response)
        except (json.JSONDecodeError, ValueError):
            return None

    def _try_strip_fences(self, response: str) -> Optional[ParseSuccess]:
        cleaned = response.strip()
        # Remove opening fence
        cleaned = re.sub(r'^```json\s*\n?', '', cleaned)
        cleaned = re.sub(r'^```\s*\n?', '', cleaned)
        # Remove closing fence
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        cleaned = cleaned.strip()
        try:
            data = json.loads(cleaned)
            return self._validate_and_build(data, "strip_markdown_fences", response)
        except (json.JSONDecodeError, ValueError):
            return None

    def _try_extract_json_object(self, response: str) -> Optional[ParseSuccess]:
        # Find the outermost complete JSON object
        depth = 0
        start = -1
        for i, char in enumerate(response):
            if char == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0 and start >= 0:
                    candidate = response[start:i+1]
                    try:
                        data = json.loads(candidate)
                        return self._validate_and_build(data, "extract_first_json_object", response)
                    except (json.JSONDecodeError, ValueError):
                        start = -1  # reset and keep looking
        return None

    def _try_fix_single_quotes(self, response: str) -> Optional[ParseSuccess]:
        # Find the JSON portion and attempt single→double quote conversion
        # Only attempt on strings that look like they contain a JSON object
        if '"tool"' not in response and "'tool'" not in response and '"action"' not in response and "'action'" not in response:
            return None
        try:
            # Replace Python-style single-quoted strings with double quotes
            # This is tricky — only replace quotes used as JSON delimiters
            fixed = response.strip()
            # Isolate JSON portion first if braces are present
            start = fixed.find('{')
            end = fixed.rfind('}')
            if start >= 0 and end >= 0:
                json_portion = fixed[start:end+1]
                json_portion = re.sub(r"'([^']*)'(\s*:)", r'"\1"\2', json_portion)  # keys
                json_portion = re.sub(r':\s*\'([^\']*?)\'', r': "\1"', json_portion)  # string values
                data = json.loads(json_portion)
                return self._validate_and_build(data, "fix_single_quotes", response)

            fixed = re.sub(r"'([^']*)'(\s*:)", r'"\1"\2', fixed)  # keys
            fixed = re.sub(r':\s*\'([^\']*?)\'', r': "\1"', fixed)  # string values
            data = json.loads(fixed)
            return self._validate_and_build(data, "fix_single_quotes", response)
        except (json.JSONDecodeError, ValueError, re.error):
            return None

    def _try_reconstruct(self, response: str) -> Optional[ParseSuccess]:
        # Try to find individual fields and reconstruct the object
        tool_match = re.search(r'"tool"\s*:\s*"([^"]+)"', response)
        if not tool_match:
            tool_match = re.search(r"'tool'\s*:\s*'([^']+)'", response)
        if not tool_match:
            tool_match = re.search(r'"action"\s*:\s*"([^"]+)"', response)
        if not tool_match:
            tool_match = re.search(r"'action'\s*:\s*'([^']+)'", response)
        if not tool_match:
            return None

        tool_name = tool_match.group(1)

        # Extract parameters block
        params = {}
        params_match = re.search(r'"parameters"\s*:\s*(\{[^}]*\})', response, re.DOTALL)
        if not params_match:
            params_match = re.search(r"'parameters'\s*:\s*(\{[^}]*\})", response, re.DOTALL)
        if not params_match:
            params_match = re.search(r'"params"\s*:\s*(\{[^}]*\})', response, re.DOTALL)
        if not params_match:
            params_match = re.search(r"'params'\s*:\s*(\{[^}]*\})", response, re.DOTALL)

        if params_match:
            try:
                params = json.loads(params_match.group(1))
            except (json.JSONDecodeError, ValueError):
                try:
                    fixed_params = re.sub(r"'([^']*)'(\s*:)", r'"\1"\2', params_match.group(1))
                    fixed_params = re.sub(r':\s*\'([^\']*?)\'', r': "\1"', fixed_params)
                    params = json.loads(fixed_params)
                except (json.JSONDecodeError, ValueError, re.error):
                    pass

        reasoning_match = re.search(r'"reasoning"\s*:\s*"([^"]*)"', response)
        if not reasoning_match:
            reasoning_match = re.search(r"'reasoning'\s*:\s*'([^']*)'", response)
        reasoning = reasoning_match.group(1) if reasoning_match else "Reconstructed from partial response"

        explanation_match = re.search(r'"explanation"\s*:\s*"([^"]*)"', response)
        if not explanation_match:
            explanation_match = re.search(r"'explanation'\s*:\s*'([^']*)'", response)
        explanation = explanation_match.group(1) if explanation_match else "Action proceeding."

        logger.debug(f"ResponseParser: reconstructed | tool={tool_name} | params={params}")
        return ParseSuccess(
            tool=tool_name,
            parameters=params,
            reasoning=reasoning,
            explanation=explanation,
            method_used="reconstruct_from_fragments",
            raw_response=response
        )

    def _is_conversational_prose(self, response: str) -> bool:
        r = response.strip()
        prefixes = ("i ", "sure", "of course", "i'll", "i will", "let me", "to ", "ok", "here", "using", "the ", "we ", "this ")
        return r.lower().startswith(prefixes)

    def _try_emergency_extraction(self, response: str) -> Optional[ParseSuccess]:
        # Last resort: look for any known tool name in the response
        if not self._is_conversational_prose(response):
            return None

        from tools.registry import list_tools
        available_tools = list_tools()

        response_lower = response.lower()
        for tool_name in available_tools:
            # Use word boundaries to ensure we match the exact tool name
            if re.search(r'\b' + re.escape(tool_name) + r'\b', response_lower):
                logger.warning(f"ResponseParser: emergency extraction — found tool name '{tool_name}' in plain text response")
                return ParseSuccess(
                    tool=tool_name,
                    parameters={},
                    reasoning="Emergency extraction from plain text response.",
                    explanation="Proceeding with best-guess tool selection.",
                    method_used="emergency_extraction",
                    raw_response=response
                )
        return None

    def _diagnose_failure(self, response: str) -> str:
        r = response.strip()
        if not r:
            return "empty_response"
        if r.startswith(("I ", "Sure", "Of course", "I'll", "I will", "Let me", "To ")):
            return "model_responded_with_plain_text_no_json"
        if r.count("{") == 0:
            return "no_json_braces_found_at_all"
        if r.count('"tool"') == 0 and r.count("'tool'") == 0 and r.count('"action"') == 0 and r.count("'action'") == 0:
            return "json_found_but_no_tool_key"
        if r.count('"') < 4 and r.count("'") < 4:
            return "insufficient_json_quotes"
        return "json_malformed_unparseable"
