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

from core.planning.requirement_types import extract_target_artifacts, extract_typed_requirements


# ── Mission Complexity (Phase 4E) ──────────────────────────────────────────────

class MissionComplexity(str, Enum):
    TRIVIAL = "TRIVIAL"       # Single file edit, micro script, simple command
    SIMPLE  = "SIMPLE"        # Small 1-3 file web app, single utility, campus board, portfolio
    MEDIUM  = "MEDIUM"        # Multi-feature single-tier app, standard web app with 4-5 files
    COMPLEX = "COMPLEX"       # Full-stack app, multi-tier system with database and API routes
    LARGE   = "LARGE"         # Multi-package, microservices, complex distributed architecture


def classify_mission_complexity(prompt: str, workspace_root: str = "") -> MissionComplexity:
    """
    Deterministic zero-LLM mission complexity classifier (< 0.2ms).
    Prevents over-decomposition of simple tasks and maintains deep planning
    for truly complex systems.
    """
    lower = prompt.lower().strip()
    words = lower.split()
    word_count = len(words)

    # Complexity indicators
    has_large = any(k in lower for k in [
        "microservice", "microservices", "distributed", "kubernetes", "monorepo",
        "multi-repo", "kafka", "event-driven architecture"
    ])
    if has_large:
        return MissionComplexity.LARGE

    has_complex = any(k in lower for k in [
        "full stack", "full-stack", "oauth", "jwt", "authentication", "login and signup",
        "database migration", "background worker", "celery", "redis queue",
        "stripe", "payment processing"
    ]) or (word_count > 150 and any(k in lower for k in ["backend and frontend", "api and database"]))
    if has_complex:
        return MissionComplexity.COMPLEX

    has_medium = any(k in lower for k in [
        "flask api", "fastapi", "rest api", "sqlite database", "crud api", "endpoints",
        "models and routes", "backend service"
    ])
    if has_medium:
        return MissionComplexity.MEDIUM

    # Explicit multi-step lists (bullet or numbered) are never trivial
    has_list = len(re.findall(r'^\s*[-*•\d+.]\s+\w+', prompt, re.MULTILINE)) >= 2
    if has_list:
        return MissionComplexity.MEDIUM if any(k in lower for k in ["flask", "api", "database", "backend"]) else MissionComplexity.SIMPLE

    # Check for trivial single-file or single-command prompts
    clean_prompt = re.sub(r'https?://[^\s<>"\']+', '', prompt)
    file_matches = re.findall(r'\b[\w\-]+\.(?:py|html|css|js|txt|md)\b', clean_prompt)
    has_trivial = not has_list and word_count < 25 and (
        any(k in lower for k in ["hello world", "single file", "script to", "function that", "one file", "push", "commit", "github", "pytest", "tests for"])
        or (len(file_matches) == 1 and not any(k in lower for k in ["website", "app", "board", "portal"]))
    )
    if has_trivial:
        return MissionComplexity.TRIVIAL

    # Default for single-page web applications, event boards, portfolios, calculators, landing pages
    return MissionComplexity.SIMPLE


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
    dependents: list[str] = field(default_factory=list)  # List of dependent task_ids
    ready_reason: str = ""
    target_paths: list[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    skill_hint: str = ""          # Which SKILL.md to load for this task
    expected_outputs: list[str] = field(default_factory=list)   # Files expected
    acceptance_criteria: str = ""  # How to know this task succeeded
    error_message: str = ""
    required_files: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    required_content_keywords: list[str] = field(default_factory=list)
    is_verified: bool = False
    verification_evidence: str = ""

    # Phase 4E: Resource & File-Contract Concurrency Fields
    resource_claims: list[str] = field(default_factory=list)
    read_dependencies: list[str] = field(default_factory=list)
    write_dependencies: list[str] = field(default_factory=list)
    conflict_keys: list[str] = field(default_factory=list)

    def compute_conflict_keys(self) -> list[str]:
        """Compute conflict keys for concurrency scheduling."""
        keys = set(self.conflict_keys)
        targets = self.write_dependencies or self.target_paths or self.expected_outputs or self.required_files
        for p in targets:
            norm = p.lower().replace("\\", "/").lstrip("./")
            keys.add(f"write:{norm}")
        for r in self.read_dependencies:
            norm = r.lower().replace("\\", "/").lstrip("./")
            keys.add(f"read:{norm}")
        return sorted(list(keys))

    @property
    def is_verification_task(self) -> bool:
        """True if this task is an end-to-end verification, testing, or final validation barrier task."""
        title_lower = self.title.lower()
        # Implementation tasks creating code are not end-to-end verification barrier tasks
        if any(title_lower.startswith(p) for p in ("implement", "create", "write", "build", "add", "establish", "develop", "style", "design")):
            return False
        return any(kw in title_lower for kw in (
            "verify", "verification", "validate", "validation", "acceptance",
            "audit project", "project completeness", "final check", "e2e"
        ))

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
            "priority": self.priority.value if hasattr(self.priority, "value") else int(self.priority),
            "state": self.state.value if hasattr(self.state, "value") else str(self.state),
            "depends_on": self.depends_on,
            "dependents": self.dependents,
            "ready_reason": self.ready_reason,
            "target_paths": self.target_paths or self.expected_outputs or self.required_files,
            "resource_claims": self.resource_claims,
            "read_dependencies": self.read_dependencies,
            "write_dependencies": self.write_dependencies,
            "conflict_keys": self.compute_conflict_keys(),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "skill_hint": self.skill_hint,
            "acceptance_criteria": self.acceptance_criteria,
            "required_files": self.required_files,
            "is_verified": self.is_verified,
        }


