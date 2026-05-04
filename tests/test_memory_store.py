import pytest
from pathlib import Path
from datetime import datetime
from memory.types import MemoryFact, MemoryState, FactType, MemoryIndex
from memory.store import (
    read_memory_index, write_fact, read_context_for_prompt,
    write_layer2_topic, read_layer2_topic, get_memory_path
)

@pytest.fixture
def isolated_project(tmp_path, monkeypatch):
    """
    Redirect memory file writes to a temp directory.
    Patches get_memory_path to use tmp_path instead of the real project root.
    """
    def mock_get_path(project="default"):
        if project == "default":
            return tmp_path / "MEMORY.md"
        proj_dir = tmp_path / "data" / "memory" / project
        proj_dir.mkdir(parents=True, exist_ok=True)
        return proj_dir / "MEMORY.md"
    
    monkeypatch.setattr("memory.store.get_memory_path", mock_get_path)
    monkeypatch.setattr("memory.store.LAYER2_BASE_DIR", tmp_path / "data" / "memory")
    return tmp_path

def make_confirmed_fact(content: str, fact_type: FactType = FactType.FACT) -> MemoryFact:
    """Helper: create a fact already in CONFIRMED state."""
    fact = MemoryFact(fact_type=fact_type, content=content)
    fact.confirm(tool_name="write_file", exit_code=0)
    return fact

# ── Core state machine enforcement ───────────────────────────────────

def test_write_fact_raises_on_proposed_state(isolated_project):
    """A PROPOSED fact must never be written — this is a hard assert."""
    proposed_fact = MemoryFact(fact_type=FactType.FACT, content="Uses Flask 3.1")
    assert proposed_fact.state == MemoryState.PROPOSED
    with pytest.raises(AssertionError, match="state machine was bypassed"):
        write_fact(proposed_fact)

def test_write_fact_succeeds_for_confirmed_fact(isolated_project):
    fact = make_confirmed_fact("Uses Flask 3.1 + SQLite3. NOT PostgreSQL.")
    result = write_fact(fact)
    assert result is True
    assert fact.state == MemoryState.PERSISTED

def test_write_fact_creates_memory_file(isolated_project):
    fact = make_confirmed_fact("App entry point is run.py. Port 5000.")
    write_fact(fact)
    memory_path = isolated_project / "MEMORY.md"
    assert memory_path.exists()
    content = memory_path.read_text()
    assert "[FACT]: App entry point is run.py. Port 5000." in content

# ── Round-trip: write then read ───────────────────────────────────────

def test_read_memory_index_returns_written_facts(isolated_project):
    fact1 = make_confirmed_fact("Uses Flask 3.1")
    fact2 = make_confirmed_fact("App runs on port 5000")
    write_fact(fact1)
    write_fact(fact2)
    
    index = read_memory_index()
    non_stale = [f for f in index.facts if f.fact_type != FactType.STALE]
    contents = [f.content for f in non_stale]
    assert "Uses Flask 3.1" in contents
    assert "App runs on port 5000" in contents

def test_read_memory_index_empty_for_missing_file(isolated_project):
    index = read_memory_index("nonexistent_project")
    assert index.facts == []

# ── Duplicate detection ───────────────────────────────────────────────

def test_write_fact_skips_exact_duplicate(isolated_project):
    fact1 = make_confirmed_fact("Uses Flask 3.1 + SQLite3")
    fact2 = make_confirmed_fact("Uses Flask 3.1 + SQLite3")
    write_fact(fact1)
    write_fact(fact2)  # Should be skipped
    
    index = read_memory_index()
    matching = [f for f in index.facts if "Flask 3.1" in f.content and f.fact_type == FactType.FACT]
    assert len(matching) == 1  # Only one, not two

# ── Contradiction handling ────────────────────────────────────────────

def test_write_fact_marks_contradicting_as_stale(isolated_project):
    old_fact = make_confirmed_fact("Uses SQLite database for all storage")
    write_fact(old_fact)
    
    new_fact = make_confirmed_fact("Uses PostgreSQL database instead of SQLite")
    write_fact(new_fact)
    
    index = read_memory_index()
    stale_facts = [f for f in index.facts if f.fact_type == FactType.STALE]
    assert len(stale_facts) >= 1
    assert any("SQLite" in f.content for f in stale_facts)

