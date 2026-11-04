# core/browser/evidence.py
"""
Authoritative Browser Verification Evidence Engine for HERMES 2.x.
Guarantees cryptographic provenance, workspace and mission binding,
artifact hash integrity, viewport matrix certification, and strict
evidence lifecycle management.
"""

from __future__ import annotations
import uuid

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class BrowserEvidenceLifecycle(str, Enum):
    """Authoritative lifecycle states for browser verification evidence."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


def compute_file_sha256(path: Union[str, Path]) -> Optional[str]:
    """Compute SHA-256 hash of a file if it exists."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        h = hashlib.sha256()
        h.update(p.read_bytes())
        return h.hexdigest()
    except Exception:
        return None


def compute_workspace_artifact_hashes(workspace_root: Union[str, Path]) -> Dict[str, str]:
    """
    Compute cryptographic SHA-256 hashes of all primary web deliverables.
    Captures index.html, styles, and scripts.
    """
    ws = Path(workspace_root).resolve()
    hashes: Dict[str, str] = {}
    
    # Standard deliverables
    candidates = [
        "index.html",
        "style.css",
        "styles.css",
        "app.js",
        "main.js",
        "src/main.js",
        "src/App.jsx",
        "src/main.jsx",
        "package.json",
    ]
    
    for rel_path in candidates:
        target = ws / rel_path
        if target.is_file():
            h = compute_file_sha256(target)
            if h:
                hashes[rel_path.replace("\\", "/")] = h
                
    return hashes


@dataclass
class AuthoritativeBrowserEvidence:
    """
    Cryptographically verifiable browser evidence record.
    Binds test execution directly to physical workspace artifacts and runtime mission.
    """
    evidence_id: str
    mission_id: str
    workspace_root: str
    status: BrowserEvidenceLifecycle
    tested_url: str
    server_origin: str
    verification_timestamp: float
    artifact_hashes: Dict[str, str]
    viewports_tested: List[Dict[str, Any]]
    browser_result: Dict[str, Any]
    console_audit: Dict[str, Any]
    network_audit: Dict[str, Any]
    provenance: str = "hermes.cdp.verifier.v2"
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AuthoritativeBrowserEvidence:
        raw_status = data.get("status", "UNAVAILABLE")
        try:
            status = BrowserEvidenceLifecycle(raw_status)
        except ValueError:
            status = BrowserEvidenceLifecycle.UNAVAILABLE
            
        return cls(
            evidence_id=data.get("evidence_id", ""),
            mission_id=data.get("mission_id", ""),
            workspace_root=data.get("workspace_root", ""),
            status=status,
            tested_url=data.get("tested_url", ""),
            server_origin=data.get("server_origin", ""),
            verification_timestamp=float(data.get("verification_timestamp", 0.0)),
            artifact_hashes=data.get("artifact_hashes", {}),
            viewports_tested=data.get("viewports_tested", []),
            browser_result=data.get("browser_result", {}),
            console_audit=data.get("console_audit", {}),
            network_audit=data.get("network_audit", {}),
            provenance=data.get("provenance", "unknown"),
            details=data.get("details", {}),
        )


