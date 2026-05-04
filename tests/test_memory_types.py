import pytest
from datetime import datetime
from memory.types import MemoryFact, MemoryState, FactType, MemoryIndex

def test_fact_initial_state_is_proposed():
    fact = MemoryFact(fact_type=FactType.FACT, content="Uses Flask 3.1")
    assert fact.state == MemoryState.PROPOSED

def test_confirm_moves_to_confirmed_on_exit_code_0():
    fact = MemoryFact(fact_type=FactType.FACT, content="Uses Flask 3.1")
    fact.confirm(tool_name="write_file", exit_code=0)
    assert fact.state == MemoryState.CONFIRMED
    assert fact.source_tool == "write_file"
    assert fact.confirmed_at is not None

def test_confirm_raises_on_nonzero_exit_code():
    fact = MemoryFact(fact_type=FactType.FACT, content="Uses Flask 3.1")
    with pytest.raises(ValueError, match="exit_code=1"):
        fact.confirm(tool_name="bash_exec", exit_code=1)
    assert fact.state == MemoryState.PROPOSED  # Must not change state

def test_confirm_raises_if_not_proposed():
    fact = MemoryFact(fact_type=FactType.FACT, content="Uses Flask 3.1")
    fact.confirm("write_file", 0)
    fact.persist()
    with pytest.raises(ValueError, match="PROPOSED"):
        fact.confirm("write_file", 0)  # Already persisted

def test_persist_moves_to_persisted():
    fact = MemoryFact(fact_type=FactType.FACT, content="Uses Flask 3.1")
    fact.confirm("write_file", 0)
    fact.persist()
    assert fact.state == MemoryState.PERSISTED
    assert fact.persisted_at is not None

def test_persist_raises_if_not_confirmed():
    fact = MemoryFact(fact_type=FactType.FACT, content="Uses Flask 3.1")
    with pytest.raises(ValueError, match="CONFIRMED"):
        fact.persist()

def test_to_memory_line_format():
    fact = MemoryFact(fact_type=FactType.FACT, content="Uses Flask 3.1 + SQLite3")
    assert fact.to_memory_line() == "[FACT]: Uses Flask 3.1 + SQLite3"

def test_to_memory_line_raises_if_over_150_chars():
    long_content = "A" * 151
    fact = MemoryFact(fact_type=FactType.FACT, content=long_content)
    with pytest.raises(ValueError, match="150-character limit"):
        fact.to_memory_line()

def test_from_memory_line_parses_correctly():
    line = "[FACT]: Uses Flask 3.1 + SQLite3. NOT PostgreSQL."
    fact = MemoryFact.from_memory_line(line)
    assert fact is not None
    assert fact.fact_type == FactType.FACT
    assert fact.content == "Uses Flask 3.1 + SQLite3. NOT PostgreSQL."
    assert fact.state == MemoryState.PERSISTED

def test_from_memory_line_returns_none_for_comment():
    assert MemoryFact.from_memory_line("# This is a comment") is None
    assert MemoryFact.from_memory_line("") is None
    assert MemoryFact.from_memory_line("  ") is None

def test_from_memory_line_returns_none_for_unknown_type():
    assert MemoryFact.from_memory_line("[UNKNOWN]: some content") is None

def test_memory_index_find_contradicting():
    index = MemoryIndex(project="myapp")
    index.facts.append(MemoryFact(
        fact_type=FactType.FACT,
        content="Uses SQLite database for storage",
        state=MemoryState.PERSISTED
    ))
    new_content = "Uses PostgreSQL database instead of SQLite"
    contradicting = index.find_contradicting(new_content, FactType.FACT)
    assert contradicting is not None

def test_memory_index_no_contradiction_different_type():
    index = MemoryIndex(project="myapp")
    index.facts.append(MemoryFact(
        fact_type=FactType.BUG,
        content="Login function has missing validation"
    ))
    # Same words but different fact type — should not contradict
    result = index.find_contradicting("Login function is now fixed", FactType.FACT)
    assert result is None
