# memory/trajectory_memory.py
"""
Trajectory Memory for HERMES
Based on: EcoAssistant (Zhang et al., 2023)

EcoAssistant finding: Storing successful (query → code) pairs and
injecting the most similar past success as a few-shot demonstration
DOUBLES the success rate of weaker models on similar future tasks.

This module implements a lightweight trajectory memory:
  1. After a task completes with is_verified=True, store the trajectory
  2. On new tasks, retrieve the most similar verified trajectory
  3. Inject it as a concrete example in the task prompt

Storage: JSON file in data/trajectories/ (no vector DB required).
Similarity: keyword overlap (sufficient for our task vocabulary).
Retrieval: top-1 by similarity score.

EcoAssistant also showed that high-quality solutions (from T3 when used)
benefit ALL future similar tasks when stored. HERMES already escalates
to Claude Sonnet for hard tasks — those solutions should be stored.
"""

from __future__ import annotations

import json
import time
import hashlib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from loguru import logger


TRAJECTORY_DIR = Path("data/trajectories")
MAX_TRAJECTORIES = 200         # Prevent unbounded growth
MAX_TRAJECTORY_CONTENT = 2000  # Max chars of solution to store


@dataclass
class Trajectory:
    """
    A verified successful task execution stored for future reference.
    """
    trajectory_id: str
    task_title: str
    task_description: str
    task_keywords: list[str]
    solution_summary: str        # What files were created and what they contain
    files_created: list[str]
    skill_used: str
    tier3_was_used: bool
    timestamp: float
    quality_verdict: str         # "COMPLETE", "PASS", etc.

    def similarity_to(self, task_description: str) -> float:
        """
        Compute keyword overlap similarity.
        Simple but effective for the structured task vocabulary we use.
        """
        task_words = set(
            w.lower() for w in task_description.split()
            if len(w) > 3
        )
        stored_words = set(self.task_keywords)
        if not task_words or not stored_words:
            return 0.0
        overlap = len(task_words & stored_words)
        union = len(task_words | stored_words)
        return overlap / union if union > 0 else 0.0

    def to_demonstration(self) -> str:
        """
        Format this trajectory as a few-shot demonstration
        to inject into the T1 prompt.
        EcoAssistant's core injection format.
        """
        return (
            f"EXAMPLE FROM PAST SUCCESS:\n"
            f"Task: {self.task_title}\n"
            f"Skill used: {self.skill_used or 'none'}\n"
            f"Files created: {', '.join(self.files_created[:5])}\n"
            f"What was done: {self.solution_summary}\n"
            f"Quality: {self.quality_verdict}\n"
        )


class TrajectoryMemory:
    """
    Stores and retrieves verified successful task trajectories.

    EcoAssistant showed that STRONGER model solutions improve
    WEAKER model performance when used as demonstrations.
    In HERMES terms: T3 solutions improve T1 performance on similar tasks.
    """

    def __init__(self) -> None:
        TRAJECTORY_DIR.mkdir(parents=True, exist_ok=True)
        self._store_path = TRAJECTORY_DIR / "trajectories.json"
        self._trajectories: list[Trajectory] = self._load()

    def store(
        self,
        task_title: str,
        task_description: str,
        files_created: list[str],
        skill_used: str,
        tier3_was_used: bool,
        quality_verdict: str,
    ) -> None:
        """
        Store a verified successful trajectory.
        Only stores trajectories from tasks marked is_verified=True.
        """
        # Extract keywords
        keywords = [
            w.lower() for w in task_description.split()
            if len(w) > 3 and w.isalpha()
        ]

        # Build solution summary from file contents
        solution_summary = self._build_solution_summary(files_created)

        traj = Trajectory(
            trajectory_id=hashlib.md5(
                f"{task_description}{time.time()}".encode()
            ).hexdigest()[:12],
            task_title=task_title,
            task_description=task_description[:500],
            task_keywords=keywords[:30],
            solution_summary=solution_summary,
            files_created=[Path(f).name for f in files_created[:10]],
            skill_used=skill_used,
            tier3_was_used=tier3_was_used,
            timestamp=time.time(),
            quality_verdict=quality_verdict,
        )

        self._trajectories.append(traj)

        # Prune if over limit
        if len(self._trajectories) > MAX_TRAJECTORIES:
            # Keep most recent and highest quality
            self._trajectories.sort(
                key=lambda t: (0 if t.tier3_was_used else 1, -t.timestamp)
            )
            self._trajectories = self._trajectories[:MAX_TRAJECTORIES]

        self._save()
        logger.info(
            f"TrajectoryMemory: stored trajectory {traj.trajectory_id} "
            f"for '{task_title[:50]}'"
        )

    def retrieve_best(
        self,
        task_description: str,
        min_similarity: float = 0.25,
    ) -> Optional[Trajectory]:
        """
        Retrieve the most similar verified trajectory.
        Returns None if nothing similar enough exists.
        """
        if not self._trajectories:
            return None

        best = None
        best_score = min_similarity

        for traj in self._trajectories:
            score = traj.similarity_to(task_description)
            if score > best_score:
                best_score = score
                best = traj

        if best:
            logger.debug(
                f"TrajectoryMemory: retrieved '{best.task_title[:50]}' "
                f"(similarity={best_score:.2f})"
            )
        return best

    def _build_solution_summary(self, files_created: list[str]) -> str:
        """Build a compact summary of what was created."""
        summaries = []
        for f_path in files_created[:5]:
            p = Path(f_path)
            if p.exists():
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    # Take first meaningful lines
                    lines = [
                        l for l in content.split("\n")
                        if l.strip() and not l.strip().startswith("#")
                    ]
                    preview = "\n".join(lines[:8])[:300]
                    summaries.append(f"{p.name}:\n{preview}")
                except Exception:
                    summaries.append(f"{p.name}: (could not read)")
        return "\n\n".join(summaries)[:MAX_TRAJECTORY_CONTENT]

    def _load(self) -> list[Trajectory]:
        if not self._store_path.exists():
            return []
        try:
            with open(self._store_path) as f:
                data = json.load(f)
            return [Trajectory(**d) for d in data]
        except Exception as e:
            logger.warning(f"TrajectoryMemory: load failed: {e}")
            return []

    def _save(self) -> None:
        try:
            with open(self._store_path, "w") as f:
                json.dump([asdict(t) for t in self._trajectories], f, indent=2)
        except Exception as e:
            logger.warning(f"TrajectoryMemory: save failed: {e}")