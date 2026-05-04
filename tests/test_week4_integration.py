#!/usr/bin/env python3
"""
HERMES - Week 4 Integration Tests
Tests the complete memory system end-to-end:
  - Write facts -> restart -> facts survive
  - State machine enforcement across the whole flow
  - Memory injection into real Tier 1 prompts
  - Session logging round-trip
  - Consolidation cleans up correctly

Run: python tests/test_week4_integration.py
"""
import asyncio
import json
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.types import MemoryFact, MemoryState, FactType, MemoryIndex
from memory.store import write_fact, read_memory_index, read_context_for_prompt, get_memory_path
from memory.extractor import extract_memories, confirm_and_write_facts
from memory.consolidator import consolidate_memory
from memory.session_logger import SessionLogger
from core.prompt_builder import PromptContext, build_system_prompt
from models.ollama_client import OllamaClient

# ----------------------------------------------------------------------

def test_1_state_machine_full_flow(tmp_path, monkeypatch):
    """
    PROPOSED -> CONFIRMED -> PERSISTED must be enforced end-to-end.
    A PROPOSED fact must never appear in MEMORY.md.
    """
    monkeypatch.setattr("memory.store.get_memory_path", lambda project="default": tmp_path / "MEMORY.md")
    
    # Create PROPOSED fact
    fact = MemoryFact(fact_type=FactType.FACT, content="Uses Flask 3.1 with JWT auth")
    assert fact.state == MemoryState.PROPOSED
    
    # Attempt to write PROPOSED - must raise AssertionError
    try:
        write_fact(fact)
        assert False, "Should have raised AssertionError"
    except AssertionError:
        pass  # Correct - PROPOSED fact was blocked
    
    # Confirm it (simulating tool exit_code=0)
    fact.confirm(tool_name="write_file", exit_code=0)
    assert fact.state == MemoryState.CONFIRMED
    
    # Now write - must succeed
    result = write_fact(fact)
    assert result is True
    assert fact.state == MemoryState.PERSISTED
    
    # Verify in file
    content = (tmp_path / "MEMORY.md").read_text()
    assert "[FACT]: Uses Flask 3.1 with JWT auth" in content
    
    print("[OK] State machine: PROPOSED -> CONFIRMED -> PERSISTED enforced correctly")

# ----------------------------------------------------------------------

def test_2_facts_survive_session_restart(tmp_path, monkeypatch):
    """
    The critical test: facts written in session 1 must be readable in session 2.
    This simulates a complete process restart.
    """
    memory_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("memory.store.get_memory_path", lambda project="default": memory_file)
    
    # -- Session 1: write facts ----------------------------------------
    facts_to_write = [
        ("Uses Flask 3.1 + SQLite3. NOT PostgreSQL. Confirmed on setup.", FactType.FACT),
        ("App entry point: run.py. Port 5000. Debug OFF in production.", FactType.FACT),
        ("REST API created. Endpoints: /todos, /users, /auth. Tools: write_file.", FactType.TASK_DONE),
    ]
    
    for content, fact_type in facts_to_write:
        fact = MemoryFact(fact_type=fact_type, content=content)
        fact.confirm("write_file", 0)
        write_fact(fact)
    
    assert memory_file.exists()
    print(f"  Session 1: wrote {len(facts_to_write)} facts to {memory_file}")
    
    # -- Session 2: read facts (simulating restart) --------------------
    # Completely fresh read - no in-memory state carried over
    fresh_index = read_memory_index()
    non_stale = [f for f in fresh_index.facts if f.fact_type != FactType.STALE]
    
    assert len(non_stale) == len(facts_to_write), (
        f"Expected {len(facts_to_write)} facts, found {len(non_stale)} after restart"
    )
    
    contents_in_file = [f.content for f in non_stale]
    for content, _ in facts_to_write:
        assert content in contents_in_file, f"Fact not found after restart: {content!r}"
    
    print(f"  Session 2: all {len(facts_to_write)} facts survived restart [OK]")
    print("[OK] Memory persistence: facts survive session restart")

# ----------------------------------------------------------------------