@dataclass
class Mission:
    """
    A complete mission: the user's full objective decomposed into tasks.
    The mission is complete when all tasks are COMPLETED.
    """
    mission_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    run_id: Optional[str] = None
    attempt_number: int = 1
    abort_event: Optional[Any] = None
    user_prompt: str = ""
    tasks: list[MissionTask] = field(default_factory=list)
    execution_order: list[str] = field(default_factory=list)  # task_ids in topological order
    workspace_root: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    verified_criteria: list[str] = field(default_factory=list)
    project_root_path: str = ""
    architecture_decision: Optional[Any] = None
    complexity: MissionComplexity = MissionComplexity.SIMPLE

    @property
    def criteria_met(self) -> bool:
        if not self.acceptance_criteria:
            return True
        return len(self.verified_criteria) >= len(self.acceptance_criteria)

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
          - Hard verification barrier: Verification tasks MUST NOT execute
            until ALL non-verification tasks are COMPLETED.
        """
        completed_ids = {t.task_id for t in self.tasks if t.state == TaskState.COMPLETED}
        non_verification_completed = all(
            t.state == TaskState.COMPLETED
            for t in self.tasks
            if not t.is_verification_task
        )

        order = self.execution_order if self.execution_order else [t.task_id for t in self.tasks]
        for task_id in order:
            task = self._get_task(task_id)
            if task is None:
                continue
            if task.state != TaskState.PENDING:
                continue
            # Hard verification barrier: verification tasks never run while prerequisites are pending
            if task.is_verification_task and not non_verification_completed:
                continue
            if all(dep_id in completed_ids for dep_id in task.depends_on):
                task.ready_reason = "all_dependencies_completed" if task.depends_on else "no_dependencies"
                return task
        return None

    def get_executable_batch(self, max_concurrent: int = 3, provider_healthy: bool = True) -> list[MissionTask]:
        """
        Return a batch of independent, non-conflicting tasks that are executable right now.
        Guarantees:
        1. All dependencies completed.
        2. Hard verification barrier preserved (verification runs only after all non-verification complete).
        3. No concurrent writes to the same target artifact (disjoint write_dependencies and conflict_keys).
        4. Dynamic batch size bounds respected (adapts to provider limits).
        """
        completed_ids = {t.task_id for t in self.tasks if t.state == TaskState.COMPLETED}
        non_verification_completed = all(
            t.state == TaskState.COMPLETED
            for t in self.tasks
            if not t.is_verification_task
        )

        order = self.execution_order if self.execution_order else [t.task_id for t in self.tasks]
        batch: list[MissionTask] = []
        claimed_write_targets: set[str] = set()
        claimed_conflict_keys: set[str] = set()

        for task_id in order:
            task = self._get_task(task_id)
            if task is None or task.state != TaskState.PENDING:
                continue
            # Hard verification barrier
            if task.is_verification_task and not non_verification_completed:
                continue
            # Dependency check
            if not all(dep_id in completed_ids for dep_id in task.depends_on):
                continue

            # Compute conflict keys for this task
            task_conflict_keys = set(task.compute_conflict_keys())
            task_write_targets = set(
                p.lower().replace("\\", "/").lstrip("./")
                for p in (task.write_dependencies or task.target_paths or task.expected_outputs or [])
            )

            # Check write conflict with already batched tasks
            if task_write_targets and claimed_write_targets.intersection(task_write_targets):
                continue

            # Check general write/read conflict keys
            write_keys = {k for k in task_conflict_keys if k.startswith("write:")}
            if write_keys and claimed_conflict_keys.intersection(write_keys):
                continue

            task.ready_reason = "all_dependencies_completed" if task.depends_on else "no_dependencies"
            batch.append(task)
            if task_write_targets:
                claimed_write_targets.update(task_write_targets)
            if task_conflict_keys:
                claimed_conflict_keys.update(task_conflict_keys)

            if len(batch) >= max_concurrent:
                break

        return batch

    @property
    def progress(self) -> tuple[int, int]:
        """Returns (completed_count, total_count)."""
        completed = sum(1 for t in self.tasks if t.state == TaskState.COMPLETED)
        return completed, len(self.tasks)

    def add_task(self, task: MissionTask) -> None:
        """Add a task to the mission and update execution order."""
        self.tasks.append(task)
        if task.task_id not in self.execution_order:
            self.execution_order.append(task.task_id)

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
    "vanilla": "vanilla-web",
    "vanilla-web": "vanilla-web",
    "html": "vanilla-web",
    "website": "vanilla-web",
    "webpage": "vanilla-web",
    "css": "vanilla-web",
}

# Dependency heuristics — if task A title contains key and task B contains value,
# A depends on B
DEPENDENCY_HEURISTICS: list[tuple[str, str]] = [
    # Verification & Testing depend on implementation, creation, setup, and integration
    ("verify", "create"),
    ("verify", "implement"),
    ("verify", "integrate"),
    ("verify", "setup"),
    ("verify", "structure"),
    ("verify", "build"),
    ("validate", "create"),
    ("validate", "implement"),
    ("validate", "integrate"),
    ("validate", "setup"),
    ("test", "create"),
    ("test", "implement"),
    ("test", "integrate"),
    ("test", "setup"),
    # Integration depends on core artifact creation
    ("integrate", "create"),
    ("integrate", "implement"),
    ("integrate", "setup"),
    ("integrate", "structure"),
    ("feature", "create"),
    ("feature", "implement"),
    # Git & Deployment
    ("push", "commit"),
    ("push", "test"),
    ("push", "verify"),
    ("commit", "implement"),
    ("commit", "create"),
    ("commit", "verify"),
    ("deploy", "test"),
    ("deploy", "commit"),
    ("deploy", "verify"),
    # Documentation & Migration
    ("document", "implement"),
    ("readme", "implement"),
    ("migrate", "schema"),
    ("run", "create"),
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

    def plan(self, user_prompt: str, workspace_root: str = "", execution_mode: str = "production") -> Mission:
        """
        Main entry point. Decomposes the prompt into a Mission.

        Steps:
          1. Parse intent into raw task descriptions
          2. Build MissionTask objects with skill hints
          3. Detect dependencies using heuristics
          4. Topological sort (Kahn's algorithm)
          5. Return Mission ready for KAIROS execution
        """
        # Mandatory canonical workspace binding (PART A)
        from pathlib import Path
        from core.workspace import global_workspace, workspace_manager
        if not workspace_root:
            wm = global_workspace if (global_workspace and global_workspace.is_locked) else workspace_manager
            workspace_root = wm.root_str if (wm and wm.is_locked and wm.root_str) else (wm.root_str if (wm and wm.root_str) else str(Path.cwd().resolve()))
        canonical_ws = str(Path(workspace_root).resolve())

        mission = Mission(
            user_prompt=user_prompt,
            workspace_root=canonical_ws,
            project_root_path=canonical_ws,
        )

        # Step 0: Authoritative Architecture Lock
        from core.architecture_lock import ArchitectureLock, detect_architecture
        arch = detect_architecture(user_prompt, workspace_root=canonical_ws)
        mission.architecture_decision = arch
        ArchitectureLock.lock(arch, mission_id=mission.mission_id)

        # Step 0.5: Phase 4E Mission Complexity Classification
        complexity = classify_mission_complexity(user_prompt, workspace_root=canonical_ws)
        mission.complexity = complexity
        from core.architecture_lock import ArchitectureType
        is_web_app = arch and arch.architecture_type == ArchitectureType.VANILLA_WEB and any(k in user_prompt.lower() for k in ["web", "html", "css", "board", "page", "dashboard", "portfolio", "site", "ui", "calc", "tracker", "console"])
        if complexity == MissionComplexity.SIMPLE and is_web_app:
            tasks = self._plan_simple_mission(user_prompt, workspace_root=canonical_ws, arch=arch)
        elif complexity == MissionComplexity.TRIVIAL:
            tasks = self._plan_trivial_mission(user_prompt, workspace_root=canonical_ws, arch=arch)
        else:
            # Step 1: Parse into raw task descriptions
            raw_tasks = self._parse_intent(user_prompt, execution_mode=execution_mode)
            if execution_mode != "benchmark" and len(raw_tasks) > 6:
                raw_tasks = self._consolidate_to_milestones(raw_tasks, user_prompt)
            logger.info(f"MissionPlanner: parsed {len(raw_tasks)} tasks from prompt | mode={execution_mode}")

            if not raw_tasks:
                # Single-task mission — treat whole prompt as one task
                raw_tasks = [user_prompt.strip()]

            # Step 2: Create MissionTask objects
            tasks: list[MissionTask] = []
            for i, raw in enumerate(raw_tasks):
                raw_clean = re.sub(r'https?://[^\s<>"\']+', '', raw)
                f_matches = re.findall(r'\b([\w\-/\\]+\.(?:html|css|json|jsx|js|py|md|tsx|ts|sql|sh))\b', raw_clean, re.IGNORECASE)
                clean_f = [fm.replace("\\", "/").lstrip("./") for fm in f_matches if not fm.startswith("http")]
                task = MissionTask(
                    title=self._generate_title(raw),
                    description=raw.strip(),
                    priority=self._assign_priority(raw, i),
                    skill_hint=self._detect_skill(raw),
                    acceptance_criteria=self._generate_acceptance_criteria(raw),
                    target_paths=clean_f,
                    write_dependencies=clean_f,
                    conflict_keys=[f"write:{cf.lower()}" for cf in clean_f],
                )
                tasks.append(task)

            # Always start with workspace inspection for complex missions
            inspection_task = MissionTask(
                title="Inspect workspace and existing files",
                description=(
                    f"Before implementing anything, inspect the workspace at "
                    f"{workspace_root or 'generated_projects/'} to understand "
                    f"what already exists. Use list_directory and read_file to "
                    f"read the most relevant existing files. Identify: "
                    f"(1) what files already exist, "
                    f"(2) what framework/technology is in use, "
                    f"(3) what code can be reused, "
                    f"(4) what needs to be created from scratch. "
                    f"Report findings clearly."
                ),
                priority=TaskPriority.CRITICAL,
                skill_hint="",
                acceptance_criteria="Workspace structure inspected and understood",
            )
            lower_prompt = user_prompt.lower()
            is_complex_mission = any(w in lower_prompt for w in [
                "website", "web app", "webpage", "landing page", "portfolio",
                "animated", "career", "full stack", "frontend and backend", "complete app"
            ])
            
            should_inspect = is_complex_mission
            if execution_mode != "benchmark":
                from pathlib import Path
                target_check = Path(workspace_root) if workspace_root else Path("generated_projects")
                try:
                    existing_files = [f for f in target_check.glob("*") if not f.name.startswith(".")] if target_check.exists() else []
                    existing_count = len(existing_files)
                except Exception:
                    existing_count = 0
                if existing_count == 0:
                    should_inspect = False

            if len(tasks) > 1 and should_inspect:
                tasks.insert(0, inspection_task)

            if execution_mode != "benchmark" and len(tasks) > 6:
                if tasks[-1].is_verification_task:
                    tasks = tasks[:5] + [tasks[-1]]
                else:
                    tasks = tasks[:6]

            # Step 3: Detect dependencies
            self._assign_dependencies(tasks)

        # Step 4: Topological sort
        sorted_ids = self._topological_sort(tasks)

        mission.tasks = tasks
        mission.execution_order = sorted_ids

        # Derive acceptance criteria from prompt
        mission.acceptance_criteria = self._derive_acceptance_criteria(
            user_prompt, tasks
        )
        # Detect the canonical project root path that will be created
        mission.project_root_path = self._detect_project_root(user_prompt, workspace_root=canonical_ws)

        # Canonicalize target paths for all tasks relative to project_root_path
        for task in tasks:
            clean_targets = []
            raw_targets = task.target_paths or task.expected_outputs or task.required_files
            for t_path in raw_targets:
                norm_p = t_path.replace("\\", "/")
                # Strip any accidental 'generated_projects/[^/]+/' prefix
                norm_p = re.sub(r'^generated_projects/[^/]+/', '', norm_p)
                norm_p = re.sub(r'^generated_projects/', '', norm_p)
                clean_targets.append(norm_p)
            task.target_paths = clean_targets
            task.expected_outputs = clean_targets

        logger.info(
            f"MissionPlanner: mission {mission.mission_id} | "
            f"{len(tasks)} tasks | order: {[t.title[:20] for t in tasks]}"
        )
        return mission

    def _plan_simple_mission(self, user_prompt: str, workspace_root: str = "", arch: Any = None) -> list[MissionTask]:
        """
        Produce 3-4 coherent, high-efficiency execution units for simple missions.
        Guarantees:
        1. HTML scaffold/markup established first as the shared contract.
        2. Styling and interaction logic execute concurrently with disjoint write targets.
        3. Comprehensive integrated verification barrier.
        """
        import uuid
        task1_id = uuid.uuid4().hex[:8]
        task2_id = uuid.uuid4().hex[:8]
        task3_id = uuid.uuid4().hex[:8]
        task4_id = uuid.uuid4().hex[:8]

        css_path = "css/styles.css" if "css/" in user_prompt else "css/styles.css"
        js_path = "js/app.js" if "js/" in user_prompt else "js/app.js"

        # Task 1: Architecture & HTML
        t1 = MissionTask(
            task_id=task1_id,
            title="Establish application architecture and core HTML layout in index.html",
            description=(
                f"Establish the application structure and implement index.html with complete semantic HTML5 structure, "
                f"accessible navigation, header, main layout, and containers for user interaction based on: {user_prompt.strip()[:300]}. "
                f"Link stylesheets to '{css_path}' and script to '{js_path}'."
            ),
            priority=TaskPriority.CRITICAL,
            skill_hint="vanilla-web",
            target_paths=["index.html"],
            expected_outputs=["index.html"],
            required_files=["index.html"],
            write_dependencies=["index.html"],
            conflict_keys=["write:index.html"],
            acceptance_criteria="index.html exists and contains complete semantic markup with required IDs and classes",
        )

        # Task 2: CSS / Visual Styling
        t2 = MissionTask(
            task_id=task2_id,
            title=f"Implement visual styling, design system, and responsive layout in {css_path}",
            description=(
                f"Create {css_path} with a cohesive modern design system: CSS custom properties (color palette, "
                f"typography tokens, spacing scale, shadows, border radii), responsive grid/flexbox cards, hover/focus/active states, "
                f"dialog/modal presentation, subtle transitions, and responsive reflow for desktop 1280px, tablet 768px, and mobile 375px. "
                f"Must have zero horizontal scroll overflow. Style elements and classes defined in index.html."
            ),
            priority=TaskPriority.HIGH,
            skill_hint="vanilla-web",
            target_paths=[css_path],
            expected_outputs=[css_path],
            required_files=[css_path],
            read_dependencies=["index.html"],
            write_dependencies=[css_path],
            conflict_keys=[f"write:{css_path.lower()}", "read:index.html"],
            depends_on=[task1_id],
            acceptance_criteria=f"{css_path} exists with complete styles, design tokens, and responsive media queries",
        )

        # Task 3: JavaScript / Logic / State / Persistence
        t3 = MissionTask(
            task_id=task3_id,
            title=f"Implement interactive behavior, state management, and localStorage persistence in {js_path}",
            description=(
                f"Create {js_path} with complete interactive behavior: realistic populated dataset (at least 5 items/records), "
                f"search query filtering, category/status filtering, item detail viewing/modal handling, interactive state toggles (interested/favorite counters), "
                f"creation form submission with validation, and complete localStorage persistence across page reloads. "
                f"Match element IDs and class selectors from index.html."
            ),
            priority=TaskPriority.HIGH,
            skill_hint="vanilla-web",
            target_paths=[js_path],
            expected_outputs=[js_path],
            required_files=[js_path],
            read_dependencies=["index.html"],
            write_dependencies=[js_path],
            conflict_keys=[f"write:{js_path.lower()}", "read:index.html"],
            depends_on=[task1_id],
            acceptance_criteria=f"{js_path} exists with complete interactive logic, event listeners, and localStorage persistence",
        )

        # Task 4: Verification & Validation
        t4 = MissionTask(
            task_id=task4_id,
            title="Verify and validate full application functionality, responsive design, and data persistence",
            description=(
                f"Perform comprehensive verification of index.html, {css_path}, and {js_path}. "
                f"Verify that all UI components render correctly, search and filtering operate as expected, "
                f"detail dialogs open and close, state changes persist across browser reloads, and responsive layouts reflow cleanly without overflow."
            ),
            priority=TaskPriority.LOW,
            skill_hint="vanilla-web",
            target_paths=["index.html", css_path, js_path],
            expected_outputs=["index.html", css_path, js_path],
            read_dependencies=["index.html", css_path, js_path],
            write_dependencies=[],
            conflict_keys=["read:index.html", f"read:{css_path.lower()}", f"read:{js_path.lower()}"],
            is_verified=False,
            depends_on=[task1_id, task2_id, task3_id],
            acceptance_criteria="All application files verified, functional requirements validated, and quality criteria satisfied",
        )

        t1.dependents = [task2_id, task3_id, task4_id]
        t2.dependents = [task4_id]
        t3.dependents = [task4_id]

        return [t1, t2, t3, t4]

    def _plan_trivial_mission(self, user_prompt: str, workspace_root: str = "", arch: Any = None) -> list[MissionTask]:
        """Trivial single-unit mission: 1 atomic implementation task + 1 fast validation task."""
        import uuid
        t1_id = uuid.uuid4().hex[:8]
        t2_id = uuid.uuid4().hex[:8]
        prompt_clean = re.sub(r'https?://[^\s<>"\']+', '', user_prompt)
        file_matches = re.findall(r'\b([\w\-/\\]+\.(?:py|html|css|js|txt|md|sh))\b', prompt_clean)
        clean_f = [fm.replace("\\", "/").lstrip("./") for fm in file_matches if not fm.startswith("http")]
        t1 = MissionTask(
            task_id=t1_id,
            title="Implement requested solution",
            description=user_prompt.strip(),
            priority=TaskPriority.CRITICAL,
            skill_hint=self._detect_skill(user_prompt),
            target_paths=clean_f,
            expected_outputs=clean_f,
            write_dependencies=clean_f,
            conflict_keys=[f"write:{f.lower()}" for f in clean_f],
            acceptance_criteria="Requested files and implementation created successfully",
        )
        needs_validation = any(w in user_prompt.lower() for w in ["test", "execute", "benchmark", "validate", "verify", "run "])
        if needs_validation:
            t2 = MissionTask(
                task_id=t2_id,
                title="Verify and validate implementation",
                description=f"Validate that {clean_f or 'the solution'} executes correctly and satisfies requirements.",
                priority=TaskPriority.LOW,
                read_dependencies=clean_f,
                write_dependencies=[],
                conflict_keys=[f"read:{f.lower()}" for f in clean_f],
                depends_on=[t1_id],
                acceptance_criteria="Execution verified without errors",
            )
            t1.dependents = [t2_id]
            return [t1, t2]
        return [t1]

    def _parse_intent(self, prompt: str, execution_mode: str = "production") -> list[str]:
        """
        Parse a user prompt into atomic task descriptions.

        Strategy (in order):
        1. Numbered list detection  (1. ... 2. ...)
        2. Bullet point detection   (- ... * ...)
        2.5 Deterministic multi-file detection (e.g. index.html, styles.css, app.js)
        3. Single atomic command detection (short concise actions)
        4. Natural language separator splitting
        5. LLM decomposition        (freeform prose → atomic tasks via Ollama)
        6. Heuristic sentence split (fallback if Ollama unavailable)
        """
        # Strategy 1: numbered list (strip introductory preamble before first item)
        if re.search(r'(?:^|\n)\s*1[\.\)]\s+', prompt):
            m1 = re.search(r'(?:^|\n)\s*1[\.\)]\s+', prompt)
            list_part = prompt[m1.start():]
            numbered = [re.sub(r'^\d+[\.\)]\s*', '', t.strip()) for t in re.split(r'(?:^|\n)\s*\d+[\.\)]\s+', list_part)]
            numbered = [t for t in numbered if t and len(t) > 3]
            if len(numbered) >= 2:
                return numbered

        # Strategy 2: bullet points (strip introductory preamble before first bullet)
        if re.search(r'(?:^|\n)\s*[-•*]\s+', prompt):
            mb = re.search(r'(?:^|\n)\s*[-•*]\s+', prompt)
            list_part = prompt[mb.start():]
            bulleted = [re.sub(r'^[-•*]\s*', '', t.strip()) for t in re.split(r'(?:^|\n)\s*[-•*]\s+', list_part)]
            bulleted = [t for t in bulleted if t and len(t) > 3]
            if len(bulleted) >= 2:
                return bulleted

        lower = prompt.lower().strip()

        # Strategy 2.5: Website Fast Path & Deterministic Decomposition (Production Mode)
        if execution_mode != "benchmark":
            from core.website_fast_path import WebsiteFastPathClassifier
            fast_path_decision = WebsiteFastPathClassifier.evaluate(prompt, execution_mode=execution_mode)
            if fast_path_decision.fast_path_candidate:
                logger.info(f"MissionPlanner: Website fast path activated: {fast_path_decision.reason}")
                if not fast_path_decision.model_required:
                    # Category A: Fully deterministic (0 model calls)
                    return [f"Execute deterministic website scaffolding for {fast_path_decision.target_files}"]
                # Category B: 1-task coordinated generation preserving user's specific creative requirements
                return [prompt.strip()]

            unique_files = extract_target_artifacts(prompt)
            if len(unique_files) >= 2 and any(kw in lower for kw in ["create", "write", "build", "generate", "make"]):
                logger.info(f"MissionPlanner: deterministic file decomposition detected: {unique_files}")
                tasks = []
                for fn in unique_files:
                    tasks.append(f"Write {fn} with necessary implementation code.")
                if len(tasks) > 6:
                    tasks = self._consolidate_to_milestones(tasks, prompt)
                return tasks

        # Strategy 3: Single atomic task detection (short concise single action)
        words = prompt.strip().split()
        complexity = classify_mission_complexity(prompt)
        is_multi_task_mission = (
            complexity in (MissionComplexity.MEDIUM, MissionComplexity.COMPLEX, MissionComplexity.LARGE)
            or any(w in lower for w in [
                "website", "web app", "webpage", "landing page", "portfolio",
                "animated", "career", "full stack", "full-stack", "frontend and backend",
                "complete app", "flask", "fastapi", "rest api", "crud", "database",
                "models and routes", "backend service"
            ])
        )

        has_multi_task_separator = any(re.search(p, prompt, re.IGNORECASE) for p in [
            r"\band\s+(?:write|create|add|implement|test|push|commit|run|build|generate|make|deploy|set up|init)\b",
            r"\bthen\s+(?:write|create|add|implement|test|push|commit|run|build|generate|make|deploy|set up|init)\b",
            r"\balso\s+(?:write|create|add|implement|test)\b",
            r"\bafter\b", r"\bnext\b", r"\bfinally\b"
        ])

        if not is_multi_task_mission and not has_multi_task_separator:
            return [prompt.strip()]

        # Strategy 4: Natural language separator splitting for concise multi-action prompts
        if has_multi_task_separator and not is_multi_task_mission:
            normalized = prompt
            for pattern in [
                r"\s*\band\s+(?=(?:write|create|add|implement|test|push|commit|run|build|generate|make|deploy|set up|init)\b)",
                r"\s*\bthen\s+(?=(?:write|create|add|implement|test|push|commit|run|build|generate|make|deploy|set up|init)\b)",
                r"\s*\balso\s+(?=(?:write|create|add|implement|test)\b)",
                r"\s*\bafter\b\s*", r"\s*\bnext\b\s*", r"\s*\bfinally\b\s*",
            ]:
                normalized = re.sub(pattern, " |TASK_SPLIT| ", normalized, flags=re.IGNORECASE)
            parts = [p.strip() for p in normalized.split("|TASK_SPLIT|") if p.strip() and len(p.strip()) > 3]
            if len(parts) >= 2:
                return parts
            return [prompt.strip()]

        # Strategy 5: LLM decomposition for freeform prose
        tasks = self._llm_decompose(prompt, execution_mode=execution_mode)
        if tasks and len(tasks) >= 2:
            return tasks

        # Strategy 6: heuristic fallback
        return self._heuristic_decompose(prompt, execution_mode=execution_mode)

    def _llm_decompose(self, prompt: str, execution_mode: str = "production") -> list[str]:
        """
        Call Tier 1 model (TIER1_MODEL) via OllamaClient to decompose a freeform
        mission into ordered atomic implementation tasks.

        Returns a list of task description strings, or empty list on failure.
        """
        import asyncio
        import concurrent.futures
        import json as _json
        from config.model_config import TIER1_PROVIDER, TIER1_MODEL, TIER1_BASE_URL, MODEL_KEEP_ALIVE

        rule_9 = "9. Minimum 8 tasks. Maximum 25 tasks." if execution_mode == "benchmark" else "9. Output at most 4 to 6 high-level engineering milestone tasks. Tasks MUST represent developmental milestones (e.g. Architecture/Setup, Core Markup/UI, Logic/State/Persistence, Features/Filtering, Verification/Testing), NEVER individual micro-tasks or 1 task per file."

        decomposition_system = f"""You are a senior software engineering project manager.
Your job is to decompose a user's software development request into
an ordered list of atomic implementation tasks.

Rules:
1. Each task must be ONE concrete, executable action.
2. Tasks must be in the correct implementation order (dependencies first).
3. Tasks must cover the COMPLETE implementation — not just setup.
4. Include: project structure, all source files, styling, logic,
   data/content, testing, validation, and final verification.
5. For a website: include HTML structure, CSS/animations, JavaScript
   logic, content, responsive design, and browser validation.
6. Never stop at folder creation — always include file creation and
   content writing tasks.
7. Output ONLY a JSON array of task description strings.
8. No explanations. No markdown. Only the JSON array.
{rule_9}
10. Each task string must be specific enough for a developer to act on.
11. All file paths must be relative to the workspace root (e.g. index.html, css/styles.css, js/app.js). Do NOT prefix paths with 'generated_projects/' or create extra wrapping directories unless explicitly asked.

Example output format:
["Establish application architecture and project structure",
 "Implement core UI and markup structure in index.html",
 "Implement styles, layout system, and responsive design in css/styles.css",
 "Implement interactive behavior, state, and local persistence in js/app.js",
 "Integrate search, filtering, and core workflows",
 "Verify application functionality and validate all created files"]"""

        user_message = f"""Decompose this software development request into atomic implementation tasks:

{prompt}

Return a JSON array of task description strings only."""

        try:
            from core.adaptive_routing import get_adaptive_router
            router = get_adaptive_router()
            if not router.is_tier_healthy(1) and execution_mode != "benchmark":
                logger.info("MissionPlanner: Tier 1 circuit is open/unhealthy, fast-pathing to heuristic decomposition")
                return self._heuristic_decompose(prompt, execution_mode=execution_mode)

            if TIER1_PROVIDER == "nvidia_nim":
                from models.nvidia_client import get_shared_nvidia_client
                client = get_shared_nvidia_client()
            else:
                from models.ollama_client import get_shared_ollama_client
                client = get_shared_ollama_client()

            async def _call():
                call_kwargs = {
                    "model": TIER1_MODEL,
                    "prompt": user_message,
                    "system": decomposition_system,
                    "keep_alive": MODEL_KEEP_ALIVE,
                    "temperature": 0.2,
                    "num_ctx": 4096,
                }
                if execution_mode != "benchmark":
                    call_kwargs["think"] = False
                    call_kwargs["num_predict"] = 512
                return await client.generate(**call_kwargs)

            decompose_timeout = 60 if execution_mode == "benchmark" else 5.0
            pool = None
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    fut = pool.submit(asyncio.run, _call())
                    response = fut.result(timeout=decompose_timeout)
                    pool.shutdown(wait=False, cancel_futures=True)
                else:
                    response = loop.run_until_complete(asyncio.wait_for(_call(), timeout=decompose_timeout))
            except (concurrent.futures.TimeoutError, asyncio.TimeoutError):
                if pool is not None:
                    try:
                        pool.shutdown(wait=False, cancel_futures=True)
                    except Exception:
                        pass
                logger.info("MissionPlanner: LLM decomposition timed out (bounded budget), using deterministic fallback")
                return self._heuristic_decompose(prompt, execution_mode=execution_mode)
            except RuntimeError:
                try:
                    response = asyncio.run(asyncio.wait_for(_call(), timeout=decompose_timeout))
                except Exception:
                    return self._heuristic_decompose(prompt, execution_mode=execution_mode)

            raw = response.text.strip()

            # Extract JSON array from response
            import re as _re
            # Try direct parse
            try:
                tasks = _json.loads(raw)
                if isinstance(tasks, list) and len(tasks) >= 2:
                    parsed = [str(t).strip() for t in tasks if str(t).strip()]
                    if execution_mode != "benchmark" and len(parsed) > 6:
                        parsed = self._consolidate_to_milestones(parsed, prompt)
                    return parsed
            except _json.JSONDecodeError:
                pass

            # Try extracting array from response
            match = _re.search(r'\[.*?\]', raw, _re.DOTALL)
            if match:
                try:
                    tasks = _json.loads(match.group())
                    if isinstance(tasks, list) and len(tasks) >= 2:
                        parsed = [str(t).strip() for t in tasks if str(t).strip()]
                        if execution_mode != "benchmark" and len(parsed) > 6:
                            parsed = self._consolidate_to_milestones(parsed, prompt)
                        return parsed
                except _json.JSONDecodeError:
                    pass

            logger.warning(f"MissionPlanner LLM decompose: could not parse JSON from response")
            return self._heuristic_decompose(prompt, execution_mode=execution_mode)

        except Exception as e:
            logger.warning(f"MissionPlanner LLM decompose failed: {e}")
            return self._heuristic_decompose(prompt, execution_mode=execution_mode)

    async def _llm_decompose_async(self, prompt: str, execution_mode: str = "production") -> list[str]:
        """Asynchronous non-blocking decomposition using shared persistent client."""
        import json as _json
        from config.model_config import TIER1_PROVIDER, TIER1_MODEL, MODEL_KEEP_ALIVE

        rule_9 = "9. Minimum 8 tasks. Maximum 25 tasks." if execution_mode == "benchmark" else "9. Output at most 4 to 6 high-level engineering milestone tasks. Tasks MUST represent developmental milestones (e.g. Architecture/Setup, Core Markup/UI, Logic/State/Persistence, Features/Filtering, Verification/Testing), NEVER individual micro-tasks or 1 task per file."

        decomposition_system = f"""You are a senior software engineering project manager.
Your job is to decompose a user's software development request into
an ordered list of atomic implementation tasks.

Rules:
1. Each task must be ONE concrete, executable action.
2. Tasks must be in the correct implementation order (dependencies first).
3. Tasks must cover the COMPLETE implementation — not just setup.
4. Include: project structure, all source files, styling, logic,
   data/content, testing, validation, and final verification.
5. For a website: include HTML structure, CSS/animations, JavaScript
   logic, content, responsive design, and browser validation.
6. Never stop at folder creation — always include file creation and
   content writing tasks.
7. Return a JSON array of strings — nothing else.
8. Do NOT include markdown fences, explanations, or preamble.
{rule_9}
10. All file paths must be relative to the workspace root (e.g. index.html, css/styles.css, js/app.js). Do NOT prefix paths with 'generated_projects/' or create extra wrapping directories unless explicitly asked.

Example output format:
["Establish application architecture and project structure",
 "Implement core UI and markup structure in index.html",
 "Implement styles, layout system, and responsive design in css/styles.css",
 "Implement interactive behavior, state, and local persistence in js/app.js",
 "Integrate search, filtering, and core workflows",
 "Verify application functionality and validate all created files"]"""

        user_message = f"""Decompose this software development request into atomic implementation tasks:

{prompt}

Return a JSON array of task description strings only."""

        try:
            from core.adaptive_routing import get_adaptive_router
            router = get_adaptive_router()
            if not router.is_tier_healthy(1) and execution_mode != "benchmark":
                logger.info("MissionPlanner: Tier 1 circuit is open/unhealthy, fast-pathing to rule-based decomposition")
                return self._rule_based_decompose(prompt)

            if TIER1_PROVIDER == "nvidia_nim":
                from models.nvidia_client import get_shared_nvidia_client
                client = get_shared_nvidia_client()
            else:
                from models.ollama_client import get_shared_ollama_client
                client = get_shared_ollama_client()

            call_kwargs = {
                "model": TIER1_MODEL,
                "prompt": user_message,
                "system": decomposition_system,
                "keep_alive": MODEL_KEEP_ALIVE,
                "temperature": 0.2,
                "num_ctx": 4096,
            }
            if execution_mode != "benchmark":
                call_kwargs["think"] = False
                call_kwargs["num_predict"] = 512

            response = await client.generate(**call_kwargs)
            raw = response.text.strip()

            import re as _re
            try:
                tasks = _json.loads(raw)
                if isinstance(tasks, list) and len(tasks) >= 2:
                    parsed = [str(t).strip() for t in tasks if str(t).strip()]
                    if execution_mode != "benchmark" and len(parsed) > 6:
                        parsed = self._consolidate_to_milestones(parsed, prompt)
                    return parsed
            except _json.JSONDecodeError:
                pass

            match = _re.search(r'\[.*?\]', raw, _re.DOTALL)
            if match:
                try:
                    tasks = _json.loads(match.group())
                    if isinstance(tasks, list) and len(tasks) >= 2:
                        parsed = [str(t).strip() for t in tasks if str(t).strip()]
                        if execution_mode != "benchmark" and len(parsed) > 6:
                            parsed = self._consolidate_to_milestones(parsed, prompt)
                        return parsed
                except _json.JSONDecodeError:
                    pass

            return []
        except Exception as e:
            logger.warning(f"MissionPlanner async decompose failed: {e}")
            return []

    async def _parse_intent_async(self, prompt: str, execution_mode: str = "production", workspace_root: str = "") -> list[str]:
        """Asynchronous non-blocking intent parsing."""
        import re
        lines = [line.strip() for line in prompt.strip().split('\n') if line.strip()]

        numbered = [re.sub(r'^\d+[\.\)]\s*', '', t) for t in lines if re.match(r'^\d+[\.\)]\s+', t)]
        numbered = [t for t in numbered if t and len(t) > 3]
        if len(numbered) >= 2:
            return numbered

        bulleted = [re.sub(r'^[-•*]\s*', '', t.strip()) for t in re.split(r'\n\s*[-•*]\s+', prompt)]
        bulleted = [t for t in bulleted if t and len(t) > 3]
        if len(bulleted) >= 2:
            return bulleted

        lower = prompt.lower().strip()

        if execution_mode != "benchmark":
            from core.website_fast_path import WebsiteFastPathClassifier
            fast_path_decision = WebsiteFastPathClassifier.evaluate(prompt, execution_mode=execution_mode)
            if fast_path_decision.fast_path_candidate:
                logger.info(f"MissionPlanner: Website fast path activated: {fast_path_decision.reason}")
                if not fast_path_decision.model_required:
                    return [f"Execute deterministic website scaffolding for {fast_path_decision.target_files}"]
                return [prompt.strip()]

            unique_files = extract_target_artifacts(prompt)
            if len(unique_files) >= 2 and any(kw in lower for kw in ["create", "write", "build", "generate", "make"]):
                tasks = []
                for fn in unique_files:
                    tasks.append(f"Write {fn} with necessary implementation code.")
                if len(tasks) > 6:
                    tasks = self._consolidate_to_milestones(tasks, prompt)
                return tasks

        is_complex_mission = any(w in lower for w in [
            "website", "web app", "webpage", "landing page", "portfolio",
            "animated", "career", "full stack", "frontend and backend",
            "complete app"
        ])

        has_multi_task_separator = any(re.search(p, prompt, re.IGNORECASE) for p in [
            r"\band\s+(?:write|create|add|implement|test|push|commit|run|build|generate|make|deploy|set up|init)\b",
            r"\bthen\s+(?:write|create|add|implement|test|push|commit|run|build|generate|make|deploy|set up|init)\b",
            r"\balso\s+(?:write|create|add|implement|test)\b",
            r"\bafter\b", r"\bnext\b", r"\bfinally\b"
        ])

        if not is_complex_mission and not has_multi_task_separator:
            return [prompt.strip()]

        if has_multi_task_separator and not is_complex_mission:
            normalized = prompt
            for pattern in [
                r"\s*\band\s+(?=(?:write|create|add|implement|test|push|commit|run|build|generate|make|deploy|set up|init)\b)",
                r"\s*\bthen\s+(?=(?:write|create|add|implement|test|push|commit|run|build|generate|make|deploy|set up|init)\b)",
                r"\s*\balso\s+(?=(?:write|create|add|implement|test)\b)",
                r"\s*\bafter\b\s*", r"\s*\bnext\b\s*", r"\s*\bfinally\b\s*",
            ]:
                normalized = re.sub(pattern, " |TASK_SPLIT| ", normalized, flags=re.IGNORECASE)
            parts = [p.strip() for p in normalized.split("|TASK_SPLIT|") if p.strip() and len(p.strip()) > 3]
            if len(parts) >= 2:
                return parts
            return [prompt.strip()]

        tasks = await self._llm_decompose_async(prompt, execution_mode=execution_mode)
        if tasks and len(tasks) >= 2:
            return tasks

        return self._heuristic_decompose(prompt, execution_mode=execution_mode, workspace_root=workspace_root)

    async def plan_async(self, user_prompt: str, workspace_root: str = "", execution_mode: str = "production") -> Mission:
        """Asynchronous non-blocking planning method."""
        mission = Mission(
            user_prompt=user_prompt,
            workspace_root=workspace_root,
        )

        # Step 0: Authoritative Architecture Lock
        from core.architecture_lock import ArchitectureLock, detect_architecture
        arch = detect_architecture(user_prompt, workspace_root=workspace_root)
        mission.architecture_decision = arch
        ArchitectureLock.lock(arch, mission_id=mission.mission_id)

        # Step 0.5: Phase 4E Mission Complexity Classification
        complexity = classify_mission_complexity(user_prompt, workspace_root=workspace_root)
        mission.complexity = complexity
        logger.info(f"MissionPlanner async: classified mission complexity={complexity.value}")

        if complexity == MissionComplexity.SIMPLE:
            tasks = self._plan_simple_mission(user_prompt, workspace_root=workspace_root, arch=arch)
        elif complexity == MissionComplexity.TRIVIAL:
            tasks = self._plan_trivial_mission(user_prompt, workspace_root=workspace_root, arch=arch)
        else:
            raw_tasks = await self._parse_intent_async(user_prompt, execution_mode=execution_mode, workspace_root=workspace_root)
            if execution_mode != "benchmark" and len(raw_tasks) > 6:
                raw_tasks = self._consolidate_to_milestones(raw_tasks, user_prompt)
            logger.info(f"MissionPlanner: parsed {len(raw_tasks)} tasks from prompt | mode={execution_mode}")

            if not raw_tasks:
                raw_tasks = [user_prompt.strip()]

            tasks: list[MissionTask] = []
            for i, raw in enumerate(raw_tasks):
                raw_clean = re.sub(r'https?://[^\s<>"\']+', '', raw)
                f_matches = re.findall(r'\b([\w\-/\\]+\.(?:html|css|json|jsx|js|py|md|tsx|ts|sql|sh))\b', raw_clean, re.IGNORECASE)
                clean_f = [fm.replace("\\", "/").lstrip("./") for fm in f_matches if not fm.startswith("http")]
                task = MissionTask(
                    title=self._generate_title(raw),
                    description=raw.strip(),
                    priority=self._assign_priority(raw, i),
                    skill_hint=self._detect_skill(raw),
                    acceptance_criteria=self._generate_acceptance_criteria(raw),
                    target_paths=clean_f,
                    write_dependencies=clean_f,
                    conflict_keys=[f"write:{cf.lower()}" for cf in clean_f],
                )
                tasks.append(task)

        inspection_task = MissionTask(
            title="Inspect workspace and existing files",
            description=(
                f"Before implementing anything, inspect the workspace at "
                f"{workspace_root or 'workspace root'} to understand "
                f"what already exists. Use list_directory and read_file to "
                f"read the most relevant existing files. Identify: "
                f"(1) what files already exist, "
                f"(2) what framework/technology is in use, "
                f"(3) what code can be reused, "
                f"(4) what needs to be created from scratch. "
                f"Report findings clearly."
            ),
            priority=TaskPriority.CRITICAL,
            skill_hint="",
            acceptance_criteria="Workspace structure and existing files inspected",
            required_tools=["list_directory", "read_file"],
        )

        # Only prepend inspection task if we have a complex multi-page website/app mission
        lower_prompt = user_prompt.lower()
        is_complex_mission = any(w in lower_prompt for w in [
            "website", "web app", "webpage", "landing page", "portfolio",
            "animated", "career", "full stack", "frontend and backend", "complete app"
        ])
        
        should_inspect = is_complex_mission
        if execution_mode != "benchmark":
            from pathlib import Path
            target_check = Path(workspace_root) if workspace_root else Path("generated_projects")
            try:
                existing_files = [f for f in target_check.glob("*") if not f.name.startswith(".")] if target_check.exists() else []
                existing_count = len(existing_files)
            except Exception:
                existing_count = 0
            if existing_count == 0:
                should_inspect = False

        if len(tasks) > 1 and should_inspect:
            if not any(t.description.lower().startswith("inspect") for t in tasks):
                tasks.insert(0, inspection_task)

        if execution_mode != "benchmark" and len(tasks) > 6:
            tasks = tasks[:6]

        self._assign_dependencies(tasks)
        sorted_ids = self._topological_sort(tasks)

        mission.tasks = tasks
        mission.execution_order = sorted_ids
        mission.acceptance_criteria = self._derive_acceptance_criteria(
            user_prompt, tasks
        )
        mission.project_root_path = self._detect_project_root(
            user_prompt, workspace_root=workspace_root
        )

        return mission

    def _heuristic_decompose(self, prompt: str, execution_mode: str = "production", workspace_root: str = "") -> list[str]:
        """
        Fallback heuristic decomposition for when Ollama is unavailable.
        Detects the request type and generates a sensible task list.
        """
        lower = prompt.lower()
        tasks = []

        # Detect project type
        is_website = any(w in lower for w in [
            "website", "web app", "webpage", "html", "css", "frontend",
            "landing page", "portfolio", "web application", "board", "event board", "dashboard", "portal", "page"
        ])
        is_flask_api = any(w in lower for w in [
            "flask", "rest api", "api", "backend", "endpoint", "fastapi", "service", "database", "sqlite", "crud"
        ])
        is_react = any(w in lower for w in ["react", "jsx", "component", "next.js"])

        # Extract project name hint
        import re as _re
        name_match = _re.search(
            r'called?\s+["\']?(\w+)["\']?|named?\s+["\']?(\w+)["\']?|'
            r'project\s+["\']?(\w+)["\']?',
            prompt, _re.IGNORECASE
        )
        project_name = "myproject"
        if name_match:
            project_name = (
                name_match.group(1) or name_match.group(2) or name_match.group(3)
                or "myproject"
            ).lower()

        from core.workspace import global_workspace
        if "generated_projects" in prompt.lower():
            base_prefix = f"generated_projects/{project_name}/"
        else:
            base_prefix = ""

        if execution_mode != "benchmark":
            complexity = classify_mission_complexity(prompt)
            if complexity in (MissionComplexity.COMPLEX, MissionComplexity.LARGE) or any(w in lower for w in [
                "full-stack", "full stack", "oauth", "jwt", "worker", "microservices", "platform", "celery", "distributed"
            ]):
                return [
                    f"Establish system architecture, dependency configuration, and project structure directly in {base_prefix or '.'}",
                    f"Implement database models, migration schemas, and persistence layer",
                    f"Implement core business logic, service components, and API endpoints",
                    f"Implement authentication, authorization middleware, and security controls",
                    f"Implement asynchronous tasks, background workers, and queue handlers",
                    f"Implement comprehensive unit and integration test suites",
                    f"Verify and validate full system integration and end-to-end functionality in {base_prefix or '.'}",
                ]
            if is_flask_api:
                return [
                    f"Establish project structure and configuration at {base_prefix or '.'}",
                    f"Implement database models and schema definitions",
                    f"Implement REST API endpoints, routing, and request validation",
                    f"Implement business logic, error handlers, and middleware",
                    f"Implement automated tests and verification suite",
                    f"Verify and validate API endpoints and service functionality in {base_prefix or '.'}",
                ]
            if is_website:
                return [
                    f"Establish application architecture and project structure directly in {base_prefix or '.'}",
                    f"Implement core UI markup and semantic layout in {base_prefix}index.html",
                    f"Implement complete visual styling, design system, and responsive layout in {base_prefix}styles.css",
                    f"Implement interactive logic, state management, and localStorage persistence in {base_prefix}app.js",
                    f"Integrate search, category filtering, item details, and user interaction workflows",
                    f"Verify and validate full application functionality across all components in {base_prefix or '.'}",
                ]
            clean_desc = prompt.strip().replace("\n", " ")
            if len(clean_desc) > 160:
                clean_desc = clean_desc[:157] + "..."
            tasks = [
                f"Implement the requested project ({clean_desc}) directly in {base_prefix or '.'}",
                f"Verify and validate all created files in {base_prefix or '.'} for completeness and correctness",
            ]
            return tasks


        if is_website:
            tasks = [
                f"Create the project folder structure with subfolders css/ js/ assets/",
                f"Create {base_prefix}index.html with complete semantic HTML5 including header navigation hero section about features and footer",
                f"Create {base_prefix}css/styles.css with CSS custom properties colour palette typography base reset and layout system",
                f"Add CSS animations in {base_prefix}css/animations.css including fade-in slide-up parallax and hover transition effects",
                f"Create {base_prefix}js/app.js with smooth scroll navigation intersection observer for scroll animations and interactive logic",
                f"Implement the main content sections with real text headlines descriptions and calls to action in index.html",
                f"Add responsive design breakpoints in styles.css for mobile 320px tablet 768px and desktop 1200px",
                f"Polish the visual design in styles.css with gradients shadows card components and professional typography scale",
                f"Open {base_prefix}index.html and verify the page structure with read_file",
                f"Check all required files exist and are non-empty with list_directory {base_prefix or '.'}",
                f"Review index.html content to verify all requested sections are implemented",
            ]
            if any(w in lower for w in ["questionnaire", "quiz", "form", "survey"]):
                tasks.insert(7, f"Create {base_prefix}js/questionnaire.js with interactive questionnaire logic")
        elif is_flask_api:
            tasks = [
                f"Create project structure at {base_prefix} with app/ models/ routes/ config.py requirements.txt",
                f"Create {base_prefix}config.py with Flask configuration database URI and secret key",
                f"Create {base_prefix}app/__init__.py with Flask application factory and extension registration",
                f"Create {base_prefix}app/models.py with SQLAlchemy 2.0 database models",
                f"Create {base_prefix}app/routes.py with all requested API endpoints",
                f"Create {base_prefix}requirements.txt with flask flask-sqlalchemy and dependencies",
                f"Create {base_prefix}run.py as the application entry point",
                f"Write pytest tests in {base_prefix}tests/test_api.py for all endpoints",
                f"Run the tests and verify they pass",
                f"Verify the application structure is complete with list_directory {base_prefix or '.'}",
            ]
        else:
            # Generic software project
            tasks = [
                f"Analyze the request and create the project folder structure at {base_path}/",
                f"Create the main application entry point file with appropriate implementation",
                f"Create supporting modules and files required by the application",
                f"Implement the core functionality described in the request",
                f"Add error handling validation and edge case coverage",
                f"Write tests to verify the implementation works correctly",
                f"Run the tests and fix any failures",
                f"Verify all requested functionality is implemented and working",
            ]

    def _consolidate_to_milestones(self, raw_tasks: list[str], prompt: str) -> list[str]:
        """
        Consolidate an exploded task list into at most 6 cohesive engineering milestones.
        In production mode, task count represents milestones, not individual files.
        """
        if len(raw_tasks) <= 6:
            return raw_tasks

        p_lower = prompt.lower()
        is_website = any(w in p_lower for w in [
            "website", "web app", "webpage", "html", "css", "lost and found", "lost-and-found", "frontend", "landing page"
        ])
        if is_website:
            return [
                "Establish application architecture and project structure",
                "Implement core UI markup and semantic layout in index.html",
                "Implement complete styles, layout system, and responsive design in styles.css",
                "Implement interactive behavior, state management, and local persistence in app.js",
                "Integrate search, filtering, item management, and resolution workflows",
                "Verify and validate full application functionality across all components",
            ]

        is_api = any(w in p_lower for w in ["flask", "fastapi", "rest api", "backend", "endpoint"])
        if is_api:
            return [
                "Establish project structure, dependencies, and configuration",
                "Implement data models and database storage schemas",
                "Implement business services and API endpoint routes",
                "Implement error handling, validation, and security middleware",
                "Implement automated test suites and verify all endpoints",
                "Final validation and documentation",
            ]

        # General software engineering milestones: chunk into <= 6
        total = len(raw_tasks)
        max_milestones = 6
        chunk_size = (total + max_milestones - 1) // max_milestones
        milestones = []
        for i in range(0, total, chunk_size):
            chunk = raw_tasks[i : i + chunk_size]
            first = chunk[0].strip().rstrip(".")
            if len(chunk) == 1:
                milestones.append(first)
            else:
                summary = f"{first} and related components ({len(chunk)} actions)"
                milestones.append(summary)
            if len(milestones) == max_milestones:
                break
        return milestones[:6]

    def _derive_acceptance_criteria(
        self, prompt: str, tasks: list[MissionTask]
    ) -> list[str]:
        """
        Derive measurable acceptance criteria from the user's prompt and
        planned tasks. These are checked before MISSION COMPLETE is declared.
        """
        criteria = []
        lower = prompt.lower()

        # Always require: at least one file created
        criteria.append("At least one file must be created (not just folders)")

        # Website criteria
        if any(w in lower for w in ["website", "web app", "webpage", "html"]):
            criteria.append("index.html must exist and be non-empty")
            if not any(w in lower for w in ["single html", "single html page", "single-page", "single page"]):
                criteria.append("CSS styling file must exist and be non-empty")
            if "animat" in lower:
                criteria.append("CSS or JS animation implementation must be present")
            if "responsive" in lower or "mobile" in lower:
                criteria.append("Responsive design breakpoints must be present")
            if "questionnaire" in lower or "quiz" in lower or "question" in lower:
                criteria.append("Questionnaire or interactive form must be implemented")

        # Flask/API criteria
        if any(w in lower for w in ["flask", "api", "backend", "endpoint"]):
            criteria.append("Flask application file must exist and be non-empty")
            criteria.append("At least one route or endpoint must be defined")

        # Test criteria
        if any(w in lower for w in ["test", "pytest", "spec"]):
            criteria.append("Test file must exist with actual test functions")

        # Generic: check tasks produced actual file writes
        write_tasks = [
            t for t in tasks
            if any(w in t.description.lower() for w in [
                "write", "create", "implement", "add", "build", "generate"
            ])
        ]
        if len(write_tasks) > 0:
            criteria.append(
                f"At least {min(3, len(write_tasks))} implementation files "
                f"must be created with content"
            )

        return criteria

    def _detect_project_root(self, prompt: str, workspace_root: str = "") -> str:
        """
        Detect the project root path that will be used for this mission.
        Returns the canonical absolute or normalized directory path.
        Guarantees that 'generated_projects/' is NEVER added automatically.
        """
        import re as _re
        from pathlib import Path

        # If prompt explicitly targets a file or directory in generated_projects
        gp_match = _re.search(r'generated_projects/([\w\-\./]+)', prompt, _re.IGNORECASE)
        if gp_match:
            target = gp_match.group(1)
            p = Path(target)
            if p.suffix:  # It's a file like synth_probe.py or myapp/main.py
                if p.parent != Path("."):
                    return f"generated_projects/{p.parent}"
                return "generated_projects"
            return f"generated_projects/{target}"

        # If workspace_root is provided, canonicalize and return it
        if workspace_root:
            return str(Path(workspace_root).resolve())

        from core.workspace import global_workspace, workspace_manager
        wm = global_workspace if (global_workspace and global_workspace.is_locked) else workspace_manager
        if wm and wm.root_str:
            return str(Path(wm.root_str).resolve())

        return str(Path.cwd().resolve())

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

    def _assign_priority(self, description: str, index: int = 0) -> TaskPriority:
        """Assign priority based on task type and position."""
        lower = description.lower()

        # Setup and architecture tasks always go first
        if any(kw in lower for kw in ["init", "setup", "install", "create project",
                                       "folder structure", "initialize", "architecture", "establish"]):
            return TaskPriority.CRITICAL

        # Final verification and validation tasks must NOT outrank implementation tasks
        if any(kw in lower for kw in ["verify", "validate", "acceptance", "completeness", "audit"]):
            return TaskPriority.LOW

        # Standalone tests
        if any(kw in lower for kw in ["test", "pytest"]):
            return TaskPriority.NORMAL

        # Documentation and cleanup
        if any(kw in lower for kw in ["readme", "documentation", "docs",
                                       "comment", "cleanup"]):
            return TaskPriority.LOW

        # Git operations typically last
        if any(kw in lower for kw in ["push", "commit", "deploy", "publish"]):
            return TaskPriority.LOW

        # Default: core implementation tasks get HIGH priority (ordered early)
        if index <= 3:
            return TaskPriority.HIGH
        return TaskPriority.NORMAL

    def _detect_skill(self, description: str) -> str:
        """Detect which SKILL.md file is most relevant for this task."""
        lower = description.lower()
        try:
            from core.architecture_lock import ArchitectureLock, ArchitectureType
            arch = ArchitectureLock.get_current()
        except Exception:
            arch = None

        for keyword, skill in SKILL_KEYWORD_MAP.items():
            if keyword in lower:
                if arch and not arch.is_skill_allowed(skill):
                    continue
                return skill

        if arch and arch.architecture_type == ArchitectureType.VANILLA_WEB:
            return "vanilla-web"
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
        Build meaningful semantic task dependencies based on task roles, artifacts, and flow.
        Rules:
        1. Architecture / setup tasks precede core implementation tasks.
        2. Core implementation tasks precede integration tasks touching the same files or subsystems.
        3. Integration tasks precede end-to-end verification.
        4. Verification / validation tasks depend on ALL prior implementation and integration tasks.
        5. Tasks modifying the same target artifact are serialized.
        """
        def _get_role(task: MissionTask) -> str:
            lower = (task.title + " " + task.description).lower()
            if task.is_verification_task or any(kw in lower for kw in ["verify", "validate", "validation", "acceptance", "completeness", "audit"]):
                return "VERIFICATION"
            if any(kw in lower for kw in ["init", "setup", "initialize", "scaffold", "architecture", "structure", "folder structure", "establish"]):
                return "SCAFFOLD"
            if any(kw in lower for kw in ["integrate", "wiring", "cross-file", "workflow", "interaction", "filtering", "search and filter", "item management", "resolution"]):
                return "INTEGRATION"
            return "IMPLEMENTATION"

        roles = [_get_role(t) for t in tasks]

        for i, task_a in enumerate(tasks):
            role_a = roles[i]
            title_a = task_a.title.lower()
            targets_a = set(task_a.target_paths or task_a.expected_outputs or task_a.required_files)

            for j, task_b in enumerate(tasks):
                if i == j:
                    continue
                role_b = roles[j]
                title_b = task_b.title.lower()
                targets_b = set(task_b.target_paths or task_b.expected_outputs or task_b.required_files)

                # Rule 1: Implementation & Integration tasks depend on Scaffold if scaffold comes before
                if role_b == "SCAFFOLD" and role_a in ("IMPLEMENTATION", "INTEGRATION", "VERIFICATION") and i > j:
                    if task_b.task_id not in task_a.depends_on:
                        task_a.depends_on.append(task_b.task_id)

                # Rule 2: Integration tasks depend on prior Implementation tasks
                if role_b == "IMPLEMENTATION" and role_a == "INTEGRATION" and i > j:
                    if task_b.task_id not in task_a.depends_on:
                        task_a.depends_on.append(task_b.task_id)

                # Rule 3: Verification tasks depend on ALL prior implementation, scaffold, and integration tasks
                if role_a == "VERIFICATION" and role_b in ("SCAFFOLD", "IMPLEMENTATION", "INTEGRATION") and i > j:
                    if task_b.task_id not in task_a.depends_on:
                        task_a.depends_on.append(task_b.task_id)

                # Rule 4: Shared target artifact serialization (prevent race conditions)
                if targets_a and targets_b and (targets_a & targets_b) and i > j:
                    if task_b.task_id not in task_a.depends_on:
                        task_a.depends_on.append(task_b.task_id)

                # Rule 5: Keyword heuristics
                for dependent_kw, prerequisite_kw in DEPENDENCY_HEURISTICS:
                    if dependent_kw in title_a and prerequisite_kw in title_b and i > j:
                        if task_b.task_id not in task_a.depends_on:
                            task_a.depends_on.append(task_b.task_id)
                            break

        # Ensure no self-references or circular deps
        for task in tasks:
            task.depends_on = [d for d in task.depends_on if d != task.task_id]

        # Populate dependents list on each task
        for task in tasks:
            task.dependents = [o.task_id for o in tasks if task.task_id in o.depends_on]

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
            key=lambda tid: task_map[tid].priority.value if hasattr(task_map[tid].priority, 'value') else int(task_map[tid].priority)
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
