# tools/platform/validator.py
"""
Hardened Tool Validation Engine for HERMES 2.x Tool Platform.
Evolves core/tool_validator.py with schema checking, alias normalization,
workspace boundary enforcement, and shell security gates.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.workspace import WorkspaceManager, WorkspaceBoundaryError
from core.tool_validator import PARAM_ALIASES, FORBIDDEN_COMMAND_PATTERNS
from tools.platform.specs import ToolSpec
from tools.platform.errors import ToolError, ToolErrorCode, ErrorGuidance
from tools.security import check_all_gates


class Validator:
    """
    Validates proposed tool requests before permission evaluation and physical execution.
    """

    @classmethod
    def normalize_arguments(cls, raw_args: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize parameter aliases to canonical names."""
        normalized: Dict[str, Any] = {}
        for key, val in raw_args.items():
            canonical_key = PARAM_ALIASES.get(key, key)
            normalized[canonical_key] = val
        return normalized

    @classmethod
    def validate(
        cls,
        spec: ToolSpec,
        raw_args: Dict[str, Any],
        workspace: Optional[WorkspaceManager] = None,
    ) -> Tuple[bool, Optional[ToolError], Dict[str, Any]]:
        """
        Validate tool call arguments against schema, workspace boundary, and security rules.
        Returns: (is_valid, tool_error, normalized_args)
        """
        norm_args = cls.normalize_arguments(raw_args)

        # 1. Required parameters check
        schema_props = spec.schema.parameters.get("properties", {})
        required_fields = spec.schema.required or spec.schema.parameters.get("required", [])

        missing = [f for f in required_fields if f not in norm_args or norm_args[f] is None]
        if missing:
            err = ToolError(
                code=ToolErrorCode.INVALID_ARGUMENT,
                message=f"Missing required parameter(s): {', '.join(missing)}",
                what_failed=f"Validation for {spec.canonical_name}",
                why_it_failed=f"Required parameter(s) '{', '.join(missing)}' were not provided.",
                actionable_guidance=ErrorGuidance.format_guidance(
                    ToolErrorCode.INVALID_ARGUMENT,
                    spec.canonical_name,
                    {"missing": missing},
                ),
                details={"missing": missing},
            )
            return False, err, norm_args

        # 2. Workspace boundary & path traversal check for filesystem tools
        path_keys = ("path", "target", "file", "dest", "destination")
        for pk in path_keys:
            if pk in norm_args and isinstance(norm_args[pk], str) and norm_args[pk].strip():
                raw_path = norm_args[pk].strip()

                # Check explicit .. traversal
                parts = Path(raw_path).parts
                if ".." in parts:
                    err = ToolError(
                        code=ToolErrorCode.PATH_OUTSIDE_WORKSPACE,
                        message=f"Path traversal blocked: relative '..' navigation not allowed: '{raw_path}'",
                        what_failed=f"Path validation for {spec.canonical_name}",
                        why_it_failed=f"Relative '..' segment is prohibited for workspace security.",
                        actionable_guidance=ErrorGuidance.format_guidance(
                            ToolErrorCode.PATH_OUTSIDE_WORKSPACE,
                            spec.canonical_name,
                            {"path": raw_path},
                        ),
                        details={"path": raw_path},
                    )
                    return False, err, norm_args

                # Workspace containment check if locked
                if workspace and workspace.is_locked:
                    try:
                        workspace.validate_path(raw_path)
                    except WorkspaceBoundaryError as wb_err:
                        err = ToolError(
                            code=ToolErrorCode.PATH_OUTSIDE_WORKSPACE,
                            message=str(wb_err),
                            what_failed=f"Workspace containment for {spec.canonical_name}",
                            why_it_failed=f"Path '{raw_path}' resolves outside workspace root.",
                            actionable_guidance=ErrorGuidance.format_guidance(
                                ToolErrorCode.PATH_OUTSIDE_WORKSPACE,
                                spec.canonical_name,
                                {"path": raw_path},
                            ),
                            details={"path": raw_path},
                        )
                        return False, err, norm_args

        # 3. Security gates for shell execution
        if spec.category == "shell" or spec.canonical_name in ("shell.bash", "bash_exec"):
            cmd = norm_args.get("command", "")
            if isinstance(cmd, str):
                # 3a. Forbidden patterns
                for pattern in FORBIDDEN_COMMAND_PATTERNS:
                    if re.search(pattern, cmd, re.IGNORECASE):
                        err = ToolError(
                            code=ToolErrorCode.COMMAND_REJECTED,
                            message=f"Command matches destructive pattern '{pattern}': {cmd[:80]}",
                            what_failed=f"Security gate evaluation for {spec.canonical_name}",
                            why_it_failed="Command is classified as dangerous/forbidden.",
                            actionable_guidance=ErrorGuidance.format_guidance(
                                ToolErrorCode.COMMAND_REJECTED,
                                spec.canonical_name,
                                {"reason": "Destructive system modification"},
                            ),
                            details={"command": cmd},
                        )
                        return False, err, norm_args

                # 3b. 15 Security gates from tools/security.py
                gates_passed, gate_reason = check_all_gates(cmd)
                if not gates_passed:
                    err = ToolError(
                        code=ToolErrorCode.COMMAND_REJECTED,
                        message=gate_reason,
                        what_failed=f"Shell security gate for {spec.canonical_name}",
                        why_it_failed=gate_reason,
                        actionable_guidance=ErrorGuidance.format_guidance(
                            ToolErrorCode.COMMAND_REJECTED,
                            spec.canonical_name,
                            {"reason": gate_reason},
                        ),
                        details={"command": cmd},
                    )
                    return False, err, norm_args

        # 4. Input model validation if implementation provides Pydantic schema
        if spec.implementation_cls is not None:
            input_model = getattr(spec.implementation_cls, "Input", getattr(spec.implementation_cls, "input_model", None))
            if input_model is not None:
                try:
                    # Validate against Pydantic schema
                    validated_obj = input_model(**norm_args)
                    norm_args = validated_obj.model_dump() if hasattr(validated_obj, "model_dump") else validated_obj.dict()
                except Exception as pydantic_err:
                    err = ToolError(
                        code=ToolErrorCode.INVALID_ARGUMENT,
                        message=f"Schema validation error: {pydantic_err}",
                        what_failed=f"Parameter typing for {spec.canonical_name}",
                        why_it_failed=str(pydantic_err),
                        actionable_guidance="Check parameter types and constraints in tool schema.",
                        details={"error": str(pydantic_err)},
                    )
                    return False, err, norm_args

        return True, None, norm_args
