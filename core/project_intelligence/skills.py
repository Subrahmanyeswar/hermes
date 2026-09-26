# core/project_intelligence/skills.py
"""
Progressive-Disclosure Agent Skills Engine for HERMES 2.x Project Intelligence.
Implements the 3-level progressive disclosure model:
Level 1: Lightweight Metadata Index at session start
Level 2: SKILL.md body loaded only when task matches
Level 3: Supporting resources loaded only when explicitly requested
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml
from loguru import logger

from core.project_intelligence.models import Skill, SkillMetadata


class SkillEngine:
    """
    Manages discovery, metadata indexing, on-demand body loading,
    and safe resource resolution for Agent Skills.
    """

    MAX_RESOURCE_DEPTH = 2

    def __init__(self, workspace_root: Optional[Path | str] = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self._metadata_index: Dict[str, SkillMetadata] = {}
        self._body_cache: Dict[str, Skill] = {}

    def discover_skills_dirs(self) -> List[Path]:
        """Locate skills directories in workspace."""
        candidates = [
            self.workspace_root / ".hermes" / "skills",
            self.workspace_root / "skills",
        ]
        return [c for c in candidates if c.exists() and c.is_dir()]

    def index_skills(self, force_reload: bool = False) -> Dict[str, SkillMetadata]:
        """
        Level 1: Index skill metadata (name, description, triggers, allowed_tools)
        without loading full SKILL.md bodies or resources.
        """
        dirs = self.discover_skills_dirs()
        if not dirs:
            self._metadata_index = {}
            return {}

        index: Dict[str, SkillMetadata] = {}
        for s_dir in dirs:
            try:
                for entry in sorted(s_dir.iterdir()):
                    if entry.is_dir():
                        skill_file = entry / "SKILL.md"
                        if skill_file.exists():
                            meta = self._parse_skill_metadata(entry, skill_file)
                            if meta and meta.name not in index:
                                index[meta.name] = meta
            except Exception as exc:
                logger.error(f"SkillEngine: error scanning '{s_dir}': {exc}")

        self._metadata_index = index
        return index

    def match_skills(
        self,
        task_text: str,
        active_tools: Optional[List[str]] = None,
        max_candidates: int = 3,
    ) -> List[SkillMetadata]:
        """
        Find candidate skills based on lexical overlap with triggers, name, and description.
        Only metadata is returned; skill bodies remain unloaded.
        """
        if not self._metadata_index:
            self.index_skills()

        if not task_text:
            return []

        task_words = set(re.findall(r"\w+", task_text.lower()))
        stopwords = {"the", "a", "an", "is", "in", "to", "and", "or", "of", "for", "with", "at", "by", "on"}
        keywords = {w for w in task_words if len(w) > 2 and w not in stopwords}

        scored_candidates: List[Tuple[SkillMetadata, float]] = []

        for name, meta in self._metadata_index.items():
            if meta.disable_model_invocation:
                continue

            score = 0.0

            # 1. Trigger matches (high weight)
            for trig in meta.triggers:
                trig_words = set(re.findall(r"\w+", trig.lower()))
                if trig_words and trig_words.issubset(keywords):
                    score += 0.50
                elif trig.lower() in task_text.lower():
                    score += 0.40

            # 2. Name match
            if name.lower() in task_text.lower():
                score += 0.60

            # 3. Description keyword overlap
            desc_words = set(re.findall(r"\w+", meta.description.lower()))
            overlap = len(keywords.intersection(desc_words))
            if overlap:
                score += min(0.30, overlap * 0.05)

            # 4. Priority boost
            score += meta.priority * 0.02

            if score >= 0.25:
                scored_candidates.append((meta, score))

        # Sort by score descending
        sorted_candidates = sorted(scored_candidates, key=lambda x: x[1], reverse=True)
        return [c[0] for c in sorted_candidates[:max_candidates]]

    def load_skill(self, name: str) -> Optional[Skill]:
        """
        Level 2: Load SKILL.md body on demand when a skill is activated.
        """
        if name in self._body_cache:
            return self._body_cache[name]

        meta = self._metadata_index.get(name)
        if not meta:
            self.index_skills()
            meta = self._metadata_index.get(name)
        if not meta:
            return None

        p = Path(meta.skill_file)
        if not p.exists():
            return None

        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            # Strip YAML frontmatter if present
            if content.startswith("---"):
                parts = content.split("---", 2)
                body = parts[2].strip() if len(parts) >= 3 else content
            else:
                body = content.strip()

            skill_obj = Skill(metadata=meta, body=body)
            self._body_cache[name] = skill_obj
            return skill_obj
        except Exception as exc:
            logger.error(f"SkillEngine: error loading body for skill '{name}': {exc}")
            return None

    def load_skill_resource(self, skill_name: str, resource_rel_path: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Level 3: Load a specific supporting resource file on demand.
        Guarantees path containment within skill directory (blocks ../ traversal).
        Returns: (content_or_none, error_or_none)
        """
        skill = self.load_skill(skill_name)
        if not skill:
            return None, f"Skill '{skill_name}' not found."

        skill_dir = Path(skill.metadata.source_dir).resolve()
        target_path = (skill_dir / resource_rel_path).resolve()

        # Path traversal guard
        try:
            target_path.relative_to(skill_dir)
        except ValueError:
            return None, f"Security violation: path traversal detected in resource path '{resource_rel_path}'."

        if not target_path.exists() or not target_path.is_file():
            return None, f"SKILL_RESOURCE_NOT_FOUND: resource '{resource_rel_path}' does not exist in skill '{skill_name}'."

        # Binary file check
        try:
            raw_bytes = target_path.read_bytes()
            if b"\x00" in raw_bytes[:1024]:
                return None, f"SKILL_RESOURCE_BINARY: resource '{resource_rel_path}' appears to be a binary file."
            content = raw_bytes.decode("utf-8", errors="replace")
            skill.resources[resource_rel_path] = content
            return content, None
        except Exception as exc:
            return None, f"Error reading skill resource '{resource_rel_path}': {exc}"

    def check_freshness(self) -> Tuple[bool, List[str]]:
        """Check if any skill files or metadata on disk have changed."""
        dirs = self.discover_skills_dirs()
        if not dirs and not self._metadata_index:
            return False, []

        changed_skills = []
        for meta in list(self._metadata_index.values()):
            p = Path(meta.skill_file)
            if not p.exists():
                changed_skills.append(meta.name)
                continue
            try:
                stat = p.stat()
                if stat.st_mtime_ns != meta.mtime_ns:
                    changed_skills.append(meta.name)
                    self._body_cache.pop(meta.name, None)
            except Exception:
                pass

        if changed_skills:
            self.index_skills(force_reload=True)
            return True, changed_skills

        return False, []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_skill_metadata(self, skill_dir: Path, skill_file: Path) -> Optional[SkillMetadata]:
        """Extract YAML frontmatter without loading the body."""
        try:
            raw_bytes = skill_file.read_bytes()
            content = raw_bytes.decode("utf-8", errors="replace")
            stat = skill_file.stat()
            sha256 = hashlib.sha256(raw_bytes).hexdigest()

            if not content.startswith("---"):
                name = skill_dir.name
                return SkillMetadata(
                    name=name,
                    description=f"Skill {name}",
                    source_dir=str(skill_dir),
                    skill_file=str(skill_file),
                    sha256_hash=sha256,
                    mtime_ns=stat.st_mtime_ns,
                )

            parts = content.split("---", 2)
            if len(parts) < 3:
                return None

            fm_raw = parts[1]
            data = yaml.safe_load(fm_raw) or {}

            name = data.get("name", skill_dir.name)
            description = data.get("description", "")
            triggers = data.get("triggers", [])
            priority = int(data.get("priority", 1))
            allowed_tools = data.get("allowed-tools", data.get("allowed_tools", []))
            disable_model_invocation = bool(data.get("disable-model-invocation", data.get("disable_model_invocation", False)))
            context_fork = bool(data.get("context", "") == "fork")

            return SkillMetadata(
                name=name,
                description=description,
                triggers=triggers,
                priority=priority,
                allowed_tools=allowed_tools,
                disable_model_invocation=disable_model_invocation,
                context_fork=context_fork,
                source_dir=str(skill_dir),
                skill_file=str(skill_file),
                sha256_hash=sha256,
                mtime_ns=stat.st_mtime_ns,
            )
        except Exception as exc:
            logger.warning(f"SkillEngine: failed to parse metadata in '{skill_file}': {exc}")
            return None
