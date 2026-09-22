"""
Unit and Integration Tests for Phase 8 Context Engine.
Tests context item classification, multi-source ranking, token budgeting,
generation headroom reservation, deduplication, and ContextPack assembly.
"""
import pytest
from core.context_engine import (
    ContextItem,
    ContextSource,
    ContextRanker,
    ContextBudgeter,
    ContextEngine,
    ContextPack
)


def test_context_item_token_estimation():
    """Token estimation should approximate 1 token per 4 characters."""
    item = ContextItem(
        id="test:1",
        source=ContextSource.USER_TASK,
        content="This is a test task with 40 characters.",
        relevance_score=10.0
    )
    assert item.token_estimate >= 8
    assert item.is_hard_required is False


def test_context_ranking_hard_required_priority():
    """Hard required items must rank above optional items regardless of score."""
    ranker = ContextRanker()
    items = [
        ContextItem(id="opt:high", source=ContextSource.WORKSPACE_FILE, content="code", relevance_score=50.0, is_hard_required=False),
        ContextItem(id="hard:low", source=ContextSource.SYSTEM_CORE, content="rules", relevance_score=1.0, is_hard_required=True),
        ContextItem(id="opt:low", source=ContextSource.MEMORY, content="fact", relevance_score=10.0, is_hard_required=False),
    ]
    ranked = ranker.rank(items)
    assert ranked[0].id == "hard:low"
    assert ranked[1].id == "opt:high"
    assert ranked[2].id == "opt:low"


def test_context_budgeter_enforces_limit_and_reserve():
    """Budgeter must keep hard required items and prune low-scoring optional items to satisfy reserve."""
    budgeter = ContextBudgeter(max_context_tokens=100, generation_reserve=50)  # 50 tokens available
    items = [
        ContextItem(id="hard:1", source=ContextSource.USER_TASK, content="A" * 80, relevance_score=100.0, is_hard_required=True),  # ~20 tokens
        ContextItem(id="opt:1", source=ContextSource.WORKSPACE_FILE, content="B" * 80, relevance_score=30.0, is_hard_required=False), # ~20 tokens
        ContextItem(id="opt:2", source=ContextSource.MEMORY, content="C" * 120, relevance_score=10.0, is_hard_required=False),        # ~30 tokens (exceeds 50 budget)
    ]
    included, dropped = budgeter.budget(items)
    included_ids = [i.id for i in included]
    assert "hard:1" in included_ids
    assert "opt:1" in included_ids
    assert "opt:2" not in included_ids
    assert any(d.id == "opt:2" for d in dropped)


def test_context_deduplication():
    """Identical content in multiple optional items must be deduplicated."""
    budgeter = ContextBudgeter(max_context_tokens=1000, generation_reserve=200)
    items = [
        ContextItem(id="file:1", source=ContextSource.WORKSPACE_FILE, content="def authenticate(): pass", relevance_score=20.0),
        ContextItem(id="mem:1", source=ContextSource.MEMORY, content="def authenticate(): pass", relevance_score=15.0),
    ]
    included, dropped = budgeter.budget(items)
    assert len(included) == 1
    assert len(dropped) == 1


def test_context_engine_full_pack_assembly():
    """ContextEngine must assemble a clean ContextPack with source labels and token counts."""
    engine = ContextEngine(enabled=True)
    cpack = engine.build_context_pack(
        task_text="Fix authentication login bug",
        mode="auto",
        workspace_manager=None,
        memory_context="[FACT]: Project uses JWT authentication\n[FACT]: Database is SQLite",
        skill_content="def solve_python_bug(): pass",
        active_skill_name="python-dev",
        tool_descriptions="read_file, write_file",
        max_context_tokens=4096,
        generation_reserve=1024
    )

    assert isinstance(cpack, ContextPack)
    assert cpack.total_tokens > 0
    assert cpack.items_included >= 2
    assert "TASK: Fix authentication login bug" in cpack.system_prompt or "Fix authentication login bug" in cpack.user_message
    assert "[MEMORY]" in cpack.system_prompt
    assert "[SKILL]" in cpack.system_prompt
    assert cpack.build_duration_ms >= 0.0
