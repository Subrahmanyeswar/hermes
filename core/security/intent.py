# core/security/intent.py
"""
User Intent and Authorization Scope Representation for HERMES 2.x.
Ensures that autonomous actions remain grounded in explicit user intent
rather than unconstrained inferred goals.
"""

from __future__ import annotations

import re
from typing import List, Optional

from core.security.models import UserIntent


class IntentAnalyzer:
    """
    Extracts explicit authorization boundaries and constraints from user messages.
    """

    @classmethod
    def from_user_prompt(cls, prompt: str) -> UserIntent:
        """Parse user prompt into an initial UserIntent structure."""
        text = prompt.strip()
        lower = text.lower()

        authorized_scope: List[str] = ["workspace"]
        prohibited_operations: List[str] = []
        explicit_constraints: List[str] = []

        # Check for explicit prohibitions
        if "don't touch" in lower or "do not touch" in lower or "do not modify" in lower:
            explicit_constraints.append("protect_user_files")
        if "delete" in lower and ("do not" in lower or "don't" in lower or "avoid" in lower or "no" in lower):
            prohibited_operations.append("delete")
        if "network" in lower and ("avoid" in lower or "no" in lower or "offline" in lower or "do not" in lower or "don't" in lower):
            prohibited_operations.append("network")
        if "read only" in lower or "readonly" in lower:
            prohibited_operations.append("write")
            prohibited_operations.append("shell")

        # Ambiguous destructive cleanup requests (e.g., "clean up my branches")
        if "clean" in lower and "branch" in lower:
            # Inspection allowed, but destructive branch deletion requires explicit confirmation
            prohibited_operations.append("git_force_delete")

        return UserIntent(
            requested_goal=text[:300],
            raw_prompt=text,
            authorized_scope=authorized_scope,
            explicit_constraints=explicit_constraints,
            prohibited_operations=prohibited_operations,
            confidence=0.9 if explicit_constraints else 0.7,
            source_messages=[text],
        )
