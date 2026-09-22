"""
tests/test_prompt4_context_optimization.py

Verification suite for HERMES Performance Optimization Phase 4:
- Context optimization (minimum sufficient context)
- Prompt prefix stability and hash invariant
- Selective tool schema injection (production vs benchmark isolation)
- Memory relevance filtering and deduplication
- Progressive skill disclosure
- Uncompromised tool authorization and security gates
"""

import pytest
import hashlib
from tools.registry import (
    selective_tool_schema_for_prompt,
    tool_schema_for_prompt,
    list_tools,
    get_tool,
    PermissionGate,
)
from memory.store import (
    read_context_for_prompt,
    read_memory_index,
)
from core.intent_classifier import IntentClassifier
from core.prompt_builder import (
    PromptContext,
    build_system_prompt,
    get_static_prefix_hash,
    HERMES_STATIC_PREFIX,
    HERMES_ROLE,
)


def test_tool_schema_benchmark_isolation():
    """Benchmark mode must unconditionally serialize all 20 registered tools."""
    bench_schema = selective_tool_schema_for_prompt(
        required_tools=["write_file"], execution_mode="benchmark"
    )
    full_schema = tool_schema_for_prompt()
    assert bench_schema == full_schema
    assert len(bench_schema.splitlines()) == 20


def test_tool_schema_selective_production_reduction():
    """Production mode must expose only task-required + safe diagnostic tools."""
    prod_schema = selective_tool_schema_for_prompt(
        required_tools=["write_file"], execution_mode="production"
    )
    lines = prod_schema.splitlines()
    assert len(lines) == 4
    tool_names = [line.split(":")[0].strip("- ") for line in lines]
    assert "write_file" in tool_names
    assert "read_file" in tool_names
    assert "list_directory" in tool_names
    assert "create_folder" in tool_names
    assert "delete_file" not in tool_names
    assert "git_push" not in tool_names
    assert "web_search" not in tool_names


def test_tool_authorization_unaffected_by_schema_reduction():
    """Omitting a tool from the prompt does NOT revoke system authorization."""
    delete_tool_cls = get_tool("delete_file")
    assert delete_tool_cls is not None
    gate_auto = PermissionGate("auto")
    allowed, reason = gate_auto.check(delete_tool_cls)
    assert allowed is True

    gate_safe = PermissionGate("safe")
    allowed_safe, reason_safe = gate_safe.check(delete_tool_cls)
    assert allowed_safe is False
    assert "blocked in 'safe' mode" in reason_safe or "exceeds the 0.5 threshold" in reason_safe


def test_static_prefix_hash_invariance():
    """The static prompt prefix must have an invariant SHA-256 hash across calls."""
    hash1 = get_static_prefix_hash()
    hash2 = hashlib.sha256(HERMES_STATIC_PREFIX.encode("utf-8")).hexdigest()
    assert hash1 == hash2
    assert len(hash1) == 64


def test_system_prompt_benchmark_layout_isolation():
    """In benchmark mode, system prompt retains the frozen HERMES_ROLE template."""
    ctx_bench = PromptContext(
        user_task="Build feature",
        mode="auto",
        available_tools=list_tools(),
        tool_descriptions=tool_schema_for_prompt(),
        execution_mode="benchmark",
    )
    bench_prompt = build_system_prompt(ctx_bench)
    assert "═══ TOOL USAGE ═══" in bench_prompt
    assert "═══ RESPONSE FORMAT ═══" in bench_prompt
    assert bench_prompt.find("═══ TOOL USAGE ═══") < bench_prompt.find("═══ RESPONSE FORMAT ═══")


def test_system_prompt_production_prefix_stability():
    """In production mode, system prompt structures static prefix before dynamic suffix."""
    ctx_prod = PromptContext(
        user_task="Build feature",
        mode="auto",
        available_tools=["write_file"],
        tool_descriptions="- write_file: Write content",
        execution_mode="production",
    )
    prod_prompt = build_system_prompt(ctx_prod)
    assert prod_prompt.startswith(HERMES_STATIC_PREFIX)
    assert prod_prompt.find("═══ RESPONSE FORMAT ═══") < prod_prompt.find("═══ TOOL USAGE ═══")


def test_memory_relevance_filtering_production():
    """In production mode, query without keyword match yields empty memory prompt."""
    query = "Create index.html layout"
    mem = read_context_for_prompt(
        project="default", query=query, execution_mode="production"
    )
    assert mem == ""


def test_memory_benchmark_preserves_full_facts():
    """In benchmark mode, memory facts are injected unconditionally up to limit."""
    query = "Create index.html layout"
    mem_bench = read_context_for_prompt(
        project="default", query=query, execution_mode="benchmark"
    )
    assert "## Project Memory" in mem_bench


def test_skill_progressive_disclosure_benchmark_vs_production():
    """Benchmark loads full procedural text; production level 1 loads compact summary."""
    classifier = IntentClassifier("skills/")
    skill_ids = ["react-frontend"]
    bench_text, _ = classifier.build_skill_prompt_section(
        skill_ids, execution_mode="benchmark"
    )
    prod_text, _ = classifier.build_skill_prompt_section(
        skill_ids, execution_mode="production", disclosure_level=1
    )
    assert len(prod_text) < len(bench_text)
    assert len(prod_text) < 350
