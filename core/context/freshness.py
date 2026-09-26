# core/context/freshness.py
"""
Context Freshness and Filesystem Truth Checker for HERMES 2.x Context Engine.
Bridges with FileIdentityCache (Prompt 6) to guarantee stale code snippets and
superseded observations are never presented as current truth.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.context.models import ActiveFileSnippet, ContextFreshness, ContextItem
from tools.platform.file_identity import FileIdentity, FileIdentityCache, file_identity_cache


class FreshnessChecker:
    """
    Validates freshness of file snippets, observations, and memory items
    against the actual filesystem and authoritative state.
    """

    def __init__(self, identity_cache: Optional[FileIdentityCache] = None) -> None:
        self.identity_cache = identity_cache or file_identity_cache

    def check_file_freshness(
        self,
        file_path: Path | str,
        expected_identity: Optional[FileIdentity] = None,
        expected_hash: Optional[str] = None,
    ) -> ContextFreshness:
        """
        Check whether a file on disk has changed compared to recorded identity snapshot.
        """
        p = Path(file_path).resolve()
        if not p.exists():
            return ContextFreshness.INVALIDATED

        # If we have an expected identity snapshot, use its is_stale check
        if expected_identity is not None:
            if expected_identity.is_stale(p):
                return ContextFreshness.STALE
            return ContextFreshness.FRESH

        # If we have a cached identity from FileIdentityCache
        cached_id = self.identity_cache.get(p)
        if cached_id is not None:
            if cached_id.is_stale(p):
                return ContextFreshness.STALE
            if expected_hash and cached_id.content_hash != expected_hash:
                return ContextFreshness.STALE
            return ContextFreshness.FRESH

        # Compare directly against current file stat
        try:
            stat = p.stat()
            # If expected hash is given, compute current hash
            if expected_hash:
                import hashlib
                with open(p, "rb") as f:
                    curr_hash = hashlib.sha256(f.read()).hexdigest()
                return ContextFreshness.FRESH if curr_hash == expected_hash else ContextFreshness.STALE
            return ContextFreshness.UNKNOWN
        except Exception:
            return ContextFreshness.UNKNOWN

    def check_item_freshness(self, item: ContextItem) -> ContextFreshness:
        """
        Evaluate freshness of an individual ContextItem.
        """
        if item.freshness == ContextFreshness.INVALIDATED:
            return ContextFreshness.INVALIDATED

        prov = item.provenance
        if prov.file_path:
            freshness = self.check_file_freshness(
                file_path=prov.file_path,
                expected_identity=prov.file_identity,
                expected_hash=prov.content_hash,
            )
            item.freshness = freshness
            return freshness

        return item.freshness

    def validate_active_files(self, snippets: List[ActiveFileSnippet]) -> List[ActiveFileSnippet]:
        """
        Revalidate active file snippets against current disk state.
        Discards or marks snippets whose backing file changed.
        """
        valid: List[ActiveFileSnippet] = []
        for s in snippets:
            freshness = self.check_file_freshness(s.path, expected_hash=s.content_hash)
            if freshness == ContextFreshness.FRESH:
                valid.append(s)
            elif freshness == ContextFreshness.STALE:
                # Discard stale snippet to prevent hallucination
                pass
        return valid


# Global singleton
freshness_checker = FreshnessChecker()
