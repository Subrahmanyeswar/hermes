#!/usr/bin/env python3
"""
HERMES - Tier 3 Claude Client Tests
Tests: initialization, cost cap enforcement, cost calculation, SQLite logging,
       availability checks, and arbitrate() error handling.

Run: pytest tests/test_claude_client.py -v
"""

import pytest
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from models.claude_client import ClaudeClient, Tier3Response, HARD_COST_CAP_USD


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-123")
    return ClaudeClient(db_path=tmp_path / "test.db")


# ──────────────────────────────────────────────────────────────────────
# Initialization & Availability Tests
# ──────────────────────────────────────────────────────────────────────

def test_client_initialises_with_zero_cost(client):
    assert client.total_cost == 0.0


def test_is_available_with_key_set(client):
    assert client.is_available() is True


def test_is_available_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = ClaudeClient(db_path=tmp_path / "test.db")
    assert c.is_available() is False


def test_is_unavailable_when_cap_reached(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    c = ClaudeClient(db_path=tmp_path / "test.db")
    c.total_cost = HARD_COST_CAP_USD  # Simulate cap reached
    assert c.is_available() is False


# ──────────────────────────────────────────────────────────────────────
# Cost Calculation Tests
# ──────────────────────────────────────────────────────────────────────

def test_calculate_cost_is_correct(client):
    cost = client._calculate_cost(input_tokens=1_000_000, output_tokens=1_000_000)
    assert abs(cost - 18.0) < 0.001  # $3 + $15 = $18


def test_calculate_cost_small_call(client):
    cost = client._calculate_cost(input_tokens=2000, output_tokens=500)
    assert cost < 0.02  # Small call should cost very little


# ──────────────────────────────────────────────────────────────────────
# Cost Summary & Logging Tests
# ──────────────────────────────────────────────────────────────────────

def test_get_cost_summary_structure(client):
    summary = client.get_cost_summary()
    assert "total_spent" in summary
    assert "cap" in summary
    assert "remaining" in summary
    assert summary["cap"] == HARD_COST_CAP_USD


def test_log_cost_updates_total(client, tmp_path):
    client._log_cost("claude-sonnet-4-6", 1000, 500, 0.0105, "test task", "disagreement")
    assert abs(client.total_cost - 0.0105) < 0.0001


def test_log_cost_persists_to_sqlite(client, tmp_path):
    client._log_cost("claude-sonnet-4-6", 1000, 500, 0.0105, "test task", "low confidence")
    with sqlite3.connect(str(client.db_path)) as conn:
        rows = conn.execute("SELECT * FROM api_costs").fetchall()
    assert len(rows) == 1
    assert rows[0][3] == 1000  # input_tokens


# ──────────────────────────────────────────────────────────────────────
# Arbitration Tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_arbitrate_returns_fallback_when_cap_reached(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    c = ClaudeClient(db_path=tmp_path / "test.db")
    c.total_cost = HARD_COST_CAP_USD  # Simulate cap

    result = await c.arbitrate(
        task="Some task",
        tier1_output="T1 said write_file",
        tier2_issues=["issue 1"],
        tool_result="result",
        escalation_reason="low confidence"
    )
    assert result.success is False
    assert "cap" in result.error.lower() or "ANTHROPIC" in result.error


@pytest.mark.asyncio
async def test_arbitrate_handles_api_error(client):
    with patch("models.claude_client.anthropic", create=True) as mock_module:
        mock_instance = MagicMock()
        mock_instance.messages.create.side_effect = Exception("API error")
        mock_module.Anthropic.return_value = mock_instance

        result = await client.arbitrate(
            task="Task", tier1_output="T1 output",
            tier2_issues=[], tool_result="",
            escalation_reason="test"
        )
    assert result.success is False
    assert result.content == "T1 output"  # Falls back to T1
