# core/subagents/__init__.py
"""
HERMES 2.x Subagent & Background Execution Subsystem.

Provides:
- Policy Engine (Explorer, Reviewer, Tester, Implementer, Ceiling Enforcement)
- Isolated Context Construction (Fresh window, zero parent transcript pollution)
- Git Worktree Manager (Safe workspace sandboxing, conflict detection, integration)
- Cancellation Controller (Cooperative tokens, Windows process tree termination)
- Resource Governor (Bounded semaphore concurrency, turn/tool/token budgets, stall detection)
- Background Job Execution (Async subagent loops, shell/test/build background processes)
- Handoff Manager (Bounded observation formatting, externalized artifact storage)
- Lifecycle Manager (Central orchestration of delegation, worktrees, and handoffs)
- Reconciler (Startup recovery of orphaned jobs, subagents, and worktrees)
"""

from core.subagents.policy import (
    SubagentPolicyEngine,
    READ_ONLY_EXPLORATION_TOOLS,
    REVIEW_TOOLS,
    TEST_TOOLS,
    IMPLEMENTATION_TOOLS,
)
from core.subagents.context import (
    SubagentContextBuilder,
    SubagentPromptContext,
)
from core.subagents.worktree import (
    WorktreeManager,
)
from core.subagents.cancellation import (
    CancellationController,
    CancellationToken,
    SubagentCancelledException,
)
from core.subagents.governor import (
    ResourceGovernor,
    BudgetExceededException,
)
from core.subagents.background import (
    BackgroundJobManager,
)
from core.subagents.handoff import (
    HandoffManager,
)
from core.subagents.manager import (
    SubagentManager,
)
from core.subagents.reconciler import (
    SubagentReconciler,
)

__all__ = [
    "SubagentPolicyEngine",
    "READ_ONLY_EXPLORATION_TOOLS",
    "REVIEW_TOOLS",
    "TEST_TOOLS",
    "IMPLEMENTATION_TOOLS",
    "SubagentContextBuilder",
    "SubagentPromptContext",
    "WorktreeManager",
    "CancellationController",
    "CancellationToken",
    "SubagentCancelledException",
    "ResourceGovernor",
    "BudgetExceededException",
    "BackgroundJobManager",
    "HandoffManager",
    "SubagentManager",
    "SubagentReconciler",
]
