# tools/base.py
# Base types for the HERMES tool system.
# Every tool in the system inherits from BaseTool.
# Every tool execution returns a ToolResult.

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class ToolResult:
    """Standardised return value for every tool execution in HERMES."""

    success: bool
    output: str
    error: str | None = None
    exit_code: int = 0
    duration_seconds: float = 0.0

    def __str__(self) -> str:
        """Return output on success, or a prefixed error message on failure."""
        if self.success:
            return self.output
        return f"ERROR: {self.error}"


class BaseTool(abc.ABC):
    """Abstract base class that every HERMES tool must inherit from.

    Subclasses must:
    - Set the ``name`` class attribute to a unique string identifier.
    - Set the ``description`` class attribute to a one-sentence summary.
    - Implement the ``execute`` method.
    """

    name: str = ""
    description: str = ""
    risk_score: float = 0.0
    blocked_in: list[str] = field(default_factory=list)  # type: ignore[assignment]

    # Use __init_subclass__ to guarantee subclasses carry independent list defaults.
    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "blocked_in" not in cls.__dict__:
            cls.blocked_in = []

    @abc.abstractmethod
    def execute(self, inp: object) -> ToolResult:
        """Execute the tool with the given input and return a ToolResult."""
