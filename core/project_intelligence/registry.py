# core/project_intelligence/registry.py
"""
Unified Project Intelligence Registry for HERMES 2.x.
Coordinates the four core intelligence layers:
1. Standing root constitution (HERMES.md)
2. Path-scoped architectural rules (.hermes/rules/)
3. Progressive-disclosure procedural skills (.hermes/skills/)
4. Environment lifecycle bootstrap (.hermes/bootstrap/)

Provides cache invalidation, freshness checks, canonical event emission,
and seamless integration into ContextEngine 2.x.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

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
    Skill,
    SkillMetadata,
    SkillRoutingDecision,
)
from core.project_intelligence.rules import RuleEngine
from core.project_intelligence.skills import SkillEngine
from core.runtime_state.events import EventSeverity, EventType


class ProjectIntelligenceRegistry:
    """
    Central authoritative registry and coordinator for project intelligence.
    Emits canonical runtime state events for all lifecycle actions.
    """

    def __init__(
        self,
        workspace_root: Optional[Path | str] = None,
        canonical_skills_root: Optional[Path | str] = None,
        event_bus: Any = None,
        mission_id: str = "default",
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self._explicit_canonical_skills_root = Path(canonical_skills_root).resolve() if canonical_skills_root else None
        self.event_bus = event_bus
        self.mission_id = mission_id

        # Initialize the 4 subsystem engines
        self.hermes_md_loader = HermesMdLoader(workspace_root=self.workspace_root)
        self.rule_engine = RuleEngine(workspace_root=self.workspace_root)
        self.skill_engine = SkillEngine(
            workspace_root=self.workspace_root,
            canonical_skills_root=self._explicit_canonical_skills_root,
        )
        self.bootstrap_engine = BootstrapEngine(workspace_root=self.workspace_root)

        # Active state tracking
        self._active_rules: Dict[str, Rule] = {}
        self._active_skills: Dict[str, Skill] = {}
        self._active_resources: Dict[Tuple[str, str], str] = {}
        self._discovered: bool = False

    @property
    def canonical_skills_root(self) -> Path:
        """Authoritative canonical skills directory path."""
        if self._explicit_canonical_skills_root and self._explicit_canonical_skills_root.is_dir():
            return self._explicit_canonical_skills_root
        return self.skill_engine.canonical_root

    # ── Discovery & Snapshot ──────────────────────────────────────────────────

    def discover(self, force_reload: bool = False) -> ProjectIntelligenceSnapshot:
        """
        Discover and index all project intelligence sources.
        Emits canonical events and returns a comprehensive snapshot.
        """
        # 1. Root instructions (HERMES.md)
        hermes_md = self.hermes_md_loader.load(force_reload=force_reload)

        # 2. Path-scoped rules
        rule_index = self.rule_engine.index_rules(force_reload=force_reload)
        for r_name, r_meta in rule_index.items():
            self._publish_event(
                EventType.RULE_DISCOVERED,
                payload={"name": r_name, "paths": r_meta.paths, "scope": r_meta.scope_type.value},
            )

        # 3. Agent Skills (Level 1: Metadata index only)
        skill_index = self.skill_engine.index_skills(force_reload=force_reload)
        for s_name, s_meta in skill_index.items():
            self._publish_event(
                EventType.SKILL_DISCOVERED,
                payload={"name": s_name, "triggers": s_meta.triggers, "tools": s_meta.allowed_tools},
            )

        # 4. Bootstrap lifecycle commands
        bootstrap_manifest = self.bootstrap_engine.discover(force_reload=force_reload)
        for act, cmd in bootstrap_manifest.commands.items():
            self._publish_event(
                EventType.BOOTSTRAP_DISCOVERED,
                payload={"action": act, "command": cmd.command, "source": cmd.source},
            )

        self._discovered = True

        snapshot = self.snapshot()

        # Emit high-level summary event
        self._publish_event(
            EventType.PROJECT_INTELLIGENCE_DISCOVERED,
            payload=snapshot.to_dict(),
        )

        return snapshot

    def snapshot(self) -> ProjectIntelligenceSnapshot:
        """Produce a lightweight diagnostic snapshot of all project intelligence state."""
        h_status = "NOT_FOUND"
        h_lines = 0
        if self.hermes_md_loader._cached_instructions:
            h_inst = self.hermes_md_loader._cached_instructions
            h_status = "OVERSIZED" if h_inst.is_oversized else ("LOADED" if h_inst.content else "EMPTY")
            h_lines = h_inst.line_count

        r_count = len(self.rule_engine._metadata_index)
        act_r_count = len(self._active_rules)

        s_count = len(self.skill_engine._metadata_index)
        act_s_count = len(self._active_skills)

        b_manifest = self.bootstrap_engine._manifest
        b_count = len(b_manifest.commands) if b_manifest else 0

        return ProjectIntelligenceSnapshot(
            hermes_md_status=h_status,
            hermes_md_lines=h_lines,
            rule_count=r_count,
            active_rule_count=act_r_count,
            skill_count=s_count,
            active_skill_count=act_s_count,
            bootstrap_command_count=b_count,
            active_bootstrap_count=b_count,
            canonical_skills_root=str(self.canonical_skills_root),
        )

    # ── Freshness & Invalidation ──────────────────────────────────────────────

    def check_freshness(self) -> Dict[str, Any]:
        """
        Check freshness across all 4 intelligence layers and emit invalidation events.
        Enables runtime responsiveness when files are created, edited, or deleted.
        """
        changes: Dict[str, Any] = {}

        # 1. HERMES.md
        h_changed, fresh_h = self.hermes_md_loader.check_freshness()
        if h_changed and fresh_h:
            changes["hermes_md"] = True
            self._publish_event(
                EventType.PROJECT_INSTRUCTIONS_CHANGED,
                payload={
                    "path": fresh_h.path,
                    "lines": fresh_h.line_count,
                    "sha256": fresh_h.sha256_hash,
                    "is_oversized": fresh_h.is_oversized,
                },
            )

        # 2. Scoped Rules
        r_changed, affected_rules = self.rule_engine.check_freshness()
        if r_changed:
            changes["rules"] = affected_rules
            for r_name in affected_rules:
                self._active_rules.pop(r_name, None)
                self._publish_event(
                    EventType.RULE_CHANGED,
                    payload={"rule_name": r_name},
                )
                self._publish_event(
                    EventType.RULE_INVALIDATED,
                    payload={"rule_name": r_name, "reason": "file_modified_or_index_changed"},
                )

        # 3. Skills
        s_changed, affected_skills = self.skill_engine.check_freshness()
        if s_changed:
            changes["skills"] = affected_skills
            for s_name in affected_skills:
                self._active_skills.pop(s_name, None)
                # Also drop cached resources
                drop_keys = [k for k in self._active_resources.keys() if k[0] == s_name]
                for k in drop_keys:
                    self._active_resources.pop(k, None)

                self._publish_event(
                    EventType.SKILL_CHANGED,
                    payload={"skill_name": s_name},
                )
                self._publish_event(
                    EventType.SKILL_INVALIDATED,
                    payload={"skill_name": s_name, "reason": "skill_file_modified"},
                )

        # 4. Bootstrap
        b_changed, fresh_b = self.bootstrap_engine.check_freshness()
        if b_changed and fresh_b:
            changes["bootstrap"] = True
            self._publish_event(
                EventType.BOOTSTRAP_CHANGED,
                payload={"commands": list(fresh_b.commands.keys())},
            )
            self._publish_event(
                EventType.BOOTSTRAP_INVALIDATED,
                payload={"reason": "manifest_modified"},
            )

        return changes

    # ── Root Instructions (HERMES.md) ─────────────────────────────────────────

    def get_active_project_rules(self) -> Optional[HermesInstructions]:
        """Retrieve root standing project instructions."""
        return self.hermes_md_loader.load()

    # ── Path-Scoped Rules ─────────────────────────────────────────────────────

    def match_scoped_rules(
        self,
        active_files: List[str] | Set[str],
        task_description: str = "",
    ) -> List[Rule]:
        """
        Evaluate active file paths against indexed scoped rules.
        Loads rule bodies lazily and sorts by precedence.
        """
        file_list = list(active_files)
        matched = self.rule_engine.match_rules(file_list)

        for rule in matched:
            name = rule.metadata.name
            if name not in self._active_rules:
                self._active_rules[name] = rule
                self._publish_event(
                    EventType.RULE_LOADED,
                    payload={
                        "name": name,
                        "scope": rule.metadata.scope_type.value,
                        "enforcement": rule.metadata.enforcement,
                        "body_length": len(rule.body),
                    },
                )
            else:
                self._active_rules[name] = rule

        return matched

    def get_rule_body(self, name: str) -> Optional[Rule]:
        """Explicitly load a scoped rule by name."""
        rule = self.rule_engine.get_rule_body(name)
        if rule:
            self._active_rules[name] = rule
        return rule

    # ── Agent Skills (3-Level Progressive Disclosure & Routing) ───────────────

    def match_skills(
        self,
        task_description: str,
        active_tools: Optional[List[str]] = None,
        max_candidates: int = 3,
    ) -> List[SkillMetadata]:
        """
        Level 1: Query indexed skills by task relevance.
        Returns lightweight metadata candidates without loading bodies.
        """
        return self.skill_engine.match_skills(
            task_text=task_description,
            active_tools=active_tools,
            max_candidates=max_candidates,
        )

    def route_skills(
        self,
        task_description: str,
        workspace_signals: Optional[Dict[str, Any]] = None,
        max_candidates: int = 3,
    ) -> SkillRoutingDecision:
        """
        Intelligently route task to relevant skills based on intent and workspace signals.
        Emits SKILL_ROUTING_COMPLETED and SKILL_SELECTED events.
        """
        decision = self.skill_engine.route_skills(
            task_description=task_description,
            workspace_signals=workspace_signals,
            max_candidates=max_candidates,
        )

        # Emit canonical routing completed event
        self._publish_event(
            EventType.SKILL_ROUTING_COMPLETED,
            payload={
                "selected_skills": decision.selected_skills,
                "candidate_scores": decision.candidate_scores,
                "rejection_reasons": decision.rejection_reasons,
                "is_fallback": decision.is_fallback,
                "decision_rationale": decision.decision_rationale,
            },
        )

        # Emit individual selection events
        for skill_name in decision.selected_skills:
            self._publish_event(
                EventType.SKILL_SELECTED,
                payload={
                    "skill_name": skill_name,
                    "score": decision.candidate_scores.get(skill_name, 1.0),
                    "rationale": decision.decision_rationale,
                    "is_fallback": decision.is_fallback,
                },
            )

        return decision

    def load_skill_body(self, name: str) -> Optional[Skill]:
        """
        Level 2: Load SKILL.md body on demand when an agent activates a skill.
        Emits SKILL_LOADED on success, or SKILL_LOAD_FAILED on failure.
        """
        try:
            skill = self.skill_engine.load_skill(name)
        except Exception as exc:
            self._publish_event(
                EventType.SKILL_LOAD_FAILED,
                severity=EventSeverity.ERROR,
                payload={
                    "name": name,
                    "error": str(exc),
                    "reason": "load_exception",
                },
            )
            return None

        if skill:
            self._active_skills[name] = skill
            self._publish_event(
                EventType.SKILL_LOADED,
                payload={
                    "name": name,
                    "allowed_tools": skill.metadata.allowed_tools,
                    "body_length": len(skill.body),
                    "sha256": skill.metadata.sha256_hash,
                },
            )
            return skill
        else:
            self._publish_event(
                EventType.SKILL_LOAD_FAILED,
                severity=EventSeverity.WARNING,
                payload={
                    "name": name,
                    "error": f"Skill '{name}' could not be loaded or found",
                    "reason": "file_missing_or_invalid",
                },
            )
            return None

    def get_active_skills(self) -> Dict[str, Skill]:
        """Return snapshot dictionary of currently active/loaded skills."""
        return dict(self._active_skills)

    def restore_skills(self, skill_names: List[str]) -> List[Skill]:
        """
        Restore and reload skills by name (e.g. during mission continuation/recovery).
        """
        restored = []
        for name in skill_names:
            s = self.load_skill_body(name)
            if s:
                restored.append(s)
        return restored

    def sync_skills_to_context_engine(
        self,
        context_engine: Any,
        skills: Optional[List[Skill]] = None,
    ) -> List[str]:
        """
        Register active skills into ContextEngine 2.x under ContextSectionType.SKILLS.
        Emits SKILL_CONTEXT_ATTACHED for each registered skill.
        Returns list of attached skill names.
        """
        from core.context.models import (
            ContextItem,
            ContextPriority,
            ContextProvenance,
            ContextSectionType,
            ContextSourceType,
        )

        skills_to_sync = skills if skills is not None else list(self._active_skills.values())
        attached_names: List[str] = []

        for skill in skills_to_sync:
            meta = skill.metadata
            item_id = f"skill_{meta.name}"
            allowed_tools_str = ",".join(meta.allowed_tools) if meta.allowed_tools else ""
            content = (
                f'<skill name="{meta.name}" allowed_tools="{allowed_tools_str}">\n'
                f"{skill.body}\n"
                f"</skill>"
            )
            item = ContextItem(
                id=item_id,
                section=ContextSectionType.SKILLS,
                content=content,
                provenance=ContextProvenance(
                    source_type=ContextSourceType.SKILL,
                    source_id=meta.name,
                    file_path=meta.source_path,
                    content_hash=meta.sha256_hash,
                ),
                priority=ContextPriority.IMPORTANT,
                relevance_score=0.90,
                metadata={
                    "name": meta.name,
                    "triggers": meta.triggers,
                    "allowed_tools": meta.allowed_tools,
                    "fingerprint": meta.sha256_hash,
                },
            )
            context_engine.register_item(item)
            attached_names.append(meta.name)

            self._publish_event(
                EventType.SKILL_CONTEXT_ATTACHED,
                payload={
                    "name": meta.name,
                    "section": "SKILLS",
                    "item_id": item_id,
                    "token_length": len(skill.body.split()),
                },
            )

        return attached_names

    def load_skill_resource(
        self,
        skill_name: str,
        resource_rel_path: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Level 3: Load a supporting file inside a skill directory on demand.
        Enforces security path containment.
        Returns: (content_or_none, error_message_or_none)
        """
        content, err = self.skill_engine.load_skill_resource(skill_name, resource_rel_path)
        if content is not None:
            self._active_resources[(skill_name, resource_rel_path)] = content
            self._publish_event(
                EventType.SKILL_RESOURCE_LOADED,
                payload={
                    "skill_name": skill_name,
                    "resource_path": resource_rel_path,
                    "length": len(content),
                },
            )
        return content, err

    # ── Bootstrap Commands ────────────────────────────────────────────────────

    def get_bootstrap_command(self, action: str | BootstrapAction) -> Optional[BootstrapCommand]:
        """Retrieve lifecycle command for an action (e.g. test, lint, build)."""
        cmd = self.bootstrap_engine.get_command(action)
        if cmd:
            self._publish_event(
                EventType.BOOTSTRAP_LOADED,
                payload={"action": cmd.action, "command": cmd.command, "risk": cmd.risk},
            )
        return cmd

    def get_bootstrap_manifest(self) -> BootstrapManifest:
        """Get full lifecycle manifest (explicit or auto-detected)."""
        return self.bootstrap_engine.discover()

    # ── Context Engine Integration ────────────────────────────────────────────

    def sync_to_context_engine(
        self,
        context_engine: Any,
        active_files: Optional[List[str] | Set[str]] = None,
        task_description: str = "",
    ) -> None:
        """
        Synchronize Project Intelligence into ContextEngine 2.x items:
        1. Ingests HERMES.md into ContextSectionType.PROJECT_RULES (tagged <project_rule>).
        2. Ingests matching Scoped Rules into ContextSectionType.SCOPED_RULES (tagged <scoped_rule>).
        3. Fences all content to prevent prompt injection.
        """
        from core.context.models import (
            ContextItem,
            ContextPriority,
            ContextProvenance,
            ContextSectionType,
            ContextSourceType,
        )

        # 1. Freshness check across all subsystems
        self.check_freshness()

        # 2. HERMES.md -> PROJECT_RULES
        h_inst = self.get_active_project_rules()
        if h_inst and h_inst.content:
            p_content = f"<project_constitution path=\"{h_inst.path}\">\n{h_inst.content}\n</project_constitution>"
            item_id = "project_instructions_hermes_md"
            item = ContextItem(
                id=item_id,
                section=ContextSectionType.PROJECT_RULES,
                content=p_content,
                provenance=ContextProvenance(
                    source_type=ContextSourceType.PROJECT_RULE,
                    source_id="HERMES.md",
                    file_path=h_inst.path,
                    content_hash=h_inst.sha256_hash,
                ),
                priority=ContextPriority.MANDATORY,
                relevance_score=1.0,
                metadata={
                    "is_oversized": h_inst.is_oversized,
                    "line_count": h_inst.line_count,
                    "warning": h_inst.warning,
                },
            )
            context_engine.register_item(item)

        # 3. Scoped Rules -> SCOPED_RULES
        matched_rule_ids: Set[str] = set()
        if active_files:
            matched_rules = self.match_scoped_rules(active_files, task_description=task_description)
            for rule in matched_rules:
                r_meta = rule.metadata
                r_id = f"scoped_rule_{r_meta.name}"
                matched_rule_ids.add(r_id)
                scope_val = r_meta.scope_type.value
                r_content = (
                    f"<scoped_rule name=\"{r_meta.name}\" scope=\"{scope_val}\" enforcement=\"{r_meta.enforcement}\">\n"
                    f"{rule.body}\n"
                    f"</scoped_rule>"
                )
                item = ContextItem(
                    id=r_id,
                    section=ContextSectionType.SCOPED_RULES,
                    content=r_content,
                    provenance=ContextProvenance(
                        source_type=ContextSourceType.SCOPED_RULE,
                        source_id=r_meta.name,
                        file_path=r_meta.source_path,
                        content_hash=r_meta.sha256_hash,
                    ),
                    priority=ContextPriority.IMPORTANT if r_meta.enforcement == "mandatory" else ContextPriority.OPTIONAL,
                    relevance_score=0.95 if r_meta.enforcement == "mandatory" else 0.80,
                    metadata={
                        "scope_type": scope_val,
                        "enforcement": r_meta.enforcement,
                        "paths": r_meta.paths,
                    },
                )
                context_engine.register_item(item)

        # Clean up stale scoped rules that no longer match current active_files
        for item_id in list(context_engine._items.keys()):
            if item_id.startswith("scoped_rule_") and item_id not in matched_rule_ids:
                context_engine._items.pop(item_id, None)

        # 4. Active Skills -> SKILLS
        if self._active_skills:
            self.sync_skills_to_context_engine(context_engine)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _publish_event(
        self,
        event_type: EventType,
        severity: EventSeverity = EventSeverity.INFO,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Helper to emit canonical runtime state events to event_bus if available."""
        if not self.event_bus:
            return

        from core.runtime_state.events import HermesEvent

        event = HermesEvent(
            event_type=event_type,
            mission_id=self.mission_id,
            source="project_intelligence",
            severity=severity,
            payload=payload or {},
        )

        if hasattr(self.event_bus, "publish_nowait"):
            self.event_bus.publish_nowait(event)
        elif hasattr(self.event_bus, "publish"):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.event_bus.publish(event))
            except Exception:
                pass


# Global singleton
project_intelligence_registry = ProjectIntelligenceRegistry()
