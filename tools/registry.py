# tools/registry.py
# The HERMES tool registry.
# All tools are registered here via the @tool decorator.
# The orchestrator uses this registry to dispatch tool calls from Tier 1.

from __future__ import annotations

from typing import Callable

from tools.base import BaseTool

# ---------------------------------------------------------------------------
# Private registry store
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[BaseTool]] = {}


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class ToolValidationError(Exception):
    """Raised when a tool's input fails Pydantic validation."""


class ToolNotFoundError(Exception):
    """Raised when a requested tool name is not present in the registry."""


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def tool(
    name: str,
    description: str,
    permissions: list[str],
    risk_score: float = 0.0,
    blocked_in: list[str] | None = None,
) -> Callable[[type[BaseTool]], type[BaseTool]]:
    """Decorator factory that registers a BaseTool subclass in the global registry.

    Usage::

        @tool(
            name="read_file",
            description="Read a file from disk and return its contents.",
            permissions=["fs_read"],
            risk_score=0.1,
            blocked_in=[],
        )
        class ReadFileTool(BaseTool):
            def execute(self, inp) -> ToolResult:
                ...

    The decorator sets ``name``, ``description``, ``risk_score``, and
    ``blocked_in`` on the class, then stores it in ``_REGISTRY`` under ``name``.
    """
    _blocked_in: list[str] = blocked_in if blocked_in is not None else []

    def decorator(cls: type[BaseTool]) -> type[BaseTool]:
        cls.name = name
        cls.description = description
        cls.risk_score = risk_score
        cls.blocked_in = _blocked_in
        _REGISTRY[name] = cls
        return cls

    return decorator


# ---------------------------------------------------------------------------
# Registry accessors
# ---------------------------------------------------------------------------


def get_tool(name: str) -> type[BaseTool] | None:
    """Return the tool class registered under *name*, or None if not found."""
    return _REGISTRY.get(name)


def list_tools() -> list[str]:
    """Return a sorted list of all registered tool names."""
    return sorted(_REGISTRY.keys())


def tool_schema_for_prompt() -> str:
    """Return a formatted string of all tools suitable for a Tier 1 system prompt.

    Each line has the form ``- tool_name: description``.
    """
    lines: list[str] = [
        f"- {name}: {_REGISTRY[name].description}" for name in sorted(_REGISTRY.keys())
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Permission gate
# ---------------------------------------------------------------------------


class PermissionGate:
    """Evaluates whether a tool is allowed to execute in the current agent mode.

    Modes:
    - ``safe``  — blocks tools with risk_score > 0.5 and any tool listed in
                  its own ``blocked_in`` list when the list contains "safe".
    - ``plan``  — blocks only tools explicitly listed in ``blocked_in`` as "plan".
    - ``auto``  — blocks only tools explicitly listed in ``blocked_in`` as "auto".
    """

    VALID_MODES: frozenset[str] = frozenset({"safe", "plan", "auto"})

    def __init__(self, mode: str) -> None:
        """Initialise the gate with the given operating mode."""
        if mode not in self.VALID_MODES:
            raise ValueError(
                f"Invalid mode '{mode}'. Must be one of {sorted(self.VALID_MODES)}."
            )
        self.mode: str = mode

    def check(self, tool_class: type[BaseTool]) -> tuple[bool, str]:
        """Return (True, '') if allowed, or (False, reason) if blocked.

        A tool is blocked if:
        - Its ``blocked_in`` list contains the current mode, **or**
        - The mode is ``"safe"`` and the tool's ``risk_score`` exceeds 0.5.
        """
        if self.mode in tool_class.blocked_in:
            return False, (
                f"Tool '{tool_class.name}' is explicitly blocked in '{self.mode}' mode."
            )

        if self.mode == "safe" and tool_class.risk_score > 0.5:
            return False, (
                f"Tool '{tool_class.name}' has risk_score={tool_class.risk_score} "
                f"which exceeds the 0.5 threshold for 'safe' mode."
            )

        return True, ""
