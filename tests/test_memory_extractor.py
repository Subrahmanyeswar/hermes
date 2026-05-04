import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from memory.types import MemoryFact, MemoryState, FactType
from memory.extractor import extract_memories, confirm_and_write_facts

# ── Tests for extract_memories ────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_memories_returns_proposed_facts():
    """Extracted facts must always be in PROPOSED state."""
    mock_client = AsyncMock()
    mock_client.generate = AsyncMock(return_value='[{"type": "FACT", "content": "Uses Flask 3.1 with SQLite"}]')
    
    facts = await extract_memories(
        task_description="Built a Flask REST API",
        conversation_history=[{"role": "user", "content": "build a flask api"}],
        tool_results=[{"tool": "write_file", "exit_code": 0, "success": True}],
        ollama_client=mock_client
    )
    
    assert len(facts) == 1
    assert facts[0].state == MemoryState.PROPOSED
    assert facts[0].fact_type == FactType.FACT
    assert "Flask" in facts[0].content

@pytest.mark.asyncio
async def test_extract_memories_handles_empty_array_response():
    mock_client = AsyncMock()
    mock_client.generate = AsyncMock(return_value='[]')
    
    facts = await extract_memories(
        task_description="Listed a directory",
        conversation_history=[],
        tool_results=[],
        ollama_client=mock_client
    )
    assert facts == []

@pytest.mark.asyncio
async def test_extract_memories_handles_json_error():
    """Malformed JSON from Tier 1 should return empty list, not crash."""
    mock_client = AsyncMock()
    mock_client.generate = AsyncMock(return_value='this is not json at all')
    
    facts = await extract_memories(
        task_description="Some task",
        conversation_history=[],
        tool_results=[],
        ollama_client=mock_client
    )
    assert facts == []

@pytest.mark.asyncio
async def test_extract_memories_handles_markdown_wrapped_json():
    """Model might wrap JSON in markdown fences — should still parse."""
    mock_client = AsyncMock()
    mock_client.generate = AsyncMock(return_value=(
        '```json\n[{"type": "TASK_DONE", "content": "Created Flask app structure"}]\n```'
    ))
    
    facts = await extract_memories(
        task_description="Created Flask app",
        conversation_history=[],
        tool_results=[],
        ollama_client=mock_client
    )
    assert len(facts) == 1
    assert facts[0].fact_type == FactType.TASK_DONE

@pytest.mark.asyncio
async def test_extract_memories_caps_at_5_facts():
    """Never extract more than 5 facts from a single task."""
    mock_client = AsyncMock()
    
    # Simpler: just use a mocked response with 7 items
    mock_client.generate = AsyncMock(return_value=(
        '[{"type": "FACT", "content": "fact 1"}, {"type": "FACT", "content": "fact 2"}, '
        '{"type": "FACT", "content": "fact 3"}, {"type": "FACT", "content": "fact 4"}, '
        '{"type": "FACT", "content": "fact 5"}, {"type": "FACT", "content": "fact 6"}, '
        '{"type": "FACT", "content": "fact 7"}]'
    ))
    
    facts = await extract_memories(
        task_description="Big task",
        conversation_history=[],
        tool_results=[],
        ollama_client=mock_client
    )
    assert len(facts) <= 5

@pytest.mark.asyncio
async def test_extract_memories_truncates_long_content():
    """Content over 150 chars should be truncated, not crash."""
    long_content = "A" * 200
    mock_client = AsyncMock()
    mock_client.generate = AsyncMock(return_value=f'[{{"type": "FACT", "content": "{long_content}"}}]')
    
    facts = await extract_memories(
        task_description="Some task",
        conversation_history=[],
        tool_results=[],
        ollama_client=mock_client
    )
    if facts:
        assert len(facts[0].content) <= 150

# ── Tests for confirm_and_write_facts ────────────────────────────────

def test_confirm_and_write_facts_writes_on_exit_code_0(tmp_path, monkeypatch):
    monkeypatch.setattr("memory.store.get_memory_path", lambda project="default": tmp_path / "MEMORY.md")
    monkeypatch.setattr("memory.store.write_fact", lambda fact, project="default": True)
    
    proposed = MemoryFact(fact_type=FactType.FACT, content="Uses Flask 3.1")
    count = confirm_and_write_facts([proposed], tool_name="write_file", exit_code=0)
    assert count == 1
    assert proposed.state == MemoryState.CONFIRMED  # or PERSISTED after write

def test_confirm_and_write_facts_skips_on_nonzero_exit_code(monkeypatch):
    monkeypatch.setattr("memory.store.write_fact", lambda fact, project="default": True)
    
    proposed = MemoryFact(fact_type=FactType.FACT, content="Uses Flask 3.1")
    # exit_code=1 means tool failed — should NOT write
    count = confirm_and_write_facts([proposed], tool_name="bash_exec", exit_code=1)
    assert count == 0
    assert proposed.state == MemoryState.PROPOSED  # unchanged