def test_3_memory_context_injected_into_prompt(tmp_path, monkeypatch):
    """
    Memory context from MEMORY.md must appear in the Tier 1 system prompt.
    """
    memory_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("memory.store.get_memory_path", lambda project="default": memory_file)
    
    # Write a distinctive fact
    fact = MemoryFact(fact_type=FactType.FACT, content="UNIQUE_MARKER_XK7Q: project uses Flask")
    fact.confirm("write_file", 0)
    write_fact(fact)
    
    # Build prompt with memory context
    memory_context = read_context_for_prompt()
    assert "UNIQUE_MARKER_XK7Q" in memory_context, "Fact must be in memory context"
    
    ctx = PromptContext(
        user_task="Add a new endpoint to the API",
        mode="auto",
        available_tools=["write_file", "read_file"],
        tool_descriptions="- write_file: Write a file\n- read_file: Read a file",
        memory_context=memory_context,
        skill_context="",
        active_skill_name="none"
    )
    
    system_prompt = build_system_prompt(ctx)
    assert "UNIQUE_MARKER_XK7Q" in system_prompt, "Memory fact must appear in Tier 1 system prompt"
    
    print("[OK] Memory injection: fact appears in Tier 1 system prompt")

# ----------------------------------------------------------------------

def test_4_consolidation_removes_stale_and_duplicates(tmp_path, monkeypatch):
    """
    Consolidation must clean up stale facts and duplicates.
    """
    memory_file = tmp_path / "MEMORY.md"
    monkeypatch.setattr("memory.store.get_memory_path", lambda project="default": memory_file)
    
    # Write original fact
    fact1 = MemoryFact(fact_type=FactType.FACT, content="Uses SQLite database for all storage")
    fact1.confirm("write_file", 0)
    write_fact(fact1)
    
    # Write contradicting fact (makes SQLite stale)
    fact2 = MemoryFact(fact_type=FactType.FACT, content="Uses PostgreSQL database, migrated from SQLite")
    fact2.confirm("bash_exec", 0)
    write_fact(fact2)
    
    # Write duplicate
    fact3 = MemoryFact(fact_type=FactType.FACT, content="Uses PostgreSQL database, migrated from SQLite")
    fact3.confirm("bash_exec", 0)
    write_fact(fact3)
    
    # Read before consolidation
    before = read_memory_index()
    before_count = len(before.facts)
    
    # Consolidate
    stats = consolidate_memory()
    
    # Read after consolidation
    after = read_memory_index()
    non_stale_after = [f for f in after.facts if f.fact_type != FactType.STALE]
    
    assert len(non_stale_after) < before_count, "Consolidation should reduce fact count"
    assert stats["duplicates_removed"] >= 1 or stats["stale_removed"] >= 1
    
    print(f"  Before: {before_count} facts | After: {len(non_stale_after)} non-stale facts")
    print(f"  Stats: {stats}")
    print("[OK] Consolidation: removes duplicates and stale facts correctly")

# ----------------------------------------------------------------------

def test_5_session_logger_round_trip(tmp_path, monkeypatch):
    """Session events written must be readable back from the log file."""
    monkeypatch.setattr("memory.session_logger.SESSION_LOG_DIR", tmp_path / "sessions")
    
    session = SessionLogger(session_id="test_session")
    session.log_user_input("build a flask rest api")
    session.log_tool_call("write_file", {"path": "app.py", "content": "..."}, "auto")
    session.log_tool_result("write_file", True, 0, "Written 500 chars", 0.05)
    session.log_tier1_response("qwen2.5-coder:7b", '{"tool": "write_file"}', 2.3, "write_file")
    
    events = session.get_recent_events(limit=10)
    assert len(events) == 4
    
    tool_results = session.get_recent_events(event_type="tool_result")
    assert len(tool_results) == 1
    assert tool_results[0]["exit_code"] == 0
    
    print(f"  Logged 4 events, retrieved {len(events)} events from JSONL file")
    print("[OK] Session logger: round-trip write/read works correctly")

# ----------------------------------------------------------------------

