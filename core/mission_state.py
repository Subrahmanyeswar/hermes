# core/mission_state.py
"""
Authoritative Mission State Engine for HERMES 2.x (Phase D).
Maintains a single source of truth for mission artifact completion,
evidence-bound validation state, checkpoint reconciliation, and deterministic next actions.
Enforces pure reconciliation: never mutates or promotes application deliverables.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.project_contract import ProjectContract, CanonicalPathResolver
from core.js_syntax_validator import compute_file_sha256

logger = logging.getLogger(__name__)


@dataclass
class AuthoritativeMissionState:
    """The single authoritative state model governing mission execution (Phase D)."""
    mission_id: str
    workspace_identity: str
    contract_version: int
    contract_hash: str
    monotonic_state_version: int = 1
    current_phase: str = "INITIALIZATION"
    required_artifacts: List[str] = field(default_factory=list)
    final_artifact_paths: List[str] = field(default_factory=list)
    staged_artifact_paths: List[str] = field(default_factory=list)
    current_artifact_hashes: Dict[str, str] = field(default_factory=dict)
    validation_evidence: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    contract_validation_status: str = "UNVERIFIED"
    unmet_requirements: List[str] = field(default_factory=list)
    current_repair_target: Optional[str] = None
    single_next_action: str = "ANALYZE_REQUIREMENTS"
    last_meaningful_progress_event: Dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AuthoritativeMissionState:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class MissionStateManager:
    """
    Coordinates authoritative state evaluation, checkpoint synchronization,
    and pure reconciliation without side-effect artifact mutation (Phase D3).
    """

    @classmethod
    def get_state_file_path(cls, workspace_root: Path | str) -> Path:
        ws = Path(workspace_root).resolve()
        return ws / ".hermes" / "mission_state.json"

    @classmethod
    def load_state(cls, workspace_root: Path | str, mission_id: Optional[str] = None) -> Optional[AuthoritativeMissionState]:
        """Load state from disk, rejecting stale missions if mission_id is specified."""
        path = cls.get_state_file_path(workspace_root)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            state = AuthoritativeMissionState.from_dict(data)
            if mission_id and state.mission_id and state.mission_id != mission_id:
                logger.info(f"MissionStateManager: Existing state belongs to older mission {state.mission_id}, not {mission_id}")
                return None
            return state
        except Exception as e:
            logger.warning(f"MissionStateManager: Failed to load state: {e}")
            return None

    @classmethod
    def reconcile_state(
        cls,
        workspace_root: Path | str,
        mission_id: str,
        contract: ProjectContract,
        current_phase: Optional[str] = None,
        last_event: Optional[Dict[str, Any]] = None,
    ) -> AuthoritativeMissionState:
        """
        Pure state reconciliation (Phase D3).
        Inspects disk artifacts against contract, verifies validation evidence freshness,
        determines unmet requirements and calculates single_next_action.
        NEVER creates, mutates, or promotes application deliverables during reconciliation.
        """
        ws = Path(workspace_root).resolve()
        existing_state = cls.load_state(ws, mission_id=mission_id)
        monotonic_ver = (existing_state.monotonic_state_version + 1) if existing_state else 1

        required = list(contract.required_files)
        final_artifacts: List[str] = []
        staged_artifacts: List[str] = []
        current_hashes: Dict[str, str] = {}
        unmet: List[str] = []

        # Retain previous valid validation evidence if hash still matches
        prev_evidence = existing_state.validation_evidence if existing_state else {}
        fresh_evidence: Dict[str, Dict[str, Any]] = {}

        for req in required:
            norm_rel = CanonicalPathResolver.normalize_slashes(req)
            full_p = ws / norm_rel
            
            # Check if final file exists and is nonempty (> 20B)
            if full_p.exists() and full_p.is_file() and full_p.stat().st_size > 20:
                final_artifacts.append(norm_rel)
                h = compute_file_sha256(full_p) or ""
                current_hashes[norm_rel] = h

                # Verify validation evidence freshness (Phase D1)
                ev = prev_evidence.get(norm_rel)
                if ev and ev.get("sha256") == h and ev.get("is_valid") is True:
                    fresh_evidence[norm_rel] = ev
                else:
                    # Stale or unrecorded
                    fresh_evidence[norm_rel] = {
                        "sha256": h,
                        "is_valid": None,  # Needs validation
                        "status": "UNVERIFIED",
                    }
            else:
                unmet.append(f"Missing required artifact: {norm_rel}")

            # Check for staged artifacts e.g. static/app.pending.js or app.js.pending
            staged_p1 = full_p.parent / f"{full_p.stem}.pending{full_p.suffix}"
            staged_p2 = full_p.parent / f"{full_p.name}.pending"
            if staged_p1.exists() and staged_p1.is_file():
                st_rel = CanonicalPathResolver.normalize_slashes(str(staged_p1.relative_to(ws)))
                staged_artifacts.append(st_rel)
                current_hashes[st_rel] = compute_file_sha256(staged_p1) or ""
            elif staged_p2.exists() and staged_p2.is_file():
                st_rel = CanonicalPathResolver.normalize_slashes(str(staged_p2.relative_to(ws)))
                staged_artifacts.append(st_rel)
                current_hashes[st_rel] = compute_file_sha256(staged_p2) or ""

        # Cross-file contract status check
        from core.cross_file_contract import CrossFileContractValidator, SEV_FAIL
        report = CrossFileContractValidator.validate_workspace(ws, current_phase=current_phase)
        contract_status = report.severity

        # Determine current repair target and single next action (Phase D)
        current_repair_target = None
        single_next_action = "ANALYZE_REQUIREMENTS"

        if staged_artifacts:
            # Check if staged artifact is ready for promotion
            st_target = staged_artifacts[0]
            current_repair_target = st_target
            single_next_action = "VALIDATE_AND_PROMOTE_STAGED_ARTIFACT"
        elif unmet:
            # First missing required artifact
            first_missing = unmet[0].split(": ")[-1]
            current_repair_target = first_missing
            single_next_action = f"GENERATE_ARTIFACT_{Path(first_missing).suffix.lstrip('.').upper() or 'FILE'}"
        elif contract_status == SEV_FAIL:
            single_next_action = "REPAIR_CROSS_FILE_CONTRACT"
            if report.endpoint_mismatches:
                current_repair_target = contract.canonical_js
            elif report.dom_id_mismatches:
                current_repair_target = contract.canonical_html
            elif report.database_mismatches:
                current_repair_target = contract.canonical_backend or "schema"
        else:
            single_next_action = "VERIFY_RUNTIME_APPLICATION"

        phase = current_phase or (existing_state.current_phase if existing_state else "SCAFFOLD")

        state = AuthoritativeMissionState(
            mission_id=mission_id,
            workspace_identity=str(ws),
            contract_version=contract.version,
            contract_hash=contract.contract_hash,
            monotonic_state_version=monotonic_ver,
            current_phase=phase,
            required_artifacts=required,
            final_artifact_paths=final_artifacts,
            staged_artifact_paths=staged_artifacts,
            current_artifact_hashes=current_hashes,
            validation_evidence=fresh_evidence,
            contract_validation_status=contract_status,
            unmet_requirements=unmet,
            current_repair_target=current_repair_target,
            single_next_action=single_next_action,
            last_meaningful_progress_event=last_event or (existing_state.last_meaningful_progress_event if existing_state else {}),
            updated_at=time.time(),
        )

        # Atomic persistence of authoritative state (Phase D2)
        cls.save_state_atomic(ws, state)

        # Synchronize checkpoints atomically (Phase D2)
        cls._sync_checkpoints(ws, state, contract)

        return state

    @classmethod
    def record_validation_evidence(
        cls,
        workspace_root: Path | str,
        mission_id: str,
        artifact_path: str,
        sha256: str,
        is_valid: bool,
        error_class: str,
        exit_code: int = 0,
    ) -> None:
        """Record verified validation evidence tied directly to input file SHA-256."""
        ws = Path(workspace_root).resolve()
        state = cls.load_state(ws, mission_id=mission_id)
        if not state:
            return
        norm_p = CanonicalPathResolver.normalize_slashes(artifact_path)
        state.validation_evidence[norm_p] = {
            "sha256": sha256,
            "is_valid": is_valid,
            "error_class": error_class,
            "exit_code": exit_code,
            "recorded_at": time.time(),
        }
        cls.save_state_atomic(ws, state)

    @classmethod
    def save_state_atomic(cls, workspace_root: Path | str, state: AuthoritativeMissionState) -> None:
        """Atomic write to .hermes/mission_state.json using same-volume temp file."""
        ws = Path(workspace_root).resolve()
        hermes_dir = ws / ".hermes"
        hermes_dir.mkdir(parents=True, exist_ok=True)
        target = hermes_dir / "mission_state.json"
        temp = hermes_dir / f".mission_state_{state.monotonic_state_version}.tmp"
        try:
            temp.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
            os.replace(temp, target)
        except Exception as e:
            logger.warning(f"MissionStateManager: Failed atomic save of mission state: {e}")
            if temp.exists():
                try:
                    temp.unlink()
                except Exception:
                    pass

    @classmethod
    def _sync_checkpoints(
        cls,
        workspace_root: Path,
        state: AuthoritativeMissionState,
        contract: ProjectContract,
    ) -> None:
        """Synchronize recovery_checkpoint.json and progress.json derived from authoritative state."""
        hermes_dir = workspace_root / ".hermes"
        hermes_dir.mkdir(parents=True, exist_ok=True)

        # 1. recovery_checkpoint.json
        rec_data = {
            "mission_id": state.mission_id,
            "state_version": state.monotonic_state_version,
            "contract_hash": state.contract_hash,
            "target_repair_file": state.current_repair_target,
            "unmet_requirements": state.unmet_requirements,
            "completed_files": state.final_artifact_paths,
            "single_next_action": state.single_next_action,
            "contract_status": state.contract_validation_status,
            "updated_at": state.updated_at,
        }
        try:
            tmp_rec = hermes_dir / f".rec_ckpt_{state.monotonic_state_version}.tmp"
            tmp_rec.write_text(json.dumps(rec_data, indent=2), encoding="utf-8")
            os.replace(tmp_rec, hermes_dir / "recovery_checkpoint.json")
        except Exception as e:
            logger.debug(f"Could not sync recovery checkpoint: {e}")

        # 2. progress.json in .artifacts/missions/<mission_id>/progress.json
        if state.mission_id:
            art_dir = workspace_root / ".artifacts" / "missions" / state.mission_id
            art_dir.mkdir(parents=True, exist_ok=True)
            prog_data = {
                "mission_id": state.mission_id,
                "current_phase": state.current_phase,
                "current_focus": state.current_repair_target or state.single_next_action,
                "required_files": state.required_artifacts,
                "completed_files": state.final_artifact_paths,
                "staged_files": state.staged_artifact_paths,
                "contract_hash": state.contract_hash,
                "updated_at": state.updated_at,
            }
            try:
                tmp_prog = art_dir / f".prog_{state.monotonic_state_version}.tmp"
                tmp_prog.write_text(json.dumps(prog_data, indent=2), encoding="utf-8")
                os.replace(tmp_prog, art_dir / "progress.json")
            except Exception as e:
                logger.debug(f"Could not sync progress.json: {e}")
