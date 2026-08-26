# core/mission_planner.py
# MissionPlanner — transforms multi-objective user prompts into executable DAGs.
#
# The core problem this solves:
#   User: "Build Flask API, add JWT auth, write tests, push to GitHub"
#   Old HERMES: executes first action (create folder) → stops.
#   New HERMES: decomposes into 4 tasks with dependencies → KAIROS executes all.
#
# Architecture:
#   1. IntentParser:     splits prompt into distinct objectives
#   2. DependencyMapper: detects which tasks depend on which
#   3. DAGBuilder:       produces a topologically-sorted task queue
#   4. KahnSorter:       validates the DAG is acyclic and orders execution
#
# Output goes directly into the SQLite tasks table via KAIROS.

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
from loguru import logger


# ── Task state machine ────────────────────────────────────────────────────────

class TaskState(str, Enum):
    PENDING   = "PENDING"
    RUNNING   = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED    = "FAILED"
    BLOCKED   = "BLOCKED"       # Dependency failed — cannot proceed
    SKIPPED   = "SKIPPED"       # User or system chose to skip


class TaskPriority(int, Enum):
    CRITICAL = 1    # Setup, init — everything depends on this
    HIGH     = 2    # Core features
    NORMAL   = 3    # Standard tasks
    LOW      = 4    # Documentation, cleanup
    OPTIONAL = 5    # Nice-to-have, skippable


# ── Task data structures ──────────────────────────────────────────────────────

@dataclass
class MissionTask:
    """
    One atomic unit of work within a mission.
    Atomic means: can be executed by a single tool call or a tight sequence
    of tool calls targeting the same file or subsystem.
    """
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    description: str = ""
    priority: TaskPriority = TaskPriority.NORMAL
    state: TaskState = TaskState.PENDING
    depends_on: list[str] = field(default_factory=list)  # List of task_ids
    retry_count: int = 0
    max_retries: int = 3
    skill_hint: str = ""          # Which SKILL.md to load for this task
    expected_outputs: list[str] = field(default_factory=list)   # Files expected
    acceptance_criteria: str = ""  # How to know this task succeeded
    error_message: str = ""

    @property
    def is_ready(self) -> bool:
        """True if this task has no pending dependencies — can start immediately."""
        return self.state == TaskState.PENDING and len(self.depends_on) == 0

    @property
    def can_retry(self) -> bool:
        return self.state == TaskState.FAILED and self.retry_count < self.max_retries

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority.value,
            "state": self.state.value,
            "depends_on": self.depends_on,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "skill_hint": self.skill_hint,
            "acceptance_criteria": self.acceptance_criteria,
        }


