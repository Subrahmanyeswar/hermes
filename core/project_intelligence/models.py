# core/project_intelligence/models.py
"""
Canonical Data Models and Schemas for HERMES 2.x Project Intelligence Layer.
Provides typed definitions for HERMES.md, Scoped Rules, Skills, and Bootstrap commands.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


@dataclass
class HermesInstructions:
    """Loaded project constitution from root HERMES.md."""
    path: str
    content: str
    line_count: int
    size_bytes: int
    mtime_ns: int
    sha256_hash: str
    loaded_at: float = field(default_factory=time.time)
    is_oversized: bool = False
    warning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "line_count": self.line_count,
            "size_bytes": self.size_bytes,
            "sha256_hash": self.sha256_hash,
            "is_oversized": self.is_oversized,
            "warning": self.warning,
            "loaded_at": self.loaded_at,
        }


class RuleScopeType(str, Enum):
    """Scope granularity for deterministic rule precedence."""
    FILE_SPECIFIC = "file_specific"   # Exact file match (e.g. src/auth/login.py)
    SUBSYSTEM = "subsystem"           # Subsystem or nested directory (e.g. src/frontend/components/**)
    DIRECTORY = "directory"           # Directory root (e.g. src/frontend/**, tests/**)
    LANGUAGE = "language"             # File extension pattern (e.g. **/*.py, **/*.tsx)
    GENERAL = "general"               # Catch-all (* or broad scope)


@dataclass
class RuleMetadata:
    """Lightweight metadata index for a path-scoped rule."""
    name: str
    description: str
    paths: List[str]
    priority: int = 100
    scope_type: RuleScopeType = RuleScopeType.DIRECTORY
    enabled: bool = True
    tags: List[str] = field(default_factory=list)
    source_path: str = ""
    sha256_hash: str = ""
    mtime_ns: int = 0
    enforcement: str = "guidance"  # "guidance" or "mandatory"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "paths": self.paths,
            "priority": self.priority,
            "scope_type": self.scope_type.value,
            "enabled": self.enabled,
            "tags": self.tags,
            "source_path": self.source_path,
            "sha256_hash": self.sha256_hash,
            "enforcement": self.enforcement,
        }


@dataclass
class Rule:
    """Full rule definition with lazily loaded instruction body."""
    metadata: RuleMetadata
    body: str
    loaded_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "body_length": len(self.body),
            "loaded_at": self.loaded_at,
        }


@dataclass
class SkillMetadata:
    """Initial lightweight metadata index for an Agent Skill."""
    name: str
    description: str
    triggers: List[str] = field(default_factory=list)
    priority: int = 1
    allowed_tools: List[str] = field(default_factory=list)
    disable_model_invocation: bool = False
    context_fork: bool = False
    source_dir: str = ""
    skill_file: str = ""
    sha256_hash: str = ""
    mtime_ns: int = 0
    tags: List[str] = field(default_factory=list)

    @property
    def source_path(self) -> str:
        return self.skill_file or self.source_dir

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "triggers": self.triggers,
            "priority": self.priority,
            "allowed_tools": self.allowed_tools,
            "disable_model_invocation": self.disable_model_invocation,
            "context_fork": self.context_fork,
            "source_dir": self.source_dir,
            "skill_file": self.skill_file,
            "sha256_hash": self.sha256_hash,
        }


@dataclass
class Skill:
    """Full skill object with lazily loaded SKILL.md body and on-demand resources."""
    metadata: SkillMetadata
    body: str
    resources: Dict[str, str] = field(default_factory=dict)
    loaded_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "body_length": len(self.body),
            "resources_loaded": list(self.resources.keys()),
            "loaded_at": self.loaded_at,
        }


@dataclass
class SkillRoutingDecision:
    """Decision output of progressive skill routing based on intent & workspace signals."""
    task_text: str
    selected_skills: List[str] = field(default_factory=list)
    selected_skill_metadata: List[SkillMetadata] = field(default_factory=list)
    candidate_scores: Dict[str, float] = field(default_factory=dict)
    rejection_reasons: Dict[str, str] = field(default_factory=dict)
    decision_rationale: str = ""
    is_fallback: bool = False
    signals_used: Dict[str, Any] = field(default_factory=dict)
    routed_at: float = field(default_factory=time.time)

    @property
    def scores(self) -> Dict[str, float]:
        return self.candidate_scores

    @property
    def reasons(self) -> Dict[str, str]:
        return self.rejection_reasons

    @property
    def rejected_skills(self) -> List[Tuple[str, str]]:
        return list(self.rejection_reasons.items())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_text": self.task_text,
            "selected_skills": self.selected_skills,
            "selected_skill_metadata": [s.to_dict() for s in self.selected_skill_metadata],
            "candidate_scores": self.candidate_scores,
            "rejection_reasons": self.rejection_reasons,
            "decision_rationale": self.decision_rationale,
            "is_fallback": self.is_fallback,
            "signals_used": self.signals_used,
            "routed_at": self.routed_at,
        }


class BootstrapAction(str, Enum):
    """Canonical lifecycle actions for repository execution."""
    INSTALL = "install"
    START = "start"
    TEST = "test"
    LINT = "lint"
    BUILD = "build"
    DEV = "dev"


@dataclass
class BootstrapCommand:
    """A single lifecycle command definition."""
    action: str
    command: str
    working_directory: str = "."
    platform: str = "all"  # "all", "windows", "linux", "darwin"
    timeout_seconds: int = 300
    risk: str = "medium"
    interactive: bool = False
    source: str = "project"  # "project" (declared in .hermes/bootstrap) vs "auto_detected"
    is_stale: bool = False
    description: str = ""
    expected_exit_codes: List[int] = field(default_factory=lambda: [0])
    prerequisites: List[str] = field(default_factory=list)
    env_vars: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "command": self.command,
            "working_directory": self.working_directory,
            "platform": self.platform,
            "timeout_seconds": self.timeout_seconds,
            "risk": self.risk,
            "interactive": self.interactive,
            "source": self.source,
            "is_stale": self.is_stale,
            "description": self.description,
            "expected_exit_codes": self.expected_exit_codes,
            "prerequisites": self.prerequisites,
            "env_vars": self.env_vars,
        }


@dataclass
class BootstrapManifest:
    """Manifest of lifecycle commands for project bootstrap."""
    commands: Dict[str, BootstrapCommand] = field(default_factory=dict)
    source_file: Optional[str] = None
    sha256_hash: str = ""
    manifest_type: str = "explicit"  # "explicit" vs "workspace_detected"
    loaded_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "commands": {k: v.to_dict() for k, v in self.commands.items()},
            "source_file": self.source_file,
            "sha256_hash": self.sha256_hash,
            "manifest_type": self.manifest_type,
            "loaded_at": self.loaded_at,
        }


@dataclass
class ProjectIntelligenceSnapshot:
    """Diagnostic overview of the entire project intelligence state."""
    hermes_md_status: str
    hermes_md_lines: int
    rule_count: int
    active_rule_count: int
    skill_count: int
    active_skill_count: int
    bootstrap_command_count: int
    active_bootstrap_count: int
    canonical_skills_root: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hermes_md_status": self.hermes_md_status,
            "hermes_md_lines": self.hermes_md_lines,
            "rule_count": self.rule_count,
            "active_rule_count": self.active_rule_count,
            "skill_count": self.skill_count,
            "active_skill_count": self.active_skill_count,
            "bootstrap_command_count": self.bootstrap_command_count,
            "active_bootstrap_count": self.active_bootstrap_count,
            "canonical_skills_root": self.canonical_skills_root,
            "timestamp": self.timestamp,
        }
