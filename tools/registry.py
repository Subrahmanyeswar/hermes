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
# Tool Aliases
# ---------------------------------------------------------------------------

TOOL_ALIASES: dict[str, str] = {
    "list_dir": "list_directory",
}


def _ensure_tools_loaded() -> None:
    if not _REGISTRY:
        import sys
        import importlib
        for mod_name in [
            "tools.file_tools",
            "tools.shell_tools",
            "tools.network_tools",
            "tools.git_tools",
            "tools.memory_tools",
            "tools.export_tools",
            "tools.vision_tools",
        ]:
            if mod_name in sys.modules:
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass
            else:
                try:
                    importlib.import_module(mod_name)
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Registry accessors
# ---------------------------------------------------------------------------


def get_tool(name: str) -> type[BaseTool] | None:
    """Return the tool class registered under *name*, resolving aliases if needed."""
    _ensure_tools_loaded()
    canonical_name = TOOL_ALIASES.get(name, name)
    return _REGISTRY.get(canonical_name)


def list_tools() -> list[str]:
    """Return a sorted list of all registered tool names."""
    _ensure_tools_loaded()
    return sorted(_REGISTRY.keys())


def tool_schema_for_prompt() -> str:
    """Return a formatted string of all tools suitable for a Tier 1 system prompt.

    BENCHMARK ISOLATION:
    Excludes production performance optimization tools such as write_files_batch
    so benchmark mode unconditionally sees exactly the 20 canonical baseline tools.
    """
    _ensure_tools_loaded()
    lines: list[str] = [
        f"- {name}: {_REGISTRY[name].description}"
        for name in sorted(_REGISTRY.keys())
        if name != "write_files_batch"
    ]
    return "\n".join(lines)


def selective_tool_schema_for_prompt(
    required_tools: list[str] | None = None,
    execution_mode: str = "production",
    allow_batch_tools: bool = False,
) -> str:
    """Return a formatted string of tools suitable for a Tier 1 system prompt.

    BENCHMARK ISOLATION GUARANTEE:
    When execution_mode == "benchmark" or required_tools is None,
    all 20 canonical tools are unconditionally serialized (identical to tool_schema_for_prompt()).
    write_files_batch is strictly excluded from benchmark schemas.

    PRODUCTION / DEMO / PERFORMANCE OPTIMIZATION:
    Serializes only the task-relevant tools plus minimal diagnostic tools
    (e.g., read_file, list_directory, create_folder when writing).
    Exposes write_files_batch only when allow_batch_tools=True or explicitly required.
    Tool authorization is strictly enforced by PermissionGate and _REGISTRY;
    this optimization strictly controls model visibility without altering system authorization.
    """
    if execution_mode == "benchmark" or required_tools is None:
        return tool_schema_for_prompt()

    _ensure_tools_loaded()
    selected = set(required_tools)
    if any(t in selected for t in ("write_file", "append_file", "write_files_batch")):
        selected.update(["read_file", "list_directory", "create_folder"])
        if allow_batch_tools:
            selected.add("write_files_batch")
    elif any(t in selected for t in ("run_tests", "run_python")):
        selected.update(["read_file", "bash_exec"])
    elif not selected:
        selected = {"read_file", "write_file", "list_directory", "create_folder", "bash_exec"}

    if not allow_batch_tools and "write_files_batch" in selected and "write_files_batch" not in required_tools:
        selected.discard("write_files_batch")

    active_tools = sorted([name for name in selected if name in _REGISTRY])
    if not active_tools:
        return tool_schema_for_prompt()

    lines: list[str] = [
        f"- {name}: {_REGISTRY[name].description}" for name in active_tools
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