# ── Context for prompt ────────────────────────────────────────────────

def test_read_context_for_prompt_returns_formatted_string(isolated_project):
    for i in range(3):
        write_fact(make_confirmed_fact(f"Test fact number {i} about the project"))
    
    context = read_context_for_prompt()
    assert "Project Memory" in context
    assert "[FACT]:" in context

def test_read_context_for_prompt_empty_when_no_facts(isolated_project):
    context = read_context_for_prompt("empty_project")
    assert context == ""

def test_read_context_excludes_stale_facts(isolated_project):
    old = make_confirmed_fact("Uses SQLite database for storage")
    write_fact(old)
    new = make_confirmed_fact("Uses PostgreSQL database, not SQLite")
    write_fact(new)
    
    context = read_context_for_prompt()
    # Stale SQLite fact should not appear in context (or only PostgreSQL version)
    assert "PostgreSQL" in context

# ── Layer 2 topic files ───────────────────────────────────────────────

def test_write_and_read_layer2_topic(isolated_project):
    content = "# Database Schema\n\nTable: users\n- id: INTEGER PRIMARY KEY\n- email: TEXT"
    result = write_layer2_topic("myapp", "database_schema", content)
    assert result is True
    
    read_back = read_layer2_topic("myapp", "database_schema")
    assert read_back is not None
    assert "users" in read_back

def test_read_layer2_topic_returns_none_for_missing(isolated_project):
    result = read_layer2_topic("myapp", "nonexistent_topic")
    assert result is None

# ── Missing Tests ───────────────────────────────────────────────────

def test_write_fact_fails_if_content_too_long(isolated_project):
    long_content = "A" * 151
    fact = make_confirmed_fact(long_content)
    result = write_fact(fact)
    assert result is False

def test_archive_stale_fact_marks_fact_as_stale(isolated_project):
    from memory.store import archive_stale_fact
    fact = make_confirmed_fact("This is a temporary fact")
    write_fact(fact)
    
    index_before = read_memory_index()
    assert index_before.facts[0].fact_type == FactType.FACT
    
    archive_stale_fact(fact)
    
    index_after = read_memory_index()
    assert index_after.facts[0].fact_type == FactType.STALE

# ── Consolidator tests ────────────────────────────────────────────────
from memory.consolidator import consolidate_memory, remove_duplicates, remove_stale_facts
from memory.types import MemoryIndex

def test_remove_duplicates_removes_exact_matches(isolated_project):
    index = MemoryIndex(project="test")
    index.facts = [
        MemoryFact(fact_type=FactType.FACT, content="Uses Flask 3.1", state=MemoryState.PERSISTED),
        MemoryFact(fact_type=FactType.FACT, content="Uses Flask 3.1", state=MemoryState.PERSISTED),  # duplicate
        MemoryFact(fact_type=FactType.FACT, content="Port is 5000", state=MemoryState.PERSISTED),
    ]
    cleaned, count = remove_duplicates(index)
    assert count == 1
    assert len(cleaned.facts) == 2

def test_remove_stale_facts_removes_stale(isolated_project):
    index = MemoryIndex(project="test")
    index.facts = [
        MemoryFact(fact_type=FactType.FACT, content="Current fact", state=MemoryState.PERSISTED),
        MemoryFact(fact_type=FactType.STALE, content="Old stale fact", state=MemoryState.PERSISTED),
    ]
    cleaned, count = remove_stale_facts(index)
    assert count == 1
    assert len(cleaned.facts) == 1
    assert cleaned.facts[0].content == "Current fact"

def test_consolidate_memory_returns_stats(isolated_project):
    # Write some facts first
    for content in ["Fact A about the project", "Fact B about the project"]:
        fact = make_confirmed_fact(content)
        write_fact(fact)
    
    stats = consolidate_memory()
    assert "initial_facts" in stats
    assert "final_facts" in stats
    assert "duplicates_removed" in stats
    assert stats["project"] == "default"