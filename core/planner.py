# core/planner.py
# Task Planner for HERMES.
# Decomposes a user request into a structured Task object.
# Assigns: complexity_score, required_tools, permission_level, priority.
# Pure logic — no LLM calls, no async. Fast (< 1ms).
# The orchestrator reads the Task to know which tools to offer Tier 1
# and how to handle failure (retry count, escalation behaviour).

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from loguru import logger


# ──────────────────────────────────────────────────────────────────────
# Types
# ──────────────────────────────────────────────────────────────────────

class PermissionLevel(Enum):
    """Required permission level for a task."""
    READ_ONLY = "read_only"      # Only read operations needed
    WRITE = "write"              # File creation or modification
    EXECUTE = "execute"          # Shell command execution
    NETWORK = "network"          # External network access
    GIT = "git"                  # Git operations
    DESTRUCTIVE = "destructive"  # Delete, force operations


@dataclass
class Task:
    """A structured task created from a user request."""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_request: str = ""
    complexity_score: float = 0.5       # 0.0 (trivial) to 1.0 (very complex)
    required_tools: list[str] = field(default_factory=list)
    permission_level: PermissionLevel = PermissionLevel.READ_ONLY
    priority: int = 5                   # 1 (highest) to 10 (lowest)
    max_retries: int = 3
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    session_id: str = ""
    subtasks: list[dict] = field(default_factory=list)

    def is_simple(self) -> bool:
        """Simple tasks: complexity < 0.4, only read or single write operations."""
        return self.complexity_score < 0.4

    def is_complex(self) -> bool:
        """Complex tasks: complexity >= 0.7, multiple tools or execution needed."""
        return self.complexity_score >= 0.7

    def requires_confirmation(self) -> bool:
        """Destructive tasks always require user confirmation."""
        return self.permission_level == PermissionLevel.DESTRUCTIVE


# ──────────────────────────────────────────────────────────────────────
# Task Planner
# ──────────────────────────────────────────────────────────────────────