@dataclass
class Mission:
    """
    A complete mission: the user's full objective decomposed into tasks.
    The mission is complete when all tasks are COMPLETED.
    """
    mission_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_prompt: str = ""
    tasks: list[MissionTask] = field(default_factory=list)
    execution_order: list[str] = field(default_factory=list)  # task_ids in topological order
    workspace_root: str = ""

    @property
    def is_complete(self) -> bool:
        return all(t.state == TaskState.COMPLETED for t in self.tasks)

    @property
    def has_failure(self) -> bool:
        return any(t.state == TaskState.FAILED for t in self.tasks)

    @property
    def next_executable_task(self) -> Optional[MissionTask]:
        """
        Return the next task that can be executed right now.
        A task is executable if:
          - Its state is PENDING
          - All tasks in its depends_on list are COMPLETED
        """
        completed_ids = {t.task_id for t in self.tasks if t.state == TaskState.COMPLETED}

        for task_id in self.execution_order:
            task = self._get_task(task_id)
            if task is None:
                continue
            if task.state != TaskState.PENDING:
                continue
            if all(dep_id in completed_ids for dep_id in task.depends_on):
                return task
        return None

    @property
    def progress(self) -> tuple[int, int]:
        """Returns (completed_count, total_count)."""
        completed = sum(1 for t in self.tasks if t.state == TaskState.COMPLETED)
        return completed, len(self.tasks)

    def _get_task(self, task_id: str) -> Optional[MissionTask]:
        return next((t for t in self.tasks if t.task_id == task_id), None)

    def mark_task_complete(self, task_id: str) -> None:
        task = self._get_task(task_id)
        if task:
            task.state = TaskState.COMPLETED
            logger.info(f"Mission {self.mission_id}: task {task_id} '{task.title}' COMPLETED")
            # Unblock tasks that were waiting on this one
            self._unblock_dependent_tasks(task_id)

    def mark_task_failed(self, task_id: str, error: str = "") -> None:
        task = self._get_task(task_id)
        if task:
            task.state = TaskState.FAILED
            task.error_message = error
            task.retry_count += 1
            logger.warning(f"Mission {self.mission_id}: task {task_id} '{task.title}' FAILED — {error[:80]}")
            # Block tasks that depend on the failed one
            self._block_dependent_tasks(task_id)

    def mark_task_running(self, task_id: str) -> None:
        task = self._get_task(task_id)
        if task:
            task.state = TaskState.RUNNING

    def retry_task(self, task_id: str) -> bool:
        task = self._get_task(task_id)
        if task and task.can_retry:
            task.state = TaskState.PENDING
            logger.info(f"Mission {self.mission_id}: retrying task {task_id} (attempt {task.retry_count}/{task.max_retries})")
            return True
        return False

    def _block_dependent_tasks(self, failed_task_id: str) -> None:
        for task in self.tasks:
            if failed_task_id in task.depends_on and task.state == TaskState.PENDING:
                task.state = TaskState.BLOCKED
                logger.warning(f"Blocking task '{task.title}' — dependency '{failed_task_id}' failed")

    def _unblock_dependent_tasks(self, completed_task_id: str) -> None:
        """After a task completes, check if any BLOCKED tasks can now proceed."""
        completed_ids = {t.task_id for t in self.tasks if t.state == TaskState.COMPLETED}
        for task in self.tasks:
            if task.state == TaskState.BLOCKED:
                if all(dep_id in completed_ids for dep_id in task.depends_on):
                    task.state = TaskState.PENDING
                    logger.info(f"Unblocked task '{task.title}' — all dependencies satisfied")

    def get_status_lines(self) -> list[str]:
        """Return human-readable status lines for TUI display."""
        lines = []
        for i, task in enumerate(self.tasks, 1):
            icons = {
                TaskState.PENDING:   "○",
                TaskState.RUNNING:   "▶",
                TaskState.COMPLETED: "✓",
                TaskState.FAILED:    "✗",
                TaskState.BLOCKED:   "⊘",
                TaskState.SKIPPED:   "−",
            }
            icon = icons.get(task.state, "?")
            lines.append(f"  {i:2d}. {task.title:<45} {icon} {task.state.value.title()}")
        return lines


# ── Intent parsing ────────────────────────────────────────────────────────────

# Patterns that signal task boundaries in a multi-objective prompt
TASK_SEPARATOR_PATTERNS: list[str] = [
    r"\band\b",           # "Create X and write Y"
    r"\bthen\b",          # "Create X then write Y"
    r"\bafter\b",         # "After creating X, write Y"
    r"\bnext\b",          # "Next, write tests"
    r"\bfinally\b",       # "Finally, push to GitHub"
    r"\balso\b",          # "Also add authentication"
    r"\bmoreover\b",
    r"\badditionally\b",
    r"\bfurthermore\b",
]

# Domain keywords that map to skill hints
SKILL_KEYWORD_MAP: dict[str, str] = {
    # Testing (high priority)
    "pytest": "pytest-generation",
    "unit test": "pytest-generation",
    "test": "pytest-generation",
    # Security
    "security": "security-audit",
    "vulnerability": "security-audit",
    "audit": "security-audit",
    # Debugging
    "debug": "debugging",
    "fix": "debugging",
    "error": "debugging",
    # Git
    "git": "git-workflow",
    "github": "git-workflow",
    "push": "git-workflow",
    "commit": "git-workflow",
    # Frameworks & Core APIs (before database mentions)
    "flask": "flask-rest-api",
    "rest": "flask-rest-api",
    "api": "flask-rest-api",
    "backend": "flask-rest-api",
    # Database
    "database": "database-design",
    "schema": "database-design",
    "sqlite": "database-design",
    "sql": "database-design",
    # Documentation
    "readme": "auto-docs",
    "documentation": "auto-docs",
    "docs": "auto-docs",
    # Specific route/endpoint
    "endpoint": "flask-rest-api",
    "route": "flask-rest-api",
    # Refactoring & Scripts & Frontend
    "refactor": "refactoring",
    "clean": "refactoring",
    "bash": "bash-scripting",
    "script": "bash-scripting",
    "react": "react-frontend",
    "frontend": "react-frontend",
    "component": "react-frontend",
}

