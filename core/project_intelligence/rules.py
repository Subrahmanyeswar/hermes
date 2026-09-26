# core/project_intelligence/rules.py
"""
Path-Scoped Rule Engine for HERMES 2.x Project Intelligence.
Discovers, indexes, matches, and lazily loads path-scoped rules from .hermes/rules/.
Provides deterministic cross-platform glob matching and precedence resolution.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml
from loguru import logger

from core.project_intelligence.models import Rule, RuleMetadata, RuleScopeType


class RuleEngine:
    """
    Manages indexing, path-matching, precedence ordering, and lazy-loading for scoped rules.
    """

    def __init__(self, workspace_root: Optional[Path | str] = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self._metadata_index: Dict[str, RuleMetadata] = {}
        self._body_cache: Dict[str, Rule] = {}

    def discover_rules_dir(self) -> Optional[Path]:
        """Locate rules directory in workspace."""
        candidates = [
            self.workspace_root / ".hermes" / "rules",
            self.workspace_root / ".rules",
        ]
        for c in candidates:
            if c.exists() and c.is_dir():
                return c
        return None

    def index_rules(self, force_reload: bool = False) -> Dict[str, RuleMetadata]:
        """
        Discover and index rule metadata without loading full rule bodies.
        """
        rules_dir = self.discover_rules_dir()
        if not rules_dir:
            self._metadata_index = {}
            return {}

        index: Dict[str, RuleMetadata] = {}
        try:
            for entry in sorted(rules_dir.glob("*.md")):
                meta = self._parse_rule_metadata(entry)
                if meta:
                    index[meta.name] = meta
        except Exception as exc:
            logger.error(f"RuleEngine: error scanning '{rules_dir}': {exc}")

        self._metadata_index = index
        return index

    def match_rules(
        self,
        target_paths: List[str],
        only_enabled: bool = True,
    ) -> List[Rule]:
        """
        Match target file paths against indexed rules and load only applicable rule bodies.
        Returns deduplicated rules sorted by precedence (highest precedence first).
        """
        if not self._metadata_index:
            self.index_rules()

        normalized_paths = [self._normalize_path(p) for p in target_paths]
        matched_rules: Dict[str, Tuple[RuleMetadata, int]] = {}

        for name, meta in self._metadata_index.items():
            if only_enabled and not meta.enabled:
                continue

            # Check if any path pattern matches any target path
            matched = False
            for pat in meta.paths:
                norm_pat = pat.replace("\\", "/").strip()
                for tp in normalized_paths:
                    if self._path_matches(tp, norm_pat):
                        matched = True
                        break
                if matched:
                    break

            if matched:
                precedence_score = self._compute_precedence(meta)
                matched_rules[meta.name] = (meta, precedence_score)

        # Sort by precedence score descending, then by priority descending, then by name
        sorted_matches = sorted(
            matched_rules.values(),
            key=lambda x: (x[1], x[0].priority, x[0].name),
            reverse=True,
        )

        # Load bodies lazily for matched rules only
        results: List[Rule] = []
        for meta, _ in sorted_matches:
            rule_obj = self._load_rule_body(meta)
            if rule_obj:
                results.append(rule_obj)

        return results

    def get_rule_body(self, name: str) -> Optional[Rule]:
        """Explicitly load body for a single rule by name."""
        meta = self._metadata_index.get(name)
        if not meta:
            self.index_rules()
            meta = self._metadata_index.get(name)
        if not meta:
            return None
        return self._load_rule_body(meta)

    def check_freshness(self) -> Tuple[bool, List[str]]:
        """
        Check if any rule on disk has changed or if rules were added/removed.
        Returns: (has_changed, affected_rule_names)
        """
        rules_dir = self.discover_rules_dir()
        if not rules_dir and not self._metadata_index:
            return False, []
        if not rules_dir and self._metadata_index:
            self._metadata_index.clear()
            self._body_cache.clear()
            return True, ["all"]

        assert rules_dir is not None
        current_files = {e.name: e for e in rules_dir.glob("*.md")}
        indexed_names = {Path(m.source_path).name: m for m in self._metadata_index.values()}

        changed_names = []

        # Check for added or removed rule files
        if set(current_files.keys()) != set(indexed_names.keys()):
            self.index_rules(force_reload=True)
            return True, ["index_changed"]

        # Check for modified rule files
        for fname, fpath in current_files.items():
            meta = indexed_names.get(fname)
            if meta:
                try:
                    stat = fpath.stat()
                    if stat.st_mtime_ns != meta.mtime_ns:
                        changed_names.append(meta.name)
                        # Invalidate body cache for this rule
                        self._body_cache.pop(meta.name, None)
                except Exception:
                    pass

        if changed_names:
            self.index_rules(force_reload=True)
            return True, changed_names

        return False, []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _normalize_path(self, path_str: str) -> str:
        """Convert path to workspace-relative forward-slash representation."""
        p = Path(path_str)
        if p.is_absolute():
            try:
                p = p.relative_to(self.workspace_root)
            except ValueError:
                pass
        return str(p).replace("\\", "/").lstrip("./")

    def _path_matches(self, path: str, pattern: str) -> bool:
        """
        Deterministic glob matching supporting '**' recursive wildcards.
        """
        # Exact match
        if path == pattern:
            return True

        # Convert glob pattern to regex
        # Handle '**/' and '/**' properly
        regex_pat = fnmatch.translate(pattern)
        # Python fnmatch.translate translates * to .*, but we want ** to match across slashes and * within directory
        if "**" in pattern:
            pat_parts = pattern.split("**")
            escaped_parts = [re.escape(part).replace(r"\*", r"[^/]*").replace(r"\?", r"[^/]") for part in pat_parts]
            custom_regex = "^" + ".*".join(escaped_parts) + "$"
            if re.match(custom_regex, path, re.IGNORECASE if os.name == "nt" else 0):
                return True

        return bool(re.match(regex_pat, path, re.IGNORECASE if os.name == "nt" else 0))

    def _compute_precedence(self, meta: RuleMetadata) -> int:
        """
        Compute deterministic precedence score based on scope specificity.
        Higher score = more specific = higher precedence.
        """
        scope_scores = {
            RuleScopeType.FILE_SPECIFIC: 500,
            RuleScopeType.SUBSYSTEM: 400,
            RuleScopeType.DIRECTORY: 300,
            RuleScopeType.LANGUAGE: 200,
            RuleScopeType.GENERAL: 100,
        }
        return scope_scores.get(meta.scope_type, 100)

    def _infer_scope_type(self, paths: List[str]) -> RuleScopeType:
        """Infer scope granularity from declared paths."""
        if not paths:
            return RuleScopeType.GENERAL

        for p in paths:
            if not any(c in p for c in ("*", "?", "[")):
                return RuleScopeType.FILE_SPECIFIC
            if p.startswith("**/*."):
                return RuleScopeType.LANGUAGE
            if p.count("/") > 2:
                return RuleScopeType.SUBSYSTEM
            if "/" in p:
                return RuleScopeType.DIRECTORY

        return RuleScopeType.GENERAL

    def _parse_rule_metadata(self, file_path: Path) -> Optional[RuleMetadata]:
        """Extract YAML frontmatter without loading the entire body."""
        try:
            raw_bytes = file_path.read_bytes()
            content = raw_bytes.decode("utf-8", errors="replace")
            stat = file_path.stat()
            sha256 = hashlib.sha256(raw_bytes).hexdigest()

            # Frontmatter check
            if not content.startswith("---"):
                name = file_path.stem
                return RuleMetadata(
                    name=name,
                    description=f"Rule {name}",
                    paths=["**/*"],
                    source_path=str(file_path),
                    sha256_hash=sha256,
                    mtime_ns=stat.st_mtime_ns,
                )

            parts = content.split("---", 2)
            if len(parts) < 3:
                return None

            fm_raw = parts[1]
            data = yaml.safe_load(fm_raw) or {}

            name = data.get("name", file_path.stem)
            description = data.get("description", "")
            paths = data.get("paths", ["**/*"])
            if isinstance(paths, str):
                paths = [paths]
            priority = int(data.get("priority", 100))
            enabled = bool(data.get("enabled", True))
            tags = data.get("tags", [])
            enforcement = data.get("enforcement", "guidance")

            scope_type = self._infer_scope_type(paths)

            return RuleMetadata(
                name=name,
                description=description,
                paths=paths,
                priority=priority,
                scope_type=scope_type,
                enabled=enabled,
                tags=tags,
                source_path=str(file_path),
                sha256_hash=sha256,
                mtime_ns=stat.st_mtime_ns,
                enforcement=enforcement,
            )
        except Exception as exc:
            logger.warning(f"RuleEngine: failed to parse metadata in '{file_path}': {exc}")
            return None

    def _load_rule_body(self, meta: RuleMetadata) -> Optional[Rule]:
        """Load and cache the markdown body for a rule."""
        if meta.name in self._body_cache:
            return self._body_cache[meta.name]

        p = Path(meta.source_path)
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

            rule_obj = Rule(metadata=meta, body=body)
            self._body_cache[meta.name] = rule_obj
            return rule_obj
        except Exception as exc:
            logger.error(f"RuleEngine: error loading body for '{meta.name}': {exc}")
            return None
