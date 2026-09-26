# core/project_intelligence/__init__.py
"""
HERMES 2.x Project Intelligence Subsystem.
Progressive-disclosure project intelligence, scoped rules, skills, and lifecycle bootstrap.
"""

from core.project_intelligence.bootstrap import BootstrapEngine
from core.project_intelligence.hermes_md import HermesMdLoader
from core.project_intelligence.models import (
    BootstrapAction,
    BootstrapCommand,
    BootstrapManifest,
    HermesInstructions,
    ProjectIntelligenceSnapshot,
    Rule,
    RuleMetadata,
    RuleScopeType,
    Skill,
    SkillMetadata,
)
from core.project_intelligence.registry import (
    ProjectIntelligenceRegistry,
    project_intelligence_registry,
)
from core.project_intelligence.rules import RuleEngine
from core.project_intelligence.skills import SkillEngine

__all__ = [
    "BootstrapAction",
    "BootstrapCommand",
    "BootstrapEngine",
    "BootstrapManifest",
    "HermesInstructions",
    "HermesMdLoader",
    "ProjectIntelligenceRegistry",
    "ProjectIntelligenceSnapshot",
    "Rule",
    "RuleEngine",
    "RuleMetadata",
    "RuleScopeType",
    "Skill",
    "SkillEngine",
    "SkillMetadata",
    "project_intelligence_registry",
]
