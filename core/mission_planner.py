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
    required_files: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    required_content_keywords: list[str] = field(default_factory=list)
    is_verified: bool = False
    verification_evidence: str = ""

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
    user_prompt: str = ""
    tasks: list[MissionTask] = field(default_factory=list)
    execution_order: list[str] = field(default_factory=list)  # task_ids in topological order
    workspace_root: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    verified_criteria: list[str] = field(default_factory=list)
    project_root_path: str = ""

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
        mission = Mission(
            user_prompt=user_prompt,
            workspace_root=workspace_root,
        )

        # Step 1: Parse into raw task descriptions
        raw_tasks = self._parse_intent(user_prompt, execution_mode=execution_mode)
        logger.info(f"MissionPlanner: parsed {len(raw_tasks)} tasks from prompt | mode={execution_mode}")

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

        # Always start with workspace inspection
        # This gives the model ground truth about what exists before generating
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
            existing_count = len(list(target_check.glob("*"))) if target_check.exists() else 0
            if existing_count == 0:
                should_inspect = False

        if len(tasks) > 1 and should_inspect:
            tasks.insert(0, inspection_task)

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
        # Detect the project root path that will be created
        mission.project_root_path = self._detect_project_root(user_prompt, workspace_root=workspace_root)

        logger.info(
            f"MissionPlanner: mission {mission.mission_id} | "
            f"{len(tasks)} tasks | order: {[t.title[:20] for t in tasks]}"
        )
        return mission

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
        # Strategy 1: numbered list
        numbered = [re.sub(r'^\d+[\.\)]\s*', '', t.strip()) for t in re.split(r'\n\s*\d+[\.\)]\s+', prompt)]
        numbered = [t for t in numbered if t and len(t) > 3]
        if len(numbered) >= 2:
            return numbered

        # Strategy 2: bullet points
        bulleted = [re.sub(r'^[-•*]\s*', '', t.strip()) for t in re.split(r'\n\s*[-•*]\s+', prompt)]
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

            file_matches = re.findall(r'\b([\w\-]+\.(?:html|css|js|py|json|md|txt|ts|tsx|jsx|sql|sh))\b', prompt, re.IGNORECASE)
            unique_files = list(dict.fromkeys(file_matches))
            if len(unique_files) >= 2 and any(kw in lower for kw in ["create", "write", "build", "generate", "make"]):
                logger.info(f"MissionPlanner: deterministic file decomposition detected: {unique_files}")
                tasks = []
                for fn in unique_files:
                    tasks.append(f"Write {fn} for EduPath Mini website with necessary code.")
                return tasks

        # Strategy 3: Single atomic task detection (short concise single action)
        words = prompt.strip().split()
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

        # Strategy 4: Natural language separator splitting for concise multi-action prompts
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

        # Strategy 5: LLM decomposition for freeform prose
        tasks = self._llm_decompose(prompt, execution_mode=execution_mode)
        if tasks and len(tasks) >= 2:
            return tasks

        # Strategy 6: heuristic fallback
        return self._heuristic_decompose(prompt)

    def _llm_decompose(self, prompt: str, execution_mode: str = "production") -> list[str]:
        """
        Call Tier 1 model (TIER1_MODEL) via OllamaClient to decompose a freeform
        mission into ordered atomic implementation tasks.

        Returns a list of task description strings, or empty list on failure.
        """
        import asyncio
        import json as _json
        from config.model_config import TIER1_PROVIDER, TIER1_MODEL, TIER1_BASE_URL, MODEL_KEEP_ALIVE

        rule_9 = "9. Minimum 8 tasks. Maximum 25 tasks." if execution_mode == "benchmark" else "9. Output ONLY the necessary tasks (typically 1 to 5 tasks). Do not create artificial micro-tasks."

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

Example output format:
["Create project folder structure at generated_projects/myapp/",
 "Create index.html with full semantic HTML5 structure",
 "Create styles.css with styling and layout",
 "Create app.js with logic and event listeners"]"""

        user_message = f"""Decompose this software development request into atomic implementation tasks:

