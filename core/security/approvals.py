# core/security/approvals.py
"""
HERMES 2.x - Approval Registry & Store (Prompt 13)
Tracks active grants, pending approval requests, consumption, and expiration.
"""

from __future__ import annotations

import time
import uuid
import logging
from typing import Dict, List, Optional

from core.security.enums import ApprovalScope, PermissionOutcome
from core.security.models import ActionDescriptor, ApprovalGrant, ApprovalRequest

logger = logging.getLogger("hermes.security.approvals")


class ApprovalStore:
    """
    Authoritative registry for approval grants and pending approval requests.
    Supports exact-action fingerprints, tool scopes, path prefixes, session scopes,
    bounded usage, and monotonic clock expiration.
    """

    def __init__(self, default_ttl_seconds: float = 3600.0) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._grants: Dict[str, ApprovalGrant] = {}
        self._requests: Dict[str, ApprovalRequest] = {}

    def add_grant(self, grant: ApprovalGrant) -> ApprovalGrant:
        """Register an active approval grant."""
        self._grants[grant.grant_id] = grant
        logger.debug("Registered approval grant %s for tool %s (scope: %s)", grant.grant_id, grant.tool_name, grant.scope.value)
        return grant

    def create_grant(
        self,
        scope: ApprovalScope,
        tool_name: str,
        fingerprint: Optional[str] = None,
        path_prefix: Optional[str] = None,
        session_id: Optional[str] = None,
        granted_by: str = "user",
        max_uses: int = 1,
        ttl_seconds: Optional[float] = None,
    ) -> ApprovalGrant:
        """Create and register a new grant."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        expires_at = time.time() + ttl if ttl > 0 else None
        
        grant = ApprovalGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:10]}",
            scope=scope,
            action_fingerprint=fingerprint,
            tool_name=tool_name,
            path_prefix=path_prefix,
            session_id=session_id,
            granted_by=granted_by,
            created_at=time.time(),
            expires_at=expires_at,
            max_uses=max_uses,
            remaining_uses=max_uses,
        )
        return self.add_grant(grant)

    def get_grant(self, grant_id: str) -> Optional[ApprovalGrant]:
        """Retrieve a grant by ID."""
        return self._grants.get(grant_id)

    def revoke_grant(self, grant_id: str) -> bool:
        """Revoke a specific grant."""
        grant = self._grants.get(grant_id)
        if grant:
            grant.revoked = True
            logger.info("Revoked grant %s", grant_id)
            return True
        return False

    def revoke_session(self, session_id: str) -> int:
        """Revoke all grants tied to a session."""
        count = 0
        for grant in self._grants.values():
            if grant.session_id == session_id and not grant.revoked:
                grant.revoked = True
                count += 1
        logger.info("Revoked %d grants for session %s", count, session_id)
        return count

    def find_matching_grant(
        self,
        action: ActionDescriptor,
        session_id: Optional[str] = None,
    ) -> Optional[ApprovalGrant]:
        """
        Find an active, valid grant matching the action descriptor.
        Returns the first matching grant, or None.
        """
        now = time.time()
        for grant in list(self._grants.values()):
            if not grant.can_apply():
                continue
            
            # Check expiration
            if grant.expires_at is not None and now > grant.expires_at:
                continue

            # Scope-specific matching
            if grant.scope == ApprovalScope.ONCE or grant.scope == ApprovalScope.EXACT_ACTION:
                if grant.action_fingerprint and grant.action_fingerprint == action.action_fingerprint:
                    return grant
            elif grant.scope == ApprovalScope.SESSION:
                if grant.tool_name == action.tool_name:
                    if not grant.session_id or grant.session_id == session_id:
                        return grant
            elif grant.scope == ApprovalScope.PATH_PREFIX:
                if grant.tool_name == action.tool_name and grant.path_prefix:
                    # Check if action affects a path under path_prefix
                    target_path = action.canonical_path or action.arguments.get("path") or action.arguments.get("file_path") or action.arguments.get("target")
                    if target_path and str(target_path).startswith(grant.path_prefix):
                        return grant
            elif grant.scope == ApprovalScope.COMMAND_PATTERN:
                if grant.tool_name == action.tool_name:
                    cmd = action.arguments.get("command") or action.arguments.get("cmd") or ""
                    if grant.command_pattern and grant.command_pattern in str(cmd):
                        return grant
            elif grant.scope == ApprovalScope.ALWAYS:
                if grant.tool_name == action.tool_name:
                    return grant

        return None

    def add_request(self, request: ApprovalRequest) -> ApprovalRequest:
        """Register a pending approval request."""
        self._requests[request.request_id] = request
        logger.info("Added pending approval request %s for %s", request.request_id, request.action.tool_name)
        return request

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Get pending request by ID."""
        return self._requests.get(request_id)

    def get_pending_requests(self) -> List[ApprovalRequest]:
        """List all requests awaiting user response."""
        now = time.time()
        return [r for r in self._requests.values() if not r.resolved and (r.expires_at is None or now < r.expires_at)]

    def resolve_request(
        self,
        request_id: str,
        approved: bool,
        scope: ApprovalScope = ApprovalScope.ONCE,
        max_uses: int = 1,
        resolved_by: str = "user",
        ttl_seconds: Optional[float] = None,
    ) -> Optional[ApprovalGrant]:
        """Resolve a pending approval request and optionally generate a grant."""
        request = self._requests.get(request_id)
        if not request or request.resolved:
            return None

        request.resolved = True
        request.resolved_at = time.time()
        request.approved = approved
        request.resolved_by = resolved_by

        if not approved:
            logger.info("Approval request %s was denied by %s", request_id, resolved_by)
            return None

        # Create corresponding grant
        path_prefix = None
        if scope == ApprovalScope.PATH_PREFIX:
            path_prefix = request.action.canonical_path

        grant = self.create_grant(
            scope=scope,
            tool_name=request.action.tool_name,
            fingerprint=request.action.action_fingerprint,
            path_prefix=path_prefix,
            session_id=request.session_id,
            granted_by=resolved_by,
            max_uses=max_uses if scope != ApprovalScope.ONCE else 1,
            ttl_seconds=ttl_seconds,
        )
        logger.info("Approval request %s approved; created grant %s (scope: %s)", request_id, grant.grant_id, scope.value)
        return grant

    def prune_expired(self) -> int:
        """Remove or flag expired grants and requests."""
        now = time.time()
        pruned = 0
        for gid, grant in list(self._grants.items()):
            if grant.expires_at is not None and now > grant.expires_at:
                grant.revoked = True
                pruned += 1
        return pruned

    def to_dict(self) -> Dict[str, Any]:
        return {
            "active_grants_count": sum(1 for g in self._grants.values() if g.can_apply()),
            "total_grants_count": len(self._grants),
            "pending_requests_count": len(self.get_pending_requests()),
        }