class TaskPlanner:
    """
    Decomposes user requests into structured Task objects.
    Pure keyword analysis — no LLM calls, no async, no randomness.
    """

    def __init__(self):
        logger.debug("Task planner ready")

    def plan(self, user_request: str, session_id: str = "") -> Task:
        """Decompose a user request into a structured Task. Pure keyword analysis — no LLM."""
        task = Task(
            user_request=user_request,
            session_id=session_id
        )

        request_lower = user_request.lower()

        # ── Assign required tools based on keywords ───────────────────
        tools = []

        if any(kw in request_lower for kw in ['read', 'show', 'display', 'list', 'view', 'check', 'find', 'search file']):
            tools.extend(['read_file', 'list_directory'])

        if any(kw in request_lower for kw in ['create', 'write', 'make', 'build', 'generate', 'add', 'new file']):
            tools.append('write_file')

        if any(kw in request_lower for kw in ['run', 'execute', 'bash', 'shell', 'command', 'install', 'start']):
            tools.append('bash_exec')

        if any(kw in request_lower for kw in ['test', 'pytest', 'unit test']):
            tools.append('run_tests')

        if any(kw in request_lower for kw in ['run python', 'run script', 'execute python']):
            tools.append('run_python')

        if any(kw in request_lower for kw in ['search web', 'search the web', 'google', 'look up', 'find online']):
            tools.append('web_search')

        if any(kw in request_lower for kw in ['git', 'commit', 'push', 'repository', 'repo', 'github']):
            tools.extend(['git_init', 'git_add_commit'])

        if any(kw in request_lower for kw in ['push', 'upload to github', 'publish']):
            tools.append('git_push')

        if any(kw in request_lower for kw in ['remember', 'save fact', 'note that', 'keep in mind']):
            tools.append('save_memory')

        if any(kw in request_lower for kw in ['delete', 'remove', 'clean up', 'erase']):
            tools.append('delete_file')

        task.required_tools = list(dict.fromkeys(tools))  # preserve order, remove dupes

        # ── Assign complexity score ───────────────────────────────────
        complexity = 0.2  # base

        # More words = more complex request
        word_count = len(user_request.split())
        if word_count > 30:
            complexity += 0.2
        elif word_count > 15:
            complexity += 0.1

        # Multiple tool categories = more complex
        if len(task.required_tools) >= 4:
            complexity += 0.3
        elif len(task.required_tools) >= 2:
            complexity += 0.15

        # Keywords that indicate complex multi-step tasks
        complex_keywords = [
            'full', 'complete', 'entire', 'all', 'with authentication',
            'with login', 'with database', 'with tests', 'and also', 'including',
            'jwt', 'oauth', 'database', 'api', 'rest api', 'crud', 'flask',
            'django', 'fastapi', 'microservice', 'middleware', 'deployment',
        ]
        if any(kw in request_lower for kw in complex_keywords):
            complexity += 0.2

        # Multiple complex keywords compound the score
        matched_complex = sum(1 for kw in complex_keywords if kw in request_lower)
        if matched_complex >= 3:
            complexity += 0.1

        # Keywords that indicate simple single-step tasks
        simple_keywords = ['just', 'only', 'simply', 'quick', 'small']
        if any(kw in request_lower for kw in simple_keywords):
            complexity -= 0.1

        task.complexity_score = max(0.1, min(1.0, complexity))

        # ── Assign permission level ───────────────────────────────────
        if 'git_push' in task.required_tools or 'delete_file' in task.required_tools:
            task.permission_level = PermissionLevel.DESTRUCTIVE
        elif any(t in task.required_tools for t in ['git_init', 'git_add_commit']):
            task.permission_level = PermissionLevel.GIT
        elif 'bash_exec' in task.required_tools or 'run_python' in task.required_tools:
            task.permission_level = PermissionLevel.EXECUTE
        elif 'web_search' in task.required_tools or 'web_fetch' in task.required_tools:
            task.permission_level = PermissionLevel.NETWORK
        elif any(t in task.required_tools for t in ['write_file', 'save_memory']):
            task.permission_level = PermissionLevel.WRITE
        else:
            task.permission_level = PermissionLevel.READ_ONLY

        # ── Assign priority ───────────────────────────────────────────
        if any(kw in request_lower for kw in ['urgent', 'asap', 'immediately', 'critical', 'fix this bug']):
            task.priority = 1
        elif task.is_complex():
            task.priority = 3
        elif task.is_simple():
            task.priority = 7
        else:
            task.priority = 5

        # ── Assign max retries ────────────────────────────────────────
        if task.permission_level == PermissionLevel.DESTRUCTIVE:
            task.max_retries = 1  # Only 1 retry for destructive operations
        elif task.is_complex():
            task.max_retries = 3
        else:
            task.max_retries = 3

        # Populate subtasks based on request keywords
        subtasks = []
        if any(kw in request_lower for kw in ['flask', 'django', 'fastapi', 'api', 'web']):
            subtasks = [
                {"title": "Create project structure", "status": "pending"},
                {"title": "Generate database models", "status": "pending"},
                {"title": "Create API routes", "status": "pending"},
                {"title": "Configure authentication", "status": "pending"},
                {"title": "Generate requirements", "status": "pending"},
                {"title": "Verify output", "status": "pending"},
            ]
        elif any(kw in request_lower for kw in ['git', 'repo', 'github', 'commit', 'push']):
            subtasks = [
                {"title": "Initialize repository", "status": "pending"},
                {"title": "Stage and commit changes", "status": "pending"},
                {"title": "Verify remote status", "status": "pending"},
                {"title": "Push code to origin", "status": "pending"},
                {"title": "Check commit history", "status": "pending"},
            ]
        elif any(kw in request_lower for kw in ['test', 'pytest']):
            subtasks = [
                {"title": "Scan test directories", "status": "pending"},
                {"title": "Identify test targets", "status": "pending"},
                {"title": "Execute test suite", "status": "pending"},
                {"title": "Collect coverage data", "status": "pending"},
                {"title": "Verify test pass rate", "status": "pending"},
            ]
        else:
            subtasks = [
                {"title": "Analyze codebase structure", "status": "pending"},
                {"title": "Perform required modifications", "status": "pending"},
                {"title": "Execute validation commands", "status": "pending"},
                {"title": "Verify overall correctness", "status": "pending"},
                {"title": "Update session memory", "status": "pending"},
            ]
        task.subtasks = subtasks

        logger.debug(
            f"Planner: task_id={task.task_id} | "
            f"complexity={task.complexity_score:.2f} | "
            f"tools={task.required_tools} | "
            f"permission={task.permission_level.value} | "
            f"priority={task.priority}"
        )
        return task