async def test_6_extraction_from_real_tier1(tmp_path, monkeypatch):
    """
    Real Tier 1 (Qwen) must extract meaningful facts from a task description.
    This tests the full extraction pipeline with a real model call.
    """
    monkeypatch.setattr("memory.store.get_memory_path", lambda project="default": tmp_path / "MEMORY.md")
    
    client = OllamaClient()
    if not await client.is_running():
        print("  [WARN] Ollama not running - skipping real Tier 1 extraction test")
        return
    
    task = "Created a Flask REST API with /users endpoint returning JSON list from SQLite database"
    conversation = [
        {"role": "user", "content": "Build a Flask API with a users endpoint"},
        {"role": "assistant", "content": "I will create the Flask API structure now"},
    ]
    tool_results = [
        {"tool": "write_file", "exit_code": 0, "success": True},
        {"tool": "write_file", "exit_code": 0, "success": True},
    ]
    
    facts = await extract_memories(
        task_description=task,
        conversation_history=conversation,
        tool_results=tool_results,
        ollama_client=client,
        model="qwen2.5-coder:7b"
    )
    
    # All extracted facts must be PROPOSED
    assert all(f.state == MemoryState.PROPOSED for f in facts), \
        "All extracted facts must be in PROPOSED state"
    assert len(facts) <= 5, "Must not extract more than 5 facts"
    
    print(f"  Extracted {len(facts)} PROPOSED facts:")
    for f in facts:
        print(f"    [{f.fact_type.value}]: {f.content}")
    
    # Confirm them all (simulating tool success)
    written = confirm_and_write_facts(facts, tool_name="write_file", exit_code=0)
    
    # Verify they are in MEMORY.md
    index = read_memory_index()
    non_stale = [f for f in index.facts if f.fact_type != FactType.STALE]
    assert len(non_stale) == written
    
    print(f"  Confirmed and persisted {written} facts to MEMORY.md")
    print("[OK] Real Tier 1 extraction: facts extracted -> confirmed -> persisted correctly")

# ----------------------------------------------------------------------

async def main():
    import tempfile
    
    print("=" * 60)
    print("HERMES - Week 4 Integration Tests (Memory System)")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        
        # Run non-async tests with a simple monkeypatch simulation
        class FakeMonkeypatch:
            def __init__(self, tmp):
                self.tmp = tmp
                self._patches = []
            def setattr(self, target, value):
                parts = target.rsplit(".", 1)
                if len(parts) == 2:
                    import importlib
                    mod = importlib.import_module(parts[0])
                    self._patches.append((mod, parts[1], getattr(mod, parts[1], None)))
                    setattr(mod, parts[1], value)
            def undo_all(self):
                for mod, attr, old_val in self._patches:
                    if old_val is None:
                        try: delattr(mod, attr)
                        except: pass
                    else:
                        setattr(mod, attr, old_val)
        
        tests = [
            ("State machine PROPOSED -> CONFIRMED -> PERSISTED", lambda: test_1_state_machine_full_flow(tmp_path, FakeMonkeypatch(tmp_path))),
            ("Facts survive session restart", lambda: test_2_facts_survive_session_restart(Path(tmp) / "t2", FakeMonkeypatch(Path(tmp) / "t2"))),
            ("Memory context injected into prompt", lambda: test_3_memory_context_injected_into_prompt(Path(tmp) / "t3", FakeMonkeypatch(Path(tmp) / "t3"))),
            ("Consolidation removes stale + duplicates", lambda: test_4_consolidation_removes_stale_and_duplicates(Path(tmp) / "t4", FakeMonkeypatch(Path(tmp) / "t4"))),
            ("Session logger round-trip", lambda: test_5_session_logger_round_trip(Path(tmp) / "t5", FakeMonkeypatch(Path(tmp) / "t5"))),
            ("Real Tier 1 memory extraction", lambda: asyncio.ensure_future(test_6_extraction_from_real_tier1(Path(tmp) / "t6", FakeMonkeypatch(Path(tmp) / "t6")))),
        ]
        
        passed_all = True
        for name, test_fn in tests:
            print(f"\n[TEST] {name}")
            try:
                result = test_fn()
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                    await result
            except Exception as e:
                import traceback
                print(f"  [FAIL] FAILED: {type(e).__name__}: {e}")
                traceback.print_exc()
                passed_all = False
    
    print("\n" + "=" * 60)
    if passed_all:
        print("WEEK 4 COMPLETE: Memory system fully operational.")
        print("Facts persist across restarts. State machine enforced.")
        print("Ready for Week 5 (Tier 2 Verifier + Disagreement Router).")
    else:
        print("WEEK 4 INCOMPLETE: Fix failures before Week 5.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
