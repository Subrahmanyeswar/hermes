# tests/test_registry.py
# Test suite for tools/registry.py
# Run with: pytest tests/test_registry.py -v

import pytest

from tools.base import BaseTool, ToolResult
from tools.registry import (
    PermissionGate,
    _REGISTRY,
    get_tool,
    list_tools,
    tool,
    tool_schema_for_prompt,
)

# ---------------------------------------------------------------------------
# Setup and Teardown
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear the global registry before and after each test."""
    _REGISTRY.clear()
    yield
    _REGISTRY.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_tool_decorator_registers_tool() -> None:
    """The @tool decorator must register the class and set its attributes."""

    @tool(
        name="dummy_tool",
        description="A dummy tool for testing.",
        permissions=["test_perm"],
        risk_score=0.2,
        blocked_in=["auto"],
    )
    class DummyTool(BaseTool):
        def execute(self, inp: object) -> ToolResult:
            return ToolResult(success=True, output="dummy")

    assert "dummy_tool" in list_tools()
    
    registered_tool = get_tool("dummy_tool")
    assert registered_tool is DummyTool
    assert registered_tool.name == "dummy_tool"
    assert registered_tool.description == "A dummy tool for testing."
    assert registered_tool.risk_score == 0.2
    assert registered_tool.blocked_in == ["auto"]


def test_tool_schema_for_prompt_contains_all_tools() -> None:
    """tool_schema_for_prompt() must format all registered tools."""

    @tool(name="tool_a", description="First tool", permissions=[])
    class ToolA(BaseTool):
        def execute(self, inp: object) -> ToolResult:
            return ToolResult(success=True, output="A")

    @tool(name="tool_b", description="Second tool", permissions=[])
    class ToolB(BaseTool):
        def execute(self, inp: object) -> ToolResult:
            return ToolResult(success=True, output="B")

    schema = tool_schema_for_prompt()
    
    assert "- tool_a: First tool" in schema
    assert "- tool_b: Second tool" in schema


def test_permission_gate_safe_mode_blocks_high_risk() -> None:
    """PermissionGate('safe') must block tools with risk_score > 0.5."""

    @tool(name="risky_tool", description="High risk", permissions=[], risk_score=0.8)
    class RiskyTool(BaseTool):
        def execute(self, inp: object) -> ToolResult:
            return ToolResult(success=True, output="Risky")

    gate = PermissionGate("safe")
    allowed, reason = gate.check(RiskyTool)
    
    assert allowed is False
    assert "exceeds the 0.5 threshold" in reason


def test_permission_gate_auto_mode_allows_high_risk() -> None:
    """PermissionGate('auto') must allow tools with risk_score > 0.5 unless explicitly blocked."""

    @tool(name="risky_tool", description="High risk", permissions=[], risk_score=0.8)
    class RiskyTool(BaseTool):
        def execute(self, inp: object) -> ToolResult:
            return ToolResult(success=True, output="Risky")

    gate = PermissionGate("auto")
    allowed, reason = gate.check(RiskyTool)
    
    assert allowed is True
    assert reason == ""


def test_get_tool_returns_none_for_unknown() -> None:
    """get_tool() must return None when the tool is not in the registry."""
    assert get_tool("nonexistent") is None

