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
import os
import re
from dataclasses import dataclass
from typing import Optional, Union, Any, Set
from loguru import logger


def _get_known_tools() -> Set[str]:
    """Return the set of all recognized tool names, including batch tools and known aliases."""
    try:
        from tools.registry import list_tools
        registered = set(list_tools())
    except Exception:
        registered = set()
    registered.update({"write_files_batch", "list_files", "create_directory", "list_dir"})
    return registered


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

    def parse(self, response: Any) -> Union[ParseSuccess, ParseFailure]:
        # ── Strategy 0: Native provider tool_calls ─────────────────────────
        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls is None and isinstance(response, dict):
            tool_calls = response.get("tool_calls")
        if tool_calls:
            try:
                # If provider returned multiple write_file calls, convert to write_files_batch
                write_file_calls = [
                    tc for tc in tool_calls
                    if tc.get("function", {}).get("name") in ("write_file", "create_file")
                ]
                if len(write_file_calls) >= 2 and len(write_file_calls) <= 3:
                    batch_items = []
                    for tc in write_file_calls:
                        fn = tc.get("function", {})
                        args = self._parse_tool_arguments("write_file", fn.get("arguments", {}))
                        p = args.get("path") or args.get("file_path")
                        c = args.get("content", "")
                        if p and c is not None:
                            batch_items.append({
                                "path": p,
                                "content": c,
                                "mode": args.get("mode", "overwrite"),
                            })
                    if len(batch_items) >= 2:
                        logger.info(f"ResponseParser: synthesized write_files_batch from {len(batch_items)} native write_file calls")
                        return ParseSuccess(
                            tool="write_files_batch",
                            parameters={"files": batch_items},
                            reasoning="Native tool calls emitted multiple file writes; batched atomically.",
                            explanation=f"Executed batch write for {len(batch_items)} files.",
                            method_used="native_tool_call_batch",
                            raw_response=getattr(response, "text", str(response)),
                        )

                # If mixed calls and one is write_file, prefer the write_file call
                active_tc = write_file_calls[0] if (len(write_file_calls) == 1 and len(tool_calls) > 1) else tool_calls[0]
                fn = active_tc.get("function", {})
                tname = fn.get("name", "")
                args_raw = fn.get("arguments", {})
                params = self._parse_tool_arguments(tname, args_raw)

                if tname and (params or tname not in ("write_file", "append_file", "read_file", "bash_exec")):
                    logger.debug(f"ResponseParser: success via native_tool_call | tool={tname}")
                    return ParseSuccess(
                        tool=tname,
                        parameters=params,
                        reasoning="Native tool call emitted by provider.",
                        explanation=f"Executed native tool call {tname}.",
                        method_used="native_tool_call",
                        raw_response=getattr(response, "text", str(response)),
                    )
            except Exception as e:
                logger.debug(f"ResponseParser: native_tool_call extraction exception: {e}")

        raw_str = response.text if hasattr(response, "text") else str(response or "")
        if not raw_str or not raw_str.strip():
            return ParseFailure(
                raw_response=raw_str,
                failure_reason="empty_response",
                methods_tried=[],
                response_length=0
            )
        response = raw_str

        # Extract <think> reasoning block from DeepSeek-R1 / reasoning models
        think_reasoning = ""
        cleaned_response = response.strip()
        think_match = re.search(r'<think>(.*?)</think>', cleaned_response, re.DOTALL)
        if think_match:
            think_reasoning = think_match.group(1).strip()
            stripped_think = re.sub(r'<think>.*?</think>', '', cleaned_response, flags=re.DOTALL).strip()
            if stripped_think:
                cleaned_response = stripped_think
            else:
                cleaned_response = think_reasoning
        elif "<think>" in cleaned_response and "</think>" not in cleaned_response:
            think_reasoning = cleaned_response.replace("<think>", "").strip()
            cleaned_response = think_reasoning

        methods_tried = []

        # ── Strategy 1: Direct JSON parse ────────────────────────────────────
        methods_tried.append("direct_parse")
        result = self._try_direct_parse(cleaned_response)
        if result:
            if think_reasoning and not result.reasoning:
                result.reasoning = think_reasoning
            return result

        # ── Strategy 2: Strip markdown fences ────────────────────────────────
        methods_tried.append("strip_markdown_fences")
        result = self._try_strip_fences(cleaned_response)
        if result:
            if think_reasoning and not result.reasoning:
                result.reasoning = think_reasoning
            return result

        # ── Strategy 3: Extract first complete JSON object ───────────────────
        methods_tried.append("extract_first_json_object")
        result = self._try_extract_json_object(cleaned_response)
        if result:
            if think_reasoning and not result.reasoning:
                result.reasoning = think_reasoning
            return result

        # ── Strategy 4: Fix single quotes → double quotes ────────────────────
        methods_tried.append("fix_single_quotes")
        result = self._try_fix_single_quotes(cleaned_response)
        if result:
            if think_reasoning and not result.reasoning:
                result.reasoning = think_reasoning
            return result

        # ── Strategy 5: Reconstruct from fragments ───────────────────────────
        methods_tried.append("reconstruct_from_fragments")
        result = self._try_reconstruct(cleaned_response)
        if result:
            if think_reasoning and not result.reasoning:
                result.reasoning = think_reasoning
            return result

        # ── Strategy 6: Extract markdown code block ──────────────────────────
        methods_tried.append("extract_code_block")
        result = self._try_extract_code_block(cleaned_response)
        if not result and think_reasoning and think_reasoning != cleaned_response:
            result = self._try_extract_code_block(think_reasoning)
        if result:
            if think_reasoning and not result.reasoning:
                result.reasoning = think_reasoning
            return result

        # ── Strategy 7: Emergency minimal extraction ─────────────────────────
        methods_tried.append("emergency_extraction")
        result = self._try_emergency_extraction(cleaned_response)
        if not result and think_reasoning and think_reasoning != cleaned_response:
            result = self._try_emergency_extraction(think_reasoning)
        if result:
            if think_reasoning and not result.reasoning:
                result.reasoning = think_reasoning
            return result

        # ── All strategies failed ─────────────────────────────────────────────
        reason = self._diagnose_failure(cleaned_response)
        logger.warning(f"ResponseParser: all strategies failed | reason={reason} | response={response[:100]!r}")
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

        tool_clean = tool.strip()

        # Hardening: Validate tool name against known registered tools & aliases
        known_tools = _get_known_tools()
        if tool_clean not in known_tools:
            logger.warning(f"ResponseParser: rejected unknown tool '{tool_clean}' via {method}")
            return None

        parameters = data.get("parameters") or data.get("params") or data.get("args") or {}
        if not isinstance(parameters, dict):
            parameters = {}

        # Tools requiring parameters must not have empty parameters
        if tool_clean in ("write_file", "read_file", "bash_exec", "create_directory", "write_files_batch") and not parameters:
            logger.warning(f"ResponseParser: {tool_clean} requires parameters but none found via {method}")
            return None

        # Reject prompt-demo placeholders in write_file
        if tool_clean == "write_file":
            content_val = parameters.get("content") or parameters.get("code") or parameters.get("body")
            if isinstance(content_val, str) and content_val.strip() in (
                "full content here", "the code string", "# full content here", "# the code string",
                "// full content here", "/* full content here */"
            ):
                logger.warning(f"ResponseParser: rejected prompt-demo placeholder in write_file: {content_val!r}")
                return None

        # Validation for write_files_batch
        if tool_clean == "write_files_batch":
            files = parameters.get("files")
            if not isinstance(files, list) or len(files) == 0:
                logger.warning(f"ResponseParser: write_files_batch requires non-empty 'files' list via {method}")
                return None
            if len(files) > 3:
                logger.warning(f"ResponseParser: write_files_batch exceeded maximum 3 files ({len(files)} files)")
                return None
            seen_paths = set()
            for entry in files:
                if not isinstance(entry, dict):
                    logger.warning(f"ResponseParser: write_files_batch invalid entry type: {type(entry)}")
                    return None
                p = entry.get("path")
                c = entry.get("content")
                if not isinstance(p, str) or not p.strip():
                    logger.warning(f"ResponseParser: write_files_batch entry missing valid 'path'")
                    return None
                if not isinstance(c, str):
                    logger.warning(f"ResponseParser: write_files_batch entry missing valid 'content' string")
                    return None
                if c.strip() in (
                    "full content here", "the code string", "# full content here", "# the code string",
                    "// full content here", "/* full content here */"
                ):
                    logger.warning(f"ResponseParser: write_files_batch rejected prompt-demo placeholder in {p}")
                    return None
                norm_p = os.path.normpath(p.strip()).replace("\\", "/")
                if norm_p in seen_paths:
                    logger.warning(f"ResponseParser: write_files_batch duplicate path '{norm_p}'")
                    return None
                seen_paths.add(norm_p)

        reasoning = str(data.get("reasoning") or data.get("thought") or data.get("reason") or "")
        explanation = str(data.get("explanation") or data.get("message") or data.get("output") or "")
        logger.debug(f"ResponseParser: success via {method} | tool={tool_clean}")
        return ParseSuccess(
            tool=tool_clean,
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
        # Find outermost complete JSON object, tracking string literals to ignore braces in content
        depth = 0
        start = -1
        in_string = False
        escape = False

        for i, char in enumerate(response):
            if in_string:
                if escape:
                    escape = False
                elif char == '\\':
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue
            elif char == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0 and start >= 0:
                    candidate = response[start:i+1]
                    try:
                        data = json.loads(candidate)
                        res = self._validate_and_build(data, "extract_first_json_object", response)
                        if res:
                            return res
                    except (json.JSONDecodeError, ValueError):
                        pass
                    start = -1  # Reset start and keep scanning for other candidates
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

        if tool_name in ("write_file", "append_file") and (not params or not params.get("content")):
            extracted = self._extract_write_file_params(response)
            if extracted:
                params = extracted

        data = {
            "tool": tool_name,
            "parameters": params,
            "reasoning": reasoning,
            "explanation": explanation,
        }
        return self._validate_and_build(data, "reconstruct_from_fragments", response)

    def _parse_tool_arguments(self, tname: str, args_raw: Any) -> dict:
        """Parse tool call arguments string robustly, handling unescaped control chars, multiline strings, and HTML/CSS."""
        if isinstance(args_raw, dict):
            return args_raw
        if not isinstance(args_raw, str) or not args_raw.strip():
            return {}

        # 1. Standard json.loads with strict=False (allows literal newlines/tabs inside strings)
        try:
            data = json.loads(args_raw, strict=False)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        # 2. Clean control characters and try again
        cleaned = _clean_json_string(args_raw)
        try:
            data = json.loads(cleaned, strict=False)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        # 3. Repair broken JSON
        repaired = _repair_broken_json(args_raw)
        try:
            data = json.loads(repaired, strict=False)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        # 4. Regex extraction for write_file / append_file
        if tname in ("write_file", "append_file"):
            extracted = self._extract_write_file_params(args_raw)
            if extracted:
                return extracted

        return {}

    def _extract_write_file_params(self, raw: str) -> Optional[dict]:
        """Extract path and content parameters when json.loads fails on complex multiline payloads."""
        path_match = re.search(r'["\'](?:path|file_path)["\']\s*:\s*["\']([^"\']+)["\']', raw)
        if not path_match:
            return None
        path = path_match.group(1).strip()

        # Find start of "content": "
        m_content = re.search(r'["\']content["\']\s*:\s*["\']', raw)
        if not m_content:
            return None
        start_pos = m_content.end()
        sub = raw[start_pos:]

        # Case 1: HTML document inside content string
        if "<!DOCTYPE" in sub or "<html" in sub:
            end_html = sub.rfind("</html>")
            if end_html != -1:
                content_str = sub[:end_html + len("</html>")]
                content_str = content_str.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
                return {"path": path, "content": content_str}

        # Case 2: Content preceded by closing quote before explanation/reasoning
        expl_idx = sub.rfind('"explanation"')
        if expl_idx == -1:
            expl_idx = sub.rfind('"reasoning"')

        if expl_idx != -1:
            prefix = sub[:expl_idx].rstrip()
            if prefix.endswith(","):
                prefix = prefix[:-1].rstrip()
            if prefix.endswith("}"):
                prefix = prefix[:-1].rstrip()
            if prefix.endswith('"'):
                content_str = prefix[:-1]
                content_str = content_str.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
                return {"path": path, "content": content_str}

        # Case 3: Fallback from the end of the string
        last_brace = sub.rfind("}")
        if last_brace != -1:
            prefix = sub[:last_brace].rstrip()
            if prefix.endswith("}"):
                prefix = prefix[:-1].rstrip()
            if prefix.endswith('"'):
                content_str = prefix[:-1]
                content_str = content_str.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
                return {"path": path, "content": content_str}

        val_end = sub.rfind('"')
        if val_end > 0:
            content_str = sub[:val_end]
            content_str = content_str.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
            return {"path": path, "content": content_str}

        return None

    def _try_extract_code_block(self, response: str) -> Optional[ParseSuccess]:
        """Extract markdown code block or raw HTML and target path if present."""
        code_match = re.search(r'```(?:python|py|html|css|js|javascript|json|sh|bash)?\s*\n(.*?)\n```', response, re.DOTALL)
        if not code_match:
            # Also check for raw HTML documents without code fences
            stripped = response.strip()
            if stripped.startswith("<!DOCTYPE") or stripped.startswith("<html"):
                path_match = re.search(r'["\']?path["\']?\s*:\s*["\']([^"\']+\.[a-zA-Z0-9_]+)["\']', response)
                path = path_match.group(1) if path_match else ""
                if not path:
                    file_match = re.search(r'(?:file|path|module|in|called|named|create)\s+[`"\']?([a-zA-Z0-9_\-\.\/]+\.(?:html|htm))[`"\']?', response, re.IGNORECASE)
                    path = file_match.group(1) if file_match else "index.html"
                return ParseSuccess(
                    tool="write_file",
                    parameters={"path": path, "content": stripped},
                    reasoning="Extracted raw HTML document from model response.",
                    explanation=f"Creating HTML file {path}.",
                    method_used="extract_code_block",
                    raw_response=response,
                )
            return None
        code_content = code_match.group(1).strip()
        if not code_content or len(code_content) < 10:
            return None

        if code_content in ("full content here", "the code string", "# full content here", "# the code string"):
            logger.warning("ResponseParser: extract_code_block rejected demo placeholder")
            return None

        # Look for target file path in response
        path = ""
        path_match = re.search(r'["\']?path["\']?\s*:\s*["\']([^"\']+\.[a-zA-Z0-9_]+)["\']', response)
        if path_match:
            path = path_match.group(1)
        else:
            file_match = re.search(r'(?:file|path|module|in|called|named|create)\s+[`"\']?([a-zA-Z0-9_\-\.\/]+\.[a-zA-Z0-9_]+)[`"\']?', response, re.IGNORECASE)
            if file_match:
                path = file_match.group(1)

        if path and not path.startswith("http"):
            logger.info(f"ResponseParser: extracted code block for path '{path}'")
            return ParseSuccess(
                tool="write_file",
                parameters={"path": path, "content": code_content},
                reasoning="Extracted code block from reasoning/response.",
                explanation=f"Creating file {path} with extracted implementation.",
                method_used="extract_code_block",
                raw_response=response
            )
        return None

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
            # Tools requiring parameters must NEVER be returned with empty parameters
            if tool_name in ("write_file", "read_file", "bash_exec", "create_directory", "write_files_batch"):
                continue

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

        # Check if valid JSON was parsed but contained an unknown/rejected tool
        try:
            cleaned = re.sub(r'^```(?:json)?\s*\n?', '', r)
            cleaned = re.sub(r'\n?```\s*$', '', cleaned).strip()
            data = json.loads(cleaned)
            if isinstance(data, dict):
                tool = data.get("tool") or data.get("action") or data.get("tool_name")
                if tool and isinstance(tool, str):
                    tool_clean = tool.strip()
                    if tool_clean not in _get_known_tools():
                        return f"unknown_tool_rejected:{tool_clean}"
        except Exception:
            pass

        if r.startswith(("I ", "Sure", "Of course", "I'll", "I will", "Let me", "To ")):
            return "model_responded_with_plain_text_no_json"
        if r.count("{") == 0:
            return "no_json_braces_found_at_all"
        if r.count('"tool"') == 0 and r.count("'tool'") == 0 and r.count('"action"') == 0 and r.count("'action'") == 0:
            return "json_found_but_no_tool_key"
        if r.count('"') < 4 and r.count("'") < 4:
            return "insufficient_json_quotes"
        return "json_malformed_unparseable"
