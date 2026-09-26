# tools/platform/specs.py
"""
Canonical Tool Specification and Metadata Definitions for HERMES 2.x Tool Platform.
Provides provider-independent schemas, risk classifications, examples, and tool identity.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Type
from pydantic import BaseModel

from tools.base import BaseTool


class RiskLevel(str, enum.Enum):
    READ_ONLY = "READ_ONLY"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ToolAvailability(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"
    RESTRICTED = "RESTRICTED"


class ResponseFormat(str, enum.Enum):
    CONCISE = "concise"
    NORMAL = "normal"
    DETAILED = "detailed"


@dataclass
class RiskMetadata:
    """Explicit risk accounting and security profile for a tool."""
    risk_score: float = 0.0
    risk_level: RiskLevel = RiskLevel.READ_ONLY
    destructive: bool = False
    writes_files: bool = False
    executes_commands: bool = False
    network_access: bool = False
    requires_confirmation: bool = False
    reversible: bool = True
    idempotent: bool = True
    affects_workspace: bool = False
    affects_external_system: bool = False
    blocked_in: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level.value if isinstance(self.risk_level, RiskLevel) else str(self.risk_level),
            "destructive": self.destructive,
            "writes_files": self.writes_files,
            "executes_commands": self.executes_commands,
            "network_access": self.network_access,
            "requires_confirmation": self.requires_confirmation,
            "reversible": self.reversible,
            "idempotent": self.idempotent,
            "affects_workspace": self.affects_workspace,
            "affects_external_system": self.affects_external_system,
            "blocked_in": self.blocked_in,
        }


@dataclass
class ToolExample:
    """Agent-facing example demonstrating valid or failure usage of a tool."""
    intent: str
    input: Dict[str, Any]
    expected_output_summary: str = ""
    is_failure_example: bool = False
    failure_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "input": self.input,
            "expected_output_summary": self.expected_output_summary,
            "is_failure_example": self.is_failure_example,
            "failure_reason": self.failure_reason,
        }


@dataclass
class ToolSchema:
    """Provider-independent machine-readable schema definition."""
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    required: List[str] = field(default_factory=list)
    output_semantics: str = ""
    version: str = "1.0"

    def to_openai_dict(self) -> Dict[str, Any]:
        """Convert to standard OpenAI / NVIDIA NIM function tool definition."""
        properties = self.parameters.get("properties", {})
        required = self.required or self.parameters.get("required", [])
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description[:500],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_ollama_dict(self) -> Dict[str, Any]:
        """Convert to Ollama tool format."""
        return self.to_openai_dict()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "required": self.required,
            "output_semantics": self.output_semantics,
            "version": self.version,
        }


@dataclass
class ToolSpec:
    """
    Authoritative specification for an agent-facing tool.
    Connects canonical identity, documentation, schemas, examples,
    risk profiles, and underlying implementations.
    """
    canonical_name: str
    display_name: str
    description: str
    category: str  # Semantic namespace: fs, shell, search, task, user, git, memory, etc.
    schema: ToolSchema
    risk: RiskMetadata
    version: str = "1.0"
    examples: List[ToolExample] = field(default_factory=list)
    availability: ToolAvailability = ToolAvailability.AVAILABLE
    aliases: List[str] = field(default_factory=list)
    implementation_cls: Optional[Type[BaseTool]] = None
    batch_safe: bool = False
    tags: List[str] = field(default_factory=list)

    @property
    def is_core(self) -> bool:
        """Check if this tool belongs to the always-available core set."""
        return self.canonical_name in {
            "fs.read",
            "fs.edit",
            "fs.write",
            "shell.bash",
            "search.glob",
            "search.grep",
            "task.todo",
            "task.delegate",
            "user.ask",
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "schema": self.schema.to_dict(),
            "risk": self.risk.to_dict(),
            "version": self.version,
            "examples": [e.to_dict() for e in self.examples],
            "availability": self.availability.value if isinstance(self.availability, ToolAvailability) else str(self.availability),
            "aliases": self.aliases,
            "batch_safe": self.batch_safe,
            "tags": self.tags,
            "is_core": self.is_core,
        }

