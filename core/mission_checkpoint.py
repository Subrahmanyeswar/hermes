# core/mission_checkpoint.py
"""
Durable Mission Checkpoint Engine for HERMES 2.x (P0/P1 Large Mission Orchestration).
Saves and loads mission state, completed phases, work packages, file fingerprints,
and validation evidence at .hermes/mission_checkpoint.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

CHECKPOINT_FILENAME = "mission_checkpoint.json"
CHECKPOINT_DIR = ".hermes"

EXCLUDED_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__",
    ".pytest_cache", ".hermes", "artifacts", "dist", "build", ".cache"
}


@dataclass
class MissionCheckpoint:
    mission_id: str
    current_phase: str
    completed_phases: List[str] = field(default_factory=list)
    completed_tasks: List[str] = field(default_factory=list)
    workspace_fingerprint: Dict[str, str] = field(default_factory=dict)
    validation_evidence: List[Dict[str, Any]] = field(default_factory=list)
    tier_state: int = 1
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    active_skills: List[str] = field(default_factory=list)
    skill_telemetry: Dict[str, Any] = field(default_factory=dict)
    design_brief: Dict[str, Any] = field(default_factory=dict)
    content_coverage: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MissionCheckpoint:
        return cls(
            mission_id=data.get("mission_id", ""),
            current_phase=data.get("current_phase", "PHASE_A_PLANNING"),
            completed_phases=list(data.get("completed_phases", [])),
            completed_tasks=list(data.get("completed_tasks", [])),
            workspace_fingerprint=dict(data.get("workspace_fingerprint", {})),
            validation_evidence=list(data.get("validation_evidence", [])),
            tier_state=int(data.get("tier_state", 1)),
            timestamp=float(data.get("timestamp", time.time())),
            metadata=dict(data.get("metadata", {})),
            active_skills=list(data.get("active_skills", [])),
            skill_telemetry=dict(data.get("skill_telemetry", {})),
            design_brief=dict(data.get("design_brief", {})),
            content_coverage=dict(data.get("content_coverage", {})),
        )


class MissionCheckpointManager:
    """
    Manages durable mission checkpoints saved at .hermes/mission_checkpoint.json.
    Enables zero-redundancy recovery and fast resumption across failover tiers.
    """

    @staticmethod
    def get_checkpoint_path(workspace_root: Path | str) -> Path:
        return Path(workspace_root) / CHECKPOINT_DIR / CHECKPOINT_FILENAME

    @classmethod
    def compute_fingerprint(cls, workspace_root: Path | str) -> Dict[str, str]:
        """Compute SHA-256 fingerprint for all relevant files, ignoring build/dependency dirs."""
        root = Path(workspace_root).resolve()
        fingerprint: Dict[str, str] = {}
        if not root.exists():
            return fingerprint

        for dirpath, dirnames, filenames in os.walk(root):
            # Exclude ignored dirs in-place
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                fpath = Path(dirpath) / fname
                try:
                    rel_p = str(fpath.relative_to(root)).replace("\\", "/")
                    hasher = hashlib.sha256()
                    with open(fpath, "rb") as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            hasher.update(chunk)
                    fingerprint[rel_p] = hasher.hexdigest()
                except Exception:
                    pass
        return fingerprint

    @classmethod
    def save_checkpoint(
        cls,
        workspace_root: Path | str,
        mission_id: str,
        current_phase: str,
        completed_phases: Optional[List[str]] = None,
        completed_tasks: Optional[List[str]] = None,
        validation_evidence: Optional[List[Any]] = None,
        tier_state: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
        active_skills: Optional[List[str]] = None,
        skill_telemetry: Optional[Dict[str, Any]] = None,
        design_brief: Optional[Dict[str, Any]] = None,
        content_coverage: Optional[Dict[str, Any]] = None,
    ) -> MissionCheckpoint:
        """Atomically persist mission checkpoint to disk."""
        root = Path(workspace_root).resolve()
        chk_dir = root / CHECKPOINT_DIR
        chk_dir.mkdir(parents=True, exist_ok=True)
        chk_file = chk_dir / CHECKPOINT_FILENAME

        fp = cls.compute_fingerprint(root)
        ev_serialized = []
        if validation_evidence:
            for ev in validation_evidence:
                if hasattr(ev, "to_dict"):
                    ev_serialized.append(ev.to_dict())
                elif isinstance(ev, dict):
                    ev_serialized.append(ev)
                else:
                    ev_serialized.append(str(ev))

        checkpoint = MissionCheckpoint(
            mission_id=mission_id,
            current_phase=str(current_phase),
            completed_phases=list(completed_phases or []),
            completed_tasks=list(completed_tasks or []),
            workspace_fingerprint=fp,
            validation_evidence=ev_serialized,
            tier_state=int(tier_state),
            timestamp=time.time(),
            metadata=dict(metadata or {}),
            active_skills=list(active_skills or []),
            skill_telemetry=dict(skill_telemetry or {}),
            design_brief=dict(design_brief or {}),
            content_coverage=dict(content_coverage or {}),
        )

        tmp_file = chk_dir / f"{CHECKPOINT_FILENAME}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(checkpoint.to_dict(), f, indent=2)
        os.replace(tmp_file, chk_file)
        logger.info(f"MissionCheckpointManager: Saved checkpoint for {mission_id} at {chk_file} (phase={current_phase})")
        return checkpoint

    @classmethod
    def load_checkpoint(cls, workspace_root: Path | str) -> Optional[MissionCheckpoint]:
        """Load checkpoint if it exists and is valid JSON."""
        chk_file = cls.get_checkpoint_path(workspace_root)
        if not chk_file.exists():
            return None
        try:
            with open(chk_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return MissionCheckpoint.from_dict(data)
        except Exception as e:
            logger.warning(f"MissionCheckpointManager: Failed to load checkpoint from {chk_file}: {e}")
            return None

    @classmethod
    def verify_fingerprint_integrity(
        cls,
        workspace_root: Path | str,
        checkpoint: MissionCheckpoint,
    ) -> Tuple[bool, List[str]]:
        """Verify whether workspace files match the checkpoint fingerprint."""
        current_fp = cls.compute_fingerprint(workspace_root)
        mismatches = []
        for path, expected_hash in checkpoint.workspace_fingerprint.items():
            if path not in current_fp:
                mismatches.append(f"Missing file: {path}")
            elif current_fp[path] != expected_hash:
                mismatches.append(f"Modified file: {path}")
        return (len(mismatches) == 0, mismatches)