{prompt}

Return a JSON array of task description strings only."""

        try:
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

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        fut = pool.submit(asyncio.run, _call())
                        response = fut.result(timeout=60)
                else:
                    response = loop.run_until_complete(_call())
            except RuntimeError:
                response = asyncio.run(_call())

            raw = response.text.strip()

            # Extract JSON array from response
            import re as _re
            # Try direct parse
            try:
                tasks = _json.loads(raw)
                if isinstance(tasks, list) and len(tasks) >= 2:
                    return [str(t).strip() for t in tasks if str(t).strip()]
            except _json.JSONDecodeError:
                pass

            # Try extracting array from response
            match = _re.search(r'\[.*?\]', raw, _re.DOTALL)
            if match:
                try:
                    tasks = _json.loads(match.group())
                    if isinstance(tasks, list) and len(tasks) >= 2:
                        return [str(t).strip() for t in tasks if str(t).strip()]
                except _json.JSONDecodeError:
                    pass

            logger.warning(f"MissionPlanner LLM decompose: could not parse JSON from response")
            return []

        except Exception as e:
            logger.warning(f"MissionPlanner LLM decompose failed: {e}")
            return []

    async def _llm_decompose_async(self, prompt: str, execution_mode: str = "production") -> list[str]:
        """Asynchronous non-blocking decomposition using shared persistent client."""
        import json as _json
        from config.model_config import TIER1_PROVIDER, TIER1_MODEL, MODEL_KEEP_ALIVE

        rule_9 = "9. Minimum 8 tasks. Maximum 25 tasks." if execution_mode == "benchmark" else "9. Output ONLY the necessary tasks (typically 1 to 5 tasks). Do not create artificial micro-tasks."

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

Example output format:
["Create project folder structure at generated_projects/myapp/",
 "Create index.html with full semantic HTML5 structure",
 "Create styles.css with styling and layout",
 "Create app.js with logic and event listeners"]"""

        user_message = f"""Decompose this software development request into atomic implementation tasks:

{prompt}

Return a JSON array of task description strings only."""

        try:
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
                    return [str(t).strip() for t in tasks if str(t).strip()]
            except _json.JSONDecodeError:
                pass

            match = _re.search(r'\[.*?\]', raw, _re.DOTALL)
            if match:
                try:
                    tasks = _json.loads(match.group())
                    if isinstance(tasks, list) and len(tasks) >= 2:
                        return [str(t).strip() for t in tasks if str(t).strip()]
                except _json.JSONDecodeError:
                    pass

            return []
        except Exception as e:
            logger.warning(f"MissionPlanner async decompose failed: {e}")
            return []

    async def _parse_intent_async(self, prompt: str, execution_mode: str = "production") -> list[str]:
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

            file_matches = re.findall(r'\b([\w\-]+\.(?:html|css|js|py|json|md|txt|ts|tsx|jsx|sql|sh))\b', prompt, re.IGNORECASE)
            unique_files = list(dict.fromkeys(file_matches))
            if len(unique_files) >= 2 and any(kw in lower for kw in ["create", "write", "build", "generate", "make"]):
                tasks = []
                for fn in unique_files:
                    tasks.append(f"Write {fn} for EduPath Mini website with necessary code.")
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

        return self._heuristic_decompose(prompt)

    async def plan_async(self, user_prompt: str, workspace_root: str = "", execution_mode: str = "production") -> Mission:
        """Asynchronous non-blocking planning method."""
        mission = Mission(
            user_prompt=user_prompt,
            workspace_root=workspace_root,
        )

        raw_tasks = await self._parse_intent_async(user_prompt, execution_mode=execution_mode)
        logger.info(f"MissionPlanner: parsed {len(raw_tasks)} tasks from prompt | mode={execution_mode}")

        if not raw_tasks:
            raw_tasks = [user_prompt.strip()]

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
                existing_count = len(list(target_check.glob("*"))) if target_check.exists() else 0
            except Exception:
                existing_count = 0
            if existing_count == 0:
                should_inspect = False

        if len(tasks) > 1 and should_inspect:
            if not any(t.description.lower().startswith("inspect") for t in tasks):
                tasks.insert(0, inspection_task)

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

    def _heuristic_decompose(self, prompt: str) -> list[str]:
        """
        Fallback heuristic decomposition for when Ollama is unavailable.
        Detects the request type and generates a sensible task list.
        """
        lower = prompt.lower()
        tasks = []

        # Detect project type
        is_website = any(w in lower for w in [
            "website", "web app", "webpage", "html", "css", "frontend",
            "landing page", "portfolio", "web application"
        ])
        is_flask_api = any(w in lower for w in [
            "flask", "rest api", "api", "backend", "endpoint", "fastapi"
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

        base_path = f"generated_projects/{project_name}"

        if is_website:
            tasks = [
                f"Create the project folder structure at {base_path}/ with subfolders css/ js/ assets/",
                f"Create {base_path}/index.html with complete semantic HTML5 including header navigation hero section about features and footer",
                f"Create {base_path}/css/styles.css with CSS custom properties colour palette typography base reset and layout system",
                f"Add CSS animations in {base_path}/css/animations.css including fade-in slide-up parallax and hover transition effects",
                f"Create {base_path}/js/app.js with smooth scroll navigation intersection observer for scroll animations and interactive logic",
                f"Implement the main content sections with real text headlines descriptions and calls to action in index.html",
                f"Add responsive design breakpoints in styles.css for mobile 320px tablet 768px and desktop 1200px",
                f"Create {base_path}/js/questionnaire.js with interactive questionnaire logic if the request requires user interaction",
                f"Polish the visual design in styles.css with gradients shadows card components and professional typography scale",
                f"Run bash_exec to open {base_path}/index.html and verify the page structure with cat command",
                f"Check all required files exist and are non-empty with ls -la {base_path}/",
                f"Review index.html content to verify all requested sections are implemented",
            ]
        elif is_flask_api:
            tasks = [
                f"Create project structure at {base_path}/ with app/ models/ routes/ config.py requirements.txt",
                f"Create {base_path}/config.py with Flask configuration database URI and secret key",
                f"Create {base_path}/app/__init__.py with Flask application factory and extension registration",
                f"Create {base_path}/app/models.py with SQLAlchemy 2.0 database models",
                f"Create {base_path}/app/routes.py with all requested API endpoints",
                f"Create {base_path}/requirements.txt with flask flask-sqlalchemy and dependencies",
                f"Create {base_path}/run.py as the application entry point",
                f"Write pytest tests in {base_path}/tests/test_api.py for all endpoints",
                f"Run the tests with bash_exec pytest and verify they pass",
                f"Verify the application structure is complete with ls -la {base_path}/",
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

        return tasks

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
        Returns the expected output directory.
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

        # If workspace_root is provided and no explicit generated_projects mentioned, use workspace_root
        if workspace_root:
            return workspace_root

        # Look for explicit path mentions
        path_match = _re.search(
            r'at\s+([\w\-]+)/|in\s+([\w\-]+)/',
            prompt, _re.IGNORECASE
        )
        if path_match:
            name = path_match.group(1) or path_match.group(2)
            if Path(name).exists() or Path(name).is_dir():
                return name
            return f"generated_projects/{name}"

        # Extract name from prompt
        name_match = _re.search(
            r'called?\s+["\']?([\w\-]+)["\']?|named?\s+["\']?([\w\-]+)["\']?',
            prompt, _re.IGNORECASE
        )
        if name_match:
            name = (name_match.group(1) or name_match.group(2)).lower()
            return f"generated_projects/{name}"

        return "generated_projects/output"

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
