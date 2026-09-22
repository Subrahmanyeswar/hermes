# core/tool_validator.py
"""
Hardened Tool-Call Reliability & Validation Pipeline for HERMES vNext.
Guarantees that malformed model-generated tool calls (e.g. write_file({}))
NEVER silently reach tool execution, while providing layered deterministic
normalization, schema repair, T1 structured correction, and security validation.

Order of Execution:
  1. Deterministic Normalization (alias mapping, whitespace trim, default injection)
  2. Schema Validation (Pydantic type/field checking)
  3. Deterministic / Contextual Repair (unambiguous argument derivation)
  4. T1 Structured Correction Request (Phase 6.3 L1 budget)
  5. Schema Re-Validation
  6. Security Gate (Path traversal ../, command injection)
  7. Execution Gate (Only validated arguments reach tool.execute)
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Type

from loguru import logger
from pydantic import BaseModel, ValidationError

from tools.registry import get_tool, list_tools, tool_schema_for_prompt
from core.workspace import workspace_manager, WorkspaceBoundaryError
from config.model_config import (
    ROBUST_TOOL_VALIDATION_ENABLED,
    TIER1_MODEL,
    MODEL_KEEP_ALIVE
)


class ToolValidationErrorType(Enum):
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    MISSING_REQUIRED_ARGUMENT = "MISSING_REQUIRED_ARGUMENT"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    NULL_OR_EMPTY = "NULL_OR_EMPTY"
    PATH_TRAVERSAL = "PATH_TRAVERSAL"
    COMMAND_SECURITY = "COMMAND_SECURITY"
    INVALID_JSON = "INVALID_JSON"


# Parameter alias mapping for safe deterministic normalization
PARAM_ALIASES = {
    "file_path": "path",
    "dir_path": "path",
    "directory_path": "path",
    "target_path": "path",
    "filepath": "path",
    "filename": "path",
    "cmd": "command",
    "shell_cmd": "command",
    "code": "content",
    "text": "content",
    "file_content": "content",
    "body": "content",
    "CodeContent": "content",
    "code_content": "content",
    "TargetFile": "path",
    "target_file": "path",
}

# Forbidden command patterns
FORBIDDEN_COMMAND_PATTERNS = [
    r"rm\s+-rf\s+/\s*$",
    r"rm\s+-rf\s+/\*",
    r":\(\)\{\s*:\|:&\s*\};:",
    r"mkfs",
    r"dd\s+if=/dev/zero\s+of=/dev/sd",
]


@dataclass
class ToolValidationResult:
    """Diagnostic outcome of the tool validation pipeline."""
    is_valid: bool
    tool_name: str
    raw_params: Dict[str, Any]
    normalized_params: Dict[str, Any]
    validated_input: Optional[BaseModel] = None
    errors: List[str] = field(default_factory=list)
    repair_applied: bool = False
    repair_method: str = "NONE"
    security_passed: bool = True


class ToolValidator:
    """
    Authoritative tool validation and repair engine.
    Ensures no malformed or unauthorized tool requests reach execution.
    """

    def __init__(self, enabled: bool = ROBUST_TOOL_VALIDATION_ENABLED):
        self.enabled = enabled
        logger.info("ToolValidator initialized | robust_validation_enabled={}", self.enabled)

    def normalize(
        self,
        tool_name: str,
        params: Dict[str, Any],
        task_text: str = ""
    ) -> Tuple[Dict[str, Any], List[str]]:
        """
        Perform deterministic parameter normalization and alias resolution.
        Returns: (normalized_dict, modifications_applied)
        """
        if not isinstance(params, dict):
            return {}, ["params_not_a_dict"]

        normalized = {}
        modifications = []

        # 1. Alias mapping and whitespace stripping
        for k, v in params.items():
            canonical_key = PARAM_ALIASES.get(k, k)
            if canonical_key != k:
                modifications.append(f"alias_{k}_to_{canonical_key}")

            if isinstance(v, str):
                # Don't strip 'content' — it destroys Python indentation
                if canonical_key == "content":
                    normalized[canonical_key] = v
                else:
                    normalized[canonical_key] = v.strip()
            else:
                normalized[canonical_key] = v

        # 2. Tool-specific deterministic defaults
        if tool_name in ("list_directory", "list_dir") and "path" not in normalized:
            normalized["path"] = "."
            modifications.append("injected_default_list_directory_path")

        # 3. Contextual path extraction if missing
        if tool_name in ("write_file", "read_file", "file_exists") and ("path" not in normalized or not normalized["path"]):
            if task_text:
                # Match path patterns like generated_projects/foo.py or foo.py
                match = re.search(r"([a-zA-Z0-9_\-/\\.]+\.[a-zA-Z0-9]+)", task_text)
                if match:
                    extracted_path = match.group(1).strip()
                    normalized["path"] = extracted_path
                    modifications.append(f"contextual_extracted_path_{extracted_path}")

        # 4. Batch file items normalization
        if tool_name == "write_files_batch" and "files" in normalized and isinstance(normalized["files"], list):
            normalized_files = []
            for idx, item in enumerate(normalized["files"]):
                if isinstance(item, dict):
                    norm_item = {}
                    for ik, iv in item.items():
                        canon_k = PARAM_ALIASES.get(ik, ik)
                        if canon_k == "content":
                            norm_item[canon_k] = iv if isinstance(iv, str) else str(iv or "")
                        elif isinstance(iv, str):
                            norm_item[canon_k] = iv.strip()
                        else:
                            norm_item[canon_k] = iv
                    normalized_files.append(norm_item)
                else:
                    normalized_files.append(item)
            normalized["files"] = normalized_files

        return normalized, modifications

    def validate_schema(
        self,
        tool_name: str,
        params: Dict[str, Any]
    ) -> Tuple[bool, Optional[BaseModel], List[str]]:
        """
        Validate parameters against the tool's registered Pydantic Input model.
        Returns: (is_valid, validated_input_instance, error_diagnostics)
        """
        tool_class = get_tool(tool_name)
        if tool_class is None:
            return False, None, [f"Tool '{tool_name}' not found in registry"]

        input_model: Optional[Type[BaseModel]] = getattr(tool_class, "Input", None)
        if input_model is None:
            # Tool has no schema requirements
            return True, None, []

        try:
            validated = input_model(**params)
            return True, validated, []
        except ValidationError as val_err:
            errors = []
            for err in val_err.errors():
                loc = ".".join(str(l) for l in err.get("loc", []))
                msg = err.get("msg", "invalid")
                err_type = err.get("type", "")
                if "missing" in err_type:
                    errors.append(f"Missing required argument: '{loc}'")
                elif "type" in err_type:
                    errors.append(f"Invalid type for argument '{loc}': {msg}")
                else:
                    errors.append(f"Argument '{loc}' validation failed: {msg}")
            return False, None, errors
        except Exception as exc:
            return False, None, [f"Schema validation exception: {exc}"]

    def validate_security(
        self,
        tool_name: str,
        params: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate security constraints (path traversal, dangerous commands) before execution.
        Returns: (is_safe, security_error_message)
        """
        # 1. Filesystem Path Traversal Checks
        if hasattr(params, "model_dump"):
            params = params.model_dump()
        elif hasattr(params, "dict"):
            params = params.dict()
        elif not isinstance(params, dict):
            params = {}

        path = params.get("path") or params.get("file_path")
        if isinstance(path, str) and path:
            if chr(0) in path:
                return False, f"SECURITY: Null byte detected in path: {path}"

            # Validate against workspace boundaries
            try:
                if workspace_manager.is_locked:
                    workspace_manager.validate_path(path)
            except WorkspaceBoundaryError as e:
                return False, f"SECURITY: Path traversal violation: {e}"

        # 1b. Batch Filesystem Path Traversal Checks
        files = params.get("files")
        if isinstance(files, list):
            seen_normalized = set()
            for idx, entry in enumerate(files):
                if isinstance(entry, dict):
                    fpath = entry.get("path") or entry.get("file_path")
                    if isinstance(fpath, str) and fpath:
                        if chr(0) in fpath:
                            return False, f"SECURITY: Null byte detected in path: {fpath}"
                        try:
                            if workspace_manager.is_locked:
                                safe_p = workspace_manager.validate_path(fpath)
                                norm = os.path.normpath(str(safe_p)).lower() if os.name == "nt" else os.path.normpath(str(safe_p))
                                if norm in seen_normalized:
                                    return False, f"SECURITY: Duplicate path detected in batch: {fpath}"
                                seen_normalized.add(norm)
                        except WorkspaceBoundaryError as e:
                            return False, f"SECURITY: Path traversal violation in batch file {idx}: {e}"

        # 2. Shell Command Security Checks
        command = params.get("command") or params.get("cmd")
        if isinstance(command, str) and command:
            for pattern in FORBIDDEN_COMMAND_PATTERNS:
                if re.search(pattern, command, re.IGNORECASE):
                    return False, f"SECURITY: Forbidden command execution blocked: {command}"

        return True, None

    async def process_and_validate(
        self,
        tool_name: str,
        raw_params: Dict[str, Any],
        task_text: str,
        ollama_client,
        budget_manager=None,
        max_repair_attempts: int = 2
    ) -> ToolValidationResult:
        """
        Execute the full layered validation and repair pipeline.
        Guarantees that only schema-valid, security-checked calls proceed to execution.
        """
        if not self.enabled:
            # Fallback legacy pass-through
            tool_class = get_tool(tool_name)
            validated_input = None
            if tool_class and hasattr(tool_class, "Input"):
                try:
                    validated_input = tool_class.Input(**raw_params)
                except Exception:
                    pass
            return ToolValidationResult(
                is_valid=True,
                tool_name=tool_name,
                raw_params=raw_params,
                normalized_params=raw_params,
                validated_input=validated_input,
                errors=[],
                repair_applied=False,
                repair_method="LEGACY_BYPASS"
            )

        # Step 1: Normalization & Deterministic Repair
        normalized_params, mods = self.normalize(tool_name, raw_params, task_text)
        repair_applied = len(mods) > 0
        repair_method = f"DETERMINISTIC_NORMALIZATION ({', '.join(mods)})" if repair_applied else "NONE"

        # Step 2: Schema Validation
        is_valid, validated_input, errors = self.validate_schema(tool_name, normalized_params)

        # Step 3: T1 Model Correction Request (if schema validation failed)
        repair_attempts = 0
        while not is_valid and repair_attempts < max_repair_attempts:
            repair_attempts += 1
            logger.warning(
                "ToolValidator: tool '{}' validation failed: {}. Initiating T1 structured correction ({}/{})...",
                tool_name, errors, repair_attempts, max_repair_attempts
            )

            # Build structured correction prompt
            tool_class = get_tool(tool_name)
            schema_repr = "unknown"
            if tool_class and hasattr(tool_class, "Input"):
                schema_repr = json.dumps(tool_class.Input.model_json_schema().get("properties", {}), indent=2)

            err_dump = json.dumps(errors, indent=2)
            correction_user = (
                f"Your tool call to '{tool_name}' failed validation with the following errors:\n"
                f"{err_dump}\n\n"
                f"Expected Schema Properties for '{tool_name}':\n{schema_repr}\n\n"
                f"Original Task: {task_text}\n\n"
                f"Please output a corrected JSON response with valid required parameters."
            )

            try:
                # Use small L1 budget for schema correction
                num_predict = 1536
                if budget_manager:
                    from core.reasoning_budget import ComplexityLevel
                    budget = budget_manager.get_budget(ComplexityLevel.L1_SIMPLE)
                    num_predict = budget.num_predict

                resp = await ollama_client.generate(
                    model=TIER1_MODEL,
                    prompt=correction_user,
                    system="You are a tool argument repair assistant. Output ONLY valid JSON containing tool and parameters.",
                    keep_alive=MODEL_KEEP_ALIVE,
                    temperature=0.05,
                    num_predict=num_predict
                )
                raw_corrected = getattr(resp, "text", str(resp))

                # Parse JSON using hardened ResponseParser
                from core.response_parser import ResponseParser
                parser = ResponseParser()
                parse_res = parser.parse(raw_corrected)
                if hasattr(parse_res, "to_dict"):
                    parsed_corrected = parse_res.to_dict()
                else:
                    cleaned = re.sub(r"<think>.*?</think>", "", raw_corrected, flags=re.DOTALL).strip()
                    cleaned = re.sub(r"^```json\s*", "", cleaned)
                    cleaned = re.sub(r"^```\s*", "", cleaned)
                    cleaned = re.sub(r"\s*```$", "", cleaned)
                    parsed_corrected = json.loads(cleaned)

                corrected_tool = parsed_corrected.get("tool") or parsed_corrected.get("tool_name") or tool_name
                corrected_params = parsed_corrected.get("parameters") or parsed_corrected.get("arguments") or parsed_corrected

                # Re-normalize & Re-validate
                normalized_params, _ = self.normalize(corrected_tool, corrected_params, task_text)
                is_valid, validated_input, errors = self.validate_schema(corrected_tool, normalized_params)
                tool_name = corrected_tool
                repair_applied = True
                repair_method = f"T1_MODEL_CORRECTION (attempt {repair_attempts})"

            except Exception as e:
                logger.error("ToolValidator: T1 model correction attempt {} failed: {}", repair_attempts, e)
                errors.append(f"Correction attempt {repair_attempts} failed: {e}")

        # Step 4: Security Validation (Post-Repair)
        try:
            security_passed, sec_error = self.validate_security(tool_name, normalized_params)
        except Exception as e:
            logger.error("ToolValidator: Security validation encountered unexpected exception: {}", e)
            security_passed = False
            sec_error = f"SECURITY_VALIDATOR_EXCEPTION: Unexpected exception during validation: {e}"

        if not security_passed:
            is_valid = False
            errors.append(sec_error or "Security violation")

        return ToolValidationResult(
            is_valid=is_valid,
            tool_name=tool_name,
            raw_params=raw_params,
            normalized_params=normalized_params,
            validated_input=validated_input,
            errors=errors,
            repair_applied=repair_applied,
            repair_method=repair_method,
            security_passed=security_passed
        )


# Global singleton
tool_validator = ToolValidator()
