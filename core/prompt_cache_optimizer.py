# core/prompt_cache_optimizer.py
"""
HERMES Phase 10: Prompt-Prefix Optimizer & Deterministic Tool Schema Normalizer.

Ensures:
1. Deterministic, sorted canonical tool schemas across all model requests.
2. Stable prompt prefix ordering to maximize LLM KV-cache reuse.
3. Separation of static invariant content (system role, tool contracts) from dynamic turn context.
4. Cryptographic SHA-256 fingerprinting of the cacheable prefix.
5. Invariant preservation: Never reorders conversation history or modifies tool authorizations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class PromptPrefixFingerprint:
    prefix_sha256: str
    prefix_length_bytes: int
    tool_count: int
    normalized_tool_names: List[str]


class PromptCacheOptimizer:
    """
    Normalizes tool schemas and optimizes prompt layouts for KV cache efficiency.
    """

    def __init__(self, system_role: Optional[str] = None) -> None:
        from core.prompt_builder import HERMES_ROLE
        self._system_role = system_role or HERMES_ROLE

    def normalize_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sort tool schemas deterministically by canonical name and recursively sort keys.
        Preserves all parameters, descriptions, and authorization metadata.
        """
        def _get_name(t: Dict[str, Any]) -> str:
            if "name" in t:
                return str(t["name"])
            if "type" in t and "function" in t and isinstance(t["function"], dict):
                return str(t["function"].get("name", ""))
            return ""

        sorted_tools = sorted(tools, key=_get_name)

        # Recursively ensure deterministic dictionary key ordering for JSON serialization
        def _sort_dict(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: _sort_dict(v) for k, v in sorted(obj.items())}
            if isinstance(obj, list):
                return [_sort_dict(item) for item in obj]
            return obj

        return [_sort_dict(t) for t in sorted_tools]

    def build_stable_prefix(
        self,
        tools: Optional[List[Dict[str, Any]]] = None,
        extra_system_rules: str = "",
    ) -> Tuple[str, PromptPrefixFingerprint]:
        """
        Construct the invariant prompt prefix consisting of:
        1. Fixed system role & engineering directives.
        2. Stable extra system rules (if any).
        3. Deterministically serialized tool schemas.
        """
        norm_tools = self.normalize_tools(tools or [])
        tool_names = []
        for t in norm_tools:
            name = t.get("name") or (t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else None)
            if name:
                tool_names.append(str(name))

        serialized_tools = json.dumps(norm_tools, separators=(",", ":"), ensure_ascii=True)
        
        prefix_parts = [
            "=== SYSTEM ROLE ===",
            self._system_role.strip(),
        ]
        if extra_system_rules.strip():
            prefix_parts.extend([
                "=== SYSTEM RULES ===",
                extra_system_rules.strip(),
            ])
        prefix_parts.extend([
            "=== AUTHORIZED TOOLS ===",
            serialized_tools,
            "=== END PREFIX ===",
        ])

        prefix_text = "\n\n".join(prefix_parts)
        prefix_bytes = prefix_text.encode("utf-8")
        prefix_sha256 = hashlib.sha256(prefix_bytes).hexdigest()

        fingerprint = PromptPrefixFingerprint(
            prefix_sha256=prefix_sha256,
            prefix_length_bytes=len(prefix_bytes),
            tool_count=len(norm_tools),
            normalized_tool_names=tool_names,
        )
        return prefix_text, fingerprint

    def assemble_optimized_prompt(
        self,
        tools: List[Dict[str, Any]],
        task_prompt: str,
        workspace_context: str = "",
        memory_context: str = "",
        extra_system_rules: str = "",
    ) -> Tuple[str, str, PromptPrefixFingerprint]:
        """
        Returns (full_prompt, prefix_text, fingerprint) where prefix_text is 100% stable
        across turns with identical tools and static rules.
        """
        prefix_text, fingerprint = self.build_stable_prefix(tools=tools, extra_system_rules=extra_system_rules)

        dynamic_parts = [
            "=== TASK CONTEXT ===",
            task_prompt.strip(),
        ]
        if workspace_context.strip():
            dynamic_parts.extend([
                "=== WORKSPACE CONTEXT ===",
                workspace_context.strip(),
            ])
        if memory_context.strip():
            dynamic_parts.extend([
                "=== MEMORY CONTEXT ===",
                memory_context.strip(),
            ])

        full_prompt = f"{prefix_text}\n\n" + "\n\n".join(dynamic_parts)
        return full_prompt, prefix_text, fingerprint


prompt_cache_optimizer = PromptCacheOptimizer()