# Dependency heuristics — if task A title contains key and task B contains value,
# A depends on B
DEPENDENCY_HEURISTICS: list[tuple[str, str]] = [
    ("test", "create"),         # tests depend on what they test being created
    ("test", "implement"),      # tests depend on implementation
    ("push", "commit"),         # push depends on commit
    ("push", "test"),           # push only after tests pass
    ("commit", "implement"),    # commit after implementation
    ("commit", "create"),       # commit after creation
    ("deploy", "test"),         # deploy after tests
    ("deploy", "commit"),       # deploy after commit
    ("document", "implement"),  # docs after implementation
    ("readme", "implement"),    # readme after implementation
    ("migrate", "schema"),      # migration after schema
    ("run", "create"),          # running after creating
]


class MissionPlanner:
    """
    Transforms a user's multi-objective prompt into a structured Mission with a DAG.

    Usage:
        planner = MissionPlanner()
        mission = planner.plan("Build Flask API, write tests, push to GitHub")
        print(mission.get_status_lines())
        next_task = mission.next_executable_task
    """

    def plan(self, user_prompt: str, workspace_root: str = "") -> Mission:
        """
        Main entry point. Decomposes the prompt into a Mission.

        Steps:
          1. Parse intent into raw task descriptions
          2. Build MissionTask objects with skill hints
          3. Detect dependencies using heuristics
          4. Topological sort (Kahn's algorithm)
          5. Return Mission ready for KAIROS execution
        """
        mission = Mission(
            user_prompt=user_prompt,
            workspace_root=workspace_root,
        )

        # Step 1: Parse into raw task descriptions
        raw_tasks = self._parse_intent(user_prompt)
        logger.info(f"MissionPlanner: parsed {len(raw_tasks)} tasks from prompt")

        if not raw_tasks:
            # Single-task mission — treat whole prompt as one task
            raw_tasks = [user_prompt.strip()]

        # Step 2: Create MissionTask objects
        tasks: list[MissionTask] = []
        for i, raw in enumerate(raw_tasks):
            task = MissionTask(
                title=self._generate_title(raw),
                description=raw.strip(),
                priority=self._assign_priority(raw, i),
                skill_hint=self._detect_skill(raw),
                acceptance_criteria=self._generate_acceptance_criteria(raw),
            )
            tasks.append(task)

        # Step 3: Detect dependencies
        self._assign_dependencies(tasks)

        # Step 4: Topological sort
        sorted_ids = self._topological_sort(tasks)

        mission.tasks = tasks
        mission.execution_order = sorted_ids

        logger.info(
            f"MissionPlanner: mission {mission.mission_id} | "
            f"{len(tasks)} tasks | order: {[t.title[:20] for t in tasks]}"
        )
        return mission

    def _parse_intent(self, prompt: str) -> list[str]:
        """
        Split a multi-objective prompt into individual task descriptions.
        Uses a combination of separator pattern detection and sentence analysis.
        """
        # First try numbered list detection (1. ... 2. ... 3. ...)
        numbered = re.split(r'\n\s*\d+[\.\)]\s+', prompt)
        if len(numbered) > 1:
            return [t.strip() for t in numbered if t.strip() and len(t.strip()) > 5]

        # Try bullet point detection
        bulleted = re.split(r'\n\s*[-•*]\s+', prompt)
        if len(bulleted) > 1:
            return [t.strip() for t in bulleted if t.strip() and len(t.strip()) > 5]

        # Try natural language separators
        # Replace separators with a unique delimiter, then split
        normalized = prompt
        for pattern in TASK_SEPARATOR_PATTERNS:
            normalized = re.sub(pattern, " |TASK_SPLIT| ", normalized, flags=re.IGNORECASE)

        parts = normalized.split("|TASK_SPLIT|")
        parts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 5]

        if len(parts) > 1:
            return parts

        # Sentence splitting as fallback
        sentences = re.split(r'[.!]\s+', prompt)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 5]

        if len(sentences) > 1:
            return sentences

        # Single task
        return [prompt.strip()]

    def _generate_title(self, description: str) -> str:
        """Generate a concise title (max 50 chars) from a task description."""
        # Remove leading articles and conjunctions
        cleaned = re.sub(r'^(and|then|also|next|finally|after that)\s+', '',
                         description.strip(), flags=re.IGNORECASE)
        # Take first meaningful phrase
        words = cleaned.split()
        title = " ".join(words[:8])
        if len(title) > 50:
            title = title[:47] + "..."
        return title.strip().capitalize()

    def _assign_priority(self, description: str, index: int) -> TaskPriority:
        """Assign priority based on task type and position."""
        lower = description.lower()

        # Setup tasks always go first
        if any(kw in lower for kw in ["init", "setup", "install", "create project",
                                       "folder structure", "initialize"]):
            return TaskPriority.CRITICAL

        # Testing and validation
        if any(kw in lower for kw in ["test", "pytest", "verify", "validate"]):
            return TaskPriority.HIGH

        # Documentation and cleanup
        if any(kw in lower for kw in ["readme", "documentation", "docs",
                                       "comment", "cleanup"]):
            return TaskPriority.LOW

        # Git operations typically last
        if any(kw in lower for kw in ["push", "commit", "deploy", "publish"]):
            return TaskPriority.LOW

        # Default: normal with slight ordering by position
        return TaskPriority.NORMAL

    def _detect_skill(self, description: str) -> str:
        """Detect which SKILL.md file is most relevant for this task."""
        lower = description.lower()
        for keyword, skill in SKILL_KEYWORD_MAP.items():
            if keyword in lower:
                return skill
        return ""

    def _generate_acceptance_criteria(self, description: str) -> str:
        """
        Generate a simple acceptance criterion string.
        Used by the execution loop to verify task completion.
        """
        lower = description.lower()
        if "test" in lower:
            return "All tests pass with exit_code=0"
        if "push" in lower or "commit" in lower:
            return "Git command completes with exit_code=0"
        if "install" in lower:
            return "Package install completes with exit_code=0"
        if "create" in lower or "write" in lower or "build" in lower:
            return "Target file(s) exist on disk after execution"
        if "run" in lower or "execute" in lower:
            return "Command completes with exit_code=0"
        return "Tool execution completes with exit_code=0"

    def _assign_dependencies(self, tasks: list[MissionTask]) -> None:
        """
        Detect dependencies between tasks using keyword heuristics.
        Modifies tasks in-place by setting their depends_on lists.
        """
        for i, task_a in enumerate(tasks):
            title_a = task_a.title.lower()
            for j, task_b in enumerate(tasks):
                if i == j:
                    continue
                title_b = task_b.title.lower()

                for dependent_kw, prerequisite_kw in DEPENDENCY_HEURISTICS:
                    if dependent_kw in title_a and prerequisite_kw in title_b:
                        if task_b.task_id not in task_a.depends_on:
                            task_a.depends_on.append(task_b.task_id)
                            logger.debug(
                                f"Dependency: '{task_a.title}' depends on '{task_b.title}'"
                            )
                            break

        # Ensure no self-references or circular deps (basic check)
        for task in tasks:
            task.depends_on = [d for d in task.depends_on if d != task.task_id]

    def _topological_sort(self, tasks: list[MissionTask]) -> list[str]:
        """
        Kahn's Algorithm for topological sort.
        Returns task_ids in an order that respects all dependencies.
        If a cycle is detected (which shouldn't happen with our heuristics),
        falls back to priority order.
        """
        # Build adjacency: task_id -> set of task_ids that depend on it
        in_degree: dict[str, int] = {t.task_id: 0 for t in tasks}
        graph: dict[str, list[str]] = {t.task_id: [] for t in tasks}

        for task in tasks:
            for dep_id in task.depends_on:
                if dep_id in graph:
                    graph[dep_id].append(task.task_id)
                    in_degree[task.task_id] += 1

        # Start with tasks that have no dependencies, sorted by priority
        task_map = {t.task_id: t for t in tasks}
        queue: list[str] = sorted(
            [tid for tid, degree in in_degree.items() if degree == 0],
            key=lambda tid: task_map[tid].priority.value
        )

        result: list[str] = []
        while queue:
            # Pick highest priority (lowest value) task
            current = queue.pop(0)
            result.append(current)

            # Reduce in-degree for all dependents
            for dependent_id in graph.get(current, []):
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)
                    queue.sort(key=lambda tid: task_map[tid].priority.value)

        # Cycle detection
        if len(result) != len(tasks):
            logger.warning(
                "MissionPlanner: cycle detected in dependency graph — "
                "falling back to priority order"
            )
            return sorted(
                [t.task_id for t in tasks],
                key=lambda tid: task_map[tid].priority.value
            )

        return result