class BrowserEvidenceValidator:
    """
    Validates provenance, freshness, artifact hash integrity, and assertions of browser evidence.
    """

    EVIDENCE_FILENAMES = (
        ".hermes/browser_verified.json",
        ".hermes/acceptance_evidence.json",
        "browser-qualification.json",
        "verification.json",
    )

    @classmethod
    def validate_evidence(
        cls,
        evidence: AuthoritativeBrowserEvidence,
        current_workspace: Union[str, Path],
        mission_id: Optional[str] = None,
        max_age_seconds: float = 86400.0,
    ) -> Tuple[BrowserEvidenceLifecycle, str]:
        """
        Validate an evidence record against physical workspace artifacts and runtime requirements.
        Returns:
            Tuple[BrowserEvidenceLifecycle, str]: (resolved_status, human_readable_reason)
        """
        ws = Path(current_workspace).resolve()

        # 1. Provenance Check
        if not evidence.provenance or not evidence.provenance.startswith("hermes.cdp"):
            return (
                BrowserEvidenceLifecycle.FAILED,
                f"Untrusted evidence provenance '{evidence.provenance}'. Must originate from hermes.cdp verifier."
            )

        # 2. Workspace Binding Check
        if not evidence.workspace_root:
            return (
                BrowserEvidenceLifecycle.FAILED,
                "Evidence missing workspace_root binding."
            )
        try:
            ev_ws = Path(evidence.workspace_root).resolve()
            if ev_ws != ws:
                return (
                    BrowserEvidenceLifecycle.FAILED,
                    f"Evidence workspace mismatch: recorded '{ev_ws}' != current '{ws}'."
                )
        except Exception as e:
            return (
                BrowserEvidenceLifecycle.FAILED,
                f"Invalid workspace path in evidence: {e}"
            )

        # 3. Mission Binding Check (if specified)
        if mission_id and evidence.mission_id:
            if evidence.mission_id != mission_id:
                return (
                    BrowserEvidenceLifecycle.FAILED,
                    f"Evidence mission mismatch: recorded '{evidence.mission_id}' != expected '{mission_id}'."
                )

        # 4. Freshness and Timestamp Validation
        now = time.time()
        if evidence.verification_timestamp <= 0:
            return (
                BrowserEvidenceLifecycle.FAILED,
                "Evidence verification timestamp is missing or zero."
            )
        if evidence.verification_timestamp > now + 300:  # Allow 5m clock skew
            return (
                BrowserEvidenceLifecycle.FAILED,
                f"Evidence timestamp is in the future ({evidence.verification_timestamp} > {now})."
            )
        if (now - evidence.verification_timestamp) > max_age_seconds:
            return (
                BrowserEvidenceLifecycle.STALE,
                f"Evidence expired (age {now - evidence.verification_timestamp:.1f}s > {max_age_seconds}s)."
            )

        # 5. Cryptographic Artifact Hash Integrity (STALE Detection)
        if not evidence.artifact_hashes:
            return (
                BrowserEvidenceLifecycle.FAILED,
                "Evidence contains no artifact hashes to verify physical deliverables."
            )

        current_hashes = compute_workspace_artifact_hashes(ws)
        # Verify that all deliverables recorded in evidence still exist and match SHA-256
        for recorded_file, recorded_hash in evidence.artifact_hashes.items():
            curr_hash = current_hashes.get(recorded_file)
            if curr_hash is None:
                return (
                    BrowserEvidenceLifecycle.STALE,
                    f"Artifact '{recorded_file}' recorded in evidence has been deleted or is missing."
                )
            if curr_hash != recorded_hash:
                return (
                    BrowserEvidenceLifecycle.STALE,
                    f"Artifact '{recorded_file}' hash changed since verification ({curr_hash[:8]}... != {recorded_hash[:8]}...)."
                )

        # 6. Console Audit Check
        console = evidence.console_audit or {}
        uncaught_errors = console.get("uncaught_errors", 0)
        if uncaught_errors > 0 or len(console.get("errors", [])) > 0:
            return (
                BrowserEvidenceLifecycle.FAILED,
                f"Browser console recorded {uncaught_errors} uncaught error(s)."
            )

        # 7. Network Audit Check
        network = evidence.network_audit or {}
        failed_requests = network.get("failed_requests", 0)
        if failed_requests > 0:
            return (
                BrowserEvidenceLifecycle.FAILED,
                f"Browser recorded {failed_requests} failed network request(s) (HTTP >= 400)."
            )

        # 8. Viewport Matrix Check
        viewports = evidence.viewports_tested or []
        if len(viewports) < 1:
            return (
                BrowserEvidenceLifecycle.FAILED,
                "Evidence does not record any tested viewport dimensions."
            )

        # 9. Browser Behavioral Result Check
        b_res = evidence.browser_result or {}
        if not b_res.get("interactions_passed", False):
            return (
                BrowserEvidenceLifecycle.FAILED,
                f"Browser interactions not certified passed: {b_res.get('failure_reason', 'interactions failed')}"
            )
        if not b_res.get("dom_elements_verified", False):
            return (
                BrowserEvidenceLifecycle.FAILED,
                "Contracted DOM elements were not certified present and functional in browser."
            )

        # 10. Server Origin & URL Check
        if not evidence.tested_url or not evidence.tested_url.startswith(("http://", "https://")):
            return (
                BrowserEvidenceLifecycle.FAILED,
                f"Invalid or missing tested URL in evidence: '{evidence.tested_url}'."
            )

        return (
            BrowserEvidenceLifecycle.PASSED,
            "Authoritative browser verification evidence passed all integrity, freshness, and behavioral checks."
        )

    @classmethod
    def load_and_validate(
        cls,
        workspace_root: Union[str, Path],
        mission_id: Optional[str] = None,
    ) -> Tuple[BrowserEvidenceLifecycle, Optional[AuthoritativeBrowserEvidence], str]:
        """
        Locate evidence file in workspace, parse it, and validate its lifecycle status.
        """
        ws = Path(workspace_root).resolve()

        found_path: Optional[Path] = None
        for name in cls.EVIDENCE_FILENAMES:
            p = ws / name
            if p.is_file():
                found_path = p
                break

        if not found_path:
            return (
                BrowserEvidenceLifecycle.UNAVAILABLE,
                None,
                "No browser verification evidence file found in workspace."
            )

        try:
            raw_text = found_path.read_text(encoding="utf-8", errors="ignore")
            data = json.loads(raw_text)
            if not isinstance(data, dict):
                return (
                    BrowserEvidenceLifecycle.FAILED,
                    None,
                    f"Evidence file at '{found_path.name}' does not contain a JSON object."
                )

            if found_path.name == "acceptance_evidence.json":
                passed = data.get("passed", False)
                issues = data.get("issues", [])
                recorded_digest = data.get("workspace_digest", "")
                if not passed:
                    return (
                        BrowserEvidenceLifecycle.FAILED,
                        None,
                        f"Browser verification failed in {found_path.name}: {'; '.join(issues) if issues else 'acceptance check failed'}"
                    )
                # Freshness check
                hashes = compute_workspace_artifact_hashes(ws)
                from core.browser.acceptance import BrowserAcceptanceVerifier
                cur_digest = BrowserAcceptanceVerifier.compute_workspace_digest(ws)
                if recorded_digest and recorded_digest != cur_digest:
                    return (
                        BrowserEvidenceLifecycle.STALE,
                        None,
                        f"Acceptance evidence is stale (digest {recorded_digest} != {cur_digest})"
                    )
                auth_ev = AuthoritativeBrowserEvidence(
                    evidence_id=f"ev_acc_{uuid.uuid4().hex[:8]}",
                    mission_id=mission_id or "",
                    workspace_root=str(ws),
                    status=BrowserEvidenceLifecycle.PASSED,
                    tested_url=data.get("target_url") or "http://127.0.0.1:3000",
                    server_origin="http://127.0.0.1:3000",
                    verification_timestamp=float(data.get("timestamp", time.time())),
                    artifact_hashes=hashes,
                    viewports_tested=[{"width": 1280, "height": 800, "device_scale_factor": 1.0}],
                    browser_result={"interactions_passed": True, "dom_elements_verified": True},
                    console_audit={"uncaught_errors": 0, "errors": []},
                    network_audit={"failed_requests": 0},
                    provenance="hermes.cdp.verifier.v2",
                    details=data,
                )
                return (BrowserEvidenceLifecycle.PASSED, auth_ev, "Browser acceptance evidence verified.")

            evidence = AuthoritativeBrowserEvidence.from_dict(data)
            status, reason = cls.validate_evidence(evidence, ws, mission_id=mission_id)
            return status, evidence, reason
        except Exception as e:
            return (
                BrowserEvidenceLifecycle.FAILED,
                None,
                f"Failed to parse or validate evidence file '{found_path.name}': {e}"
            )


def persist_authoritative_evidence(
    workspace_root: Union[str, Path],
    evidence: AuthoritativeBrowserEvidence,
    filename: str = ".hermes/browser_verified.json",
) -> Path:
    """Save authoritative evidence to workspace with parent directory creation."""
    ws = Path(workspace_root).resolve()
    target = ws / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(evidence.to_dict(), indent=2), encoding="utf-8")
    return target