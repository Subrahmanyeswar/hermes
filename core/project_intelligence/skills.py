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
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml
from loguru import logger

from core.project_intelligence.models import Skill, SkillMetadata, SkillRoutingDecision


class SkillEngine:
    """
    Manages discovery, metadata indexing, intelligent intent/workspace routing,
    on-demand body loading, and safe resource resolution for Agent Skills.
    """

    MAX_RESOURCE_DEPTH = 2

    def __init__(
        self,
        workspace_root: Optional[Path | str] = None,
        canonical_skills_root: Optional[Path | str] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self.canonical_skills_root = Path(canonical_skills_root).resolve() if canonical_skills_root else None

        self._metadata_index: Dict[str, SkillMetadata] = {}
        self._body_cache: Dict[str, Skill] = {}
        self._parse_warnings: List[str] = []

    @property
    def canonical_root(self) -> Path:
        """Return the authoritative resolved canonical skills root path."""
        if self.canonical_skills_root and self.canonical_skills_root.is_dir():
            return self.canonical_skills_root
        if (self.workspace_root / "skills").is_dir():
            return (self.workspace_root / "skills").resolve()
        repo_skills = (Path(__file__).resolve().parents[2] / "skills").resolve()
        if repo_skills.is_dir():
            return repo_skills
        return (self.workspace_root / "skills").resolve()

    def discover_skills_dirs(self) -> List[Path]:
        """
        Locate skills directories in workspace and canonical repository root.
        Order of precedence:
        1. Workspace custom overrides (.hermes/skills)
        2. Workspace-local skills (skills)
        3. Canonical repository skills (canonical_skills_root)
        """
        candidates = [
            self.workspace_root / ".hermes" / "skills",
            self.workspace_root / "skills",
        ]
        if self.canonical_skills_root:
            candidates.append(self.canonical_skills_root)

        seen: Set[Path] = set()
        dirs: List[Path] = []
        for c in candidates:
            if c and c.exists() and c.is_dir():
                resolved = c.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    dirs.append(resolved)
        return dirs

    def index_skills(self, force_reload: bool = False) -> Dict[str, SkillMetadata]:
        """
        Level 1: Index skill metadata (name, description, triggers, allowed_tools)
        without loading full SKILL.md bodies or resources.
        """
        if self._metadata_index and not force_reload:
            return self._metadata_index

        dirs = self.discover_skills_dirs()
        if not dirs:
            self._metadata_index = {}
            return {}

        index: Dict[str, SkillMetadata] = {}
        self._parse_warnings.clear()

        for s_dir in dirs:
            try:
                for entry in sorted(s_dir.iterdir()):
                    if entry.is_dir():
                        skill_file = entry / "SKILL.md"
                        if not skill_file.exists():
                            # Check lowercase or variant
                            variants = list(entry.glob("[sS][kK][iI][lL][lL].[mM][dD]"))
                            if variants:
                                skill_file = variants[0]

                        if skill_file.exists():
                            meta = self._parse_skill_metadata(entry, skill_file)
                            if meta:
                                if meta.name in index:
                                    # Deterministic deduplication: higher priority or first discovered wins
                                    existing = index[meta.name]
                                    if meta.priority > existing.priority:
                                        index[meta.name] = meta
                                        logger.info(
                                            f"SkillEngine: duplicate skill '{meta.name}' overridden by higher priority in '{entry}'"
                                        )
                                    else:
                                        logger.debug(
                                            f"SkillEngine: duplicate skill '{meta.name}' in '{entry}' ignored in favor of '{existing.source_dir}'"
                                        )
                                else:
                                    index[meta.name] = meta
                            else:
                                self._parse_warnings.append(f"Failed to parse metadata in '{skill_file}'")
            except Exception as exc:
                logger.error(f"SkillEngine: error scanning '{s_dir}': {exc}")
                self._parse_warnings.append(f"Error scanning '{s_dir}': {exc}")

        self._metadata_index = index
        return index

    def route_skills(
        self,
        task_text: str = "",
        workspace_signals: Optional[Dict[str, Any]] = None,
        max_candidates: int = 3,
        task_description: Optional[str] = None,
    ) -> SkillRoutingDecision:
        """
        Intelligent routing combining user task intent and bounded workspace signals.
        Returns a SkillRoutingDecision with selected skills, scores, reasons, and rejected skills.
        Level 1 only: bodies remain strictly unloaded.
        """
        if task_description and not task_text:
            task_text = task_description

        if not self._metadata_index:
            self.index_skills()

        if not task_text or not task_text.strip():
            return SkillRoutingDecision(
                task_text=task_text,
                selected_skills=[],
                selected_skill_metadata=[],
                candidate_scores={},
                rejection_reasons={"fallback": "Empty task text provided"},
                decision_rationale="No skill met the relevance threshold (empty task)",
                is_fallback=True,
                signals_used=workspace_signals or {},
            )

        task_lower = task_text.lower()
        task_words = set(re.findall(r"\w+", task_lower))
        stopwords = {"the", "a", "an", "is", "in", "to", "and", "or", "of", "for", "with", "at", "by", "on", "my", "this"}
        keywords = {w for w in task_words if len(w) > 2 and w not in stopwords}

        ws_signals = workspace_signals or {}
        ws_files = [f.lower() for f in ws_signals.get("files", [])]
        ws_framework = str(ws_signals.get("framework", "")).lower()
        ws_errors = str(ws_signals.get("errors", "")).lower()

        scores: Dict[str, float] = {}
        reasons: Dict[str, str] = {}
        rejected: List[Tuple[str, str]] = []

        # Domain intent detectors using word boundaries
        def _has_keyword(words: List[str]) -> bool:
            return any(bool(re.search(rf"\b{re.escape(w)}\b", task_lower)) for w in words)

        has_vanilla_intent = _has_keyword(["vanilla", "vanilla-web", "html", "css", "javascript", "website", "webpage"])
        has_react_intent = _has_keyword(["react", "jsx", "tsx", "nextjs"])
        has_debug_intent = _has_keyword(["debug", "error", "traceback", "fix", "bug", "crash", "broken", "failing"])
        has_db_intent = _has_keyword(["database", "schema", "sqlite", "postgres", "sql", "relational", "persist", "tables", "orm", "models"])
        has_api_intent = _has_keyword(["api", "endpoints", "rest", "flask", "backend", "crud", "fastapi"])
        has_fastapi_intent = _has_keyword(["fastapi", "asgi", "uvicorn", "pydantic", "starlette"])
        has_flask_intent = _has_keyword(["flask", "werkzeug", "blueprints", "flask_restful"])
        has_arch_intent = _has_keyword(["architecture", "c4", "system design", "adr", "architectural decision", "decomposition", "module boundaries", "subsystem boundaries", "architectural pattern", "software architecture"])
        has_context_intent = _has_keyword(["project context", "hermes.md", "agents.md", "system instructions", "agent instructions", "repository instructions", "rules hierarchy", "maintain context"])
        has_doc_intent = _has_keyword(["docstring", "docstrings", "documentation", "docs", "readme", "jsdoc", "document code"])
        has_review_intent = _has_keyword(["review", "audit", "correctness", "code-review", "pr"])
        has_test_intent = _has_keyword(["test", "pytest", "unit test", "tests"])
        has_powershell_intent = _has_keyword(["powershell", "pwsh", "ps1", "windows script", "powershell script", "powershell automation"])
        has_bash_intent = _has_keyword(["bash", "shell script", "sh script", "linux script"])
        has_security_intent = _has_keyword(["security", "vulnerability", "injection", "traversal", "auth bypass", "bypass", "exploit", "cve", "owasp", "xss", "csrf", "sanitise", "sanitize", "secure"])
        has_git_intent = _has_keyword(["git", "merge conflict", "merge", "commit", "branch", "rebase", "pull request", "cherry-pick"])

        # Conceptual / purely definitional question detector (prevents false positive activations on theoretical queries)
        is_conceptual_inquiry = bool(re.search(
            r"^(what\s+(is|are|does)\b|how\s+(does|do|can|is|are)\b|why\s+(is|are|do|does)\b|explain\b|describe\b|in\s+theory\b)",
            task_lower.strip()
        ))
        has_concrete_action = bool(re.search(
            r"\b(fix\b|debug\s+(this|my|the|an?|code|test|issue|bug|error|traceback)|audit\s+(this|my|the|an?|code|endpoint|system|app)|perform\s+.*audit|conduct\s+.*audit|run\s+.*audit|review\s+(this|my|the\s+pr|the\s+diff|the\s+code)|write\s+tests?|generate\s+tests?|resolve\s+(conflict|issue|merge)|merge\s+(this|branch|into|pr)|write\s+a\s+.*script|create\b|implement\b|build\b|refactor\b|benchmark\b)",
            task_lower
        ))
        is_pure_conceptual = is_conceptual_inquiry and not has_concrete_action and not ws_files

        # Explicit technology requirements
        explicitly_vanilla = bool(re.search(r"\bvanilla\b", task_lower))

        for name, meta in self._metadata_index.items():
            if meta.disable_model_invocation:
                rejected.append((name, "Model invocation disabled in metadata"))
                continue

            if is_pure_conceptual:
                # Conceptual / purely definitional inquiries avoid false-positive activation of operational skills
                rejected.append((name, "Purely conceptual inquiry without codebase action"))
                continue

            score = 0.0
            score_reasons = []

            # 1. Trigger phrase & keyword matching (high weight)
            for trig in meta.triggers:
                trig_l = trig.lower().strip()
                if not trig_l:
                    continue
                if re.search(rf"\b{re.escape(trig_l)}\b", task_lower):
                    score += 0.50
                    score_reasons.append(f"matched trigger '{trig}'")
                    break
                else:
                    trig_words = set(re.findall(r"\w+", trig_l))
                    if trig_words and trig_words.issubset(keywords):
                        score += 0.35
                        score_reasons.append(f"matched trigger words '{trig}'")
                        break

            # 2. Skill Name match
            if re.search(rf"\b{re.escape(name.lower())}\b", task_lower) or re.search(rf"\b{re.escape(name.replace('-', ' ').lower())}\b", task_lower):
                score += 0.50
                score_reasons.append(f"name match '{name}'")

            # 3. Description keyword overlap
            desc_words = set(re.findall(r"\w+", meta.description.lower()))
            overlap = len(keywords.intersection(desc_words))
            if overlap:
                overlap_score = min(0.30, overlap * 0.05)
                score += overlap_score
                score_reasons.append(f"description overlap ({overlap} words)")

            # 4. Priority boost
            score += meta.priority * 0.02

            # 5. Workspace signal integration
            if name == "debugging":
                if has_debug_intent or ws_errors or any("traceback" in f for f in ws_files):
                    score += 0.60
                    score_reasons.append("debugging intent / error traceback detected")
                elif any(f.endswith(".py") for f in ws_files) and any(w in task_lower for w in ["fail", "issue", "problem"]):
                    score += 0.40
                    score_reasons.append("Python workspace with reported issue")

            elif name == "vanilla-web":
                if has_vanilla_intent:
                    score += 0.45
                    score_reasons.append("vanilla website intent detected")
                if any(f.endswith((".html", ".css", ".js")) for f in ws_files) or "html" in ws_framework or "vanilla" in ws_framework:
                    score += 0.35
                    score_reasons.append("workspace contains HTML/CSS/JS files")
                if explicitly_vanilla:
                    score += 0.40
                    score_reasons.append("explicit vanilla web requirement")

            elif name == "react-frontend":
                has_html_files = any(f.endswith(".html") for f in ws_files)
                has_react_files = any(f.endswith((".jsx", ".tsx")) for f in ws_files) or "react" in ws_framework
                if explicitly_vanilla or (has_html_files and not has_react_files):
                    # Explicit conflict resolution: workspace is vanilla HTML without react
                    score = 0.0
                    rejected.append((name, "Workspace contains vanilla HTML/JS without React"))
                    continue
                if has_react_intent:
                    score += 0.50
                    score_reasons.append("React frontend intent")
                if has_react_files:
                    score += 0.35
                    score_reasons.append("workspace contains React/JSX files")

            elif name == "database-design":
                if has_db_intent:
                    score += 0.50
                    score_reasons.append("database / schema modeling intent")
                if any(f.endswith(".sql") or "migration" in f or "model" in f for f in ws_files):
                    score += 0.35
                    score_reasons.append("workspace contains SQL/database schema files")

            elif name == "flask-rest-api":
                is_ui_component_api = bool(re.search(r"\b(component|react|tabs|menu|props|ui)\s+api\b", task_lower))
                if has_fastapi_intent and not has_flask_intent:
                    score = min(score, 0.15)
                    rejected.append((name, "FastAPI specified; suppressing Flask REST API"))
                else:
                    if (has_api_intent or has_flask_intent) and not is_ui_component_api:
                        score += 0.45
                        score_reasons.append("REST API intent")
                    if any("api" in f or "app.py" in f for f in ws_files) or "flask" in ws_framework:
                        score += 0.30
                        score_reasons.append("workspace contains API route files")

            elif name == "fastapi-backend":
                is_ui_component_api = bool(re.search(r"\b(component|react|tabs|menu|props|ui)\s+api\b", task_lower))
                if has_flask_intent and not has_fastapi_intent:
                    score = min(score, 0.15)
                    rejected.append((name, "Flask specified; suppressing FastAPI backend"))
                elif has_fastapi_intent:
                    score += 0.55
                    score_reasons.append("FastAPI / ASGI backend intent")
                elif has_api_intent and not is_ui_component_api and not has_flask_intent:
                    if "fastapi" in ws_framework or any("fastapi" in f or "main.py" in f for f in ws_files):
                        score += 0.45
                        score_reasons.append("FastAPI workspace signal with API intent")

            elif name == "react-best-practices":
                has_perf_intent = _has_keyword(["performance", "re-render", "waterfall", "bundle", "memo", "usememo", "usecallback", "suspense", "best practices", "data fetching"])
                if has_react_intent and has_perf_intent:
                    score += 0.45
                    score_reasons.append("React performance and best-practices intent")

            elif name == "react-composition-patterns":
                has_comp_intent = _has_keyword(["composition", "compound", "compound component", "slots", "tabs", "menu", "accordion", "controlled", "uncontrolled", "reusable"])
                if has_react_intent and has_comp_intent:
                    score += 0.45
                    score_reasons.append("React component composition intent")

            elif name == "design-system":
                has_ds_intent = _has_keyword(["design system", "design tokens", "design token", "tokens", "token", "token extraction", "color tokens", "typography scale", "design.md"])
                if has_ds_intent:
                    score += 0.50
                    score_reasons.append("design system / token architecture intent")

            elif name == "web-design-guidelines":
                has_audit_intent = _has_keyword(["audit", "guidelines", "usability", "accessibility", "a11y", "wcag", "keyboard navigation", "heuristics"])
                if has_security_intent and not any(w in task_lower for w in ["accessibility", "a11y", "wcag", "usability", "keyboard", "frontend", "ui", "design"]):
                    score = min(score, 0.15)
                    rejected.append((name, "Security audit intent; suppressing web design guidelines"))
                elif has_audit_intent:
                    score += 0.50
                    score_reasons.append("usability / accessibility guidelines intent")

            elif name == "security-audit":
                if has_security_intent:
                    score += 0.60
                    score_reasons.append("security / vulnerability audit intent")
                if any("security" in f or "auth" in f or "audit" in f for f in ws_files):
                    score += 0.25
                    score_reasons.append("workspace contains security/audit files")

            elif name == "git-workflow":
                if has_git_intent:
                    score += 0.55
                    score_reasons.append("Git workflow / version control intent")
                if any(".git" in f or "conflict" in f for f in ws_files):
                    score += 0.25
                    score_reasons.append("workspace contains git/conflict signals")

            elif name == "taste-design":
                has_taste_intent = _has_keyword(["taste", "editorial", "distinctive", "creative direction", "brand mood", "aesthetic direction", "design brief", "art direction", "brief"])
                if has_taste_intent:
                    score += 0.50
                    score_reasons.append("taste / creative design direction intent")

            elif name == "design-engineering":
                has_de_intent = _has_keyword(["design engineering", "polished frontend", "ui engineering", "product design implementation", "frontend design", "visual polish", "craft", "polish"])
                has_taste_intent = _has_keyword(["taste", "editorial", "distinctive", "creative direction", "brand mood", "aesthetic direction", "design brief", "art direction"])
                if has_de_intent or (has_taste_intent and any(w in task_lower for w in ["build", "implement", "create", "portfolio", "interface"])):
                    score += 0.45
                    score_reasons.append("design engineering implementation intent")

            elif name == "shadcn-ui":
                has_shadcn_intent = _has_keyword(["shadcn", "shadcn/ui", "shadcn ui", "shadcn-ui", "radix", "radix ui"])
                has_ui_task = any(w in task_lower for w in ["component", "dropdown", "dialog", "modal", "button", "menu", "form", "sheet", "card", "select", "ui", "popover", "tooltip", "tabs"])
                has_shadcn_ws = "shadcn" in ws_framework or any("components/ui" in f or "shadcn" in f for f in ws_files)
                if has_shadcn_intent:
                    score += 0.60
                    score_reasons.append("shadcn/ui intent detected")
                elif has_shadcn_ws and has_ui_task:
                    score += 0.45
                    score_reasons.append("shadcn/ui workspace signal with UI component task")
                elif not has_shadcn_ws:
                    score = min(score, 0.15)

            elif name == "code-review":
                if has_review_intent:
                    score += 0.50
                    score_reasons.append("code review intent")

            elif name == "pytest-generation":
                if (has_vanilla_intent or any(f.endswith((".html", ".css", ".js")) for f in ws_files)) and not any(w in task_lower for w in ["pytest", "python", "backend test"]):
                    score = min(score, 0.15)
                    rejected.append((name, "Vanilla web project without Python; suppressing pytest-generation"))
                else:
                    if has_test_intent:
                        score += 0.50
                        score_reasons.append("testing / pytest intent")
                    if any("test" in f or "pytest" in f for f in ws_files):
                        score += 0.25
                        score_reasons.append("workspace contains test files")

            elif name == "software-architecture":
                if has_arch_intent:
                    score += 0.55
                    score_reasons.append("software architecture / C4 / ADR intent detected")
                if any("adr" in f or "architecture" in f for f in ws_files):
                    score += 0.25
                    score_reasons.append("workspace contains architecture documentation")

            elif name == "project-context":
                if has_context_intent:
                    score += 0.55
                    score_reasons.append("project context / repository instruction management intent")
                if any("hermes.md" in f or "agents.md" in f for f in ws_files) and any(w in task_lower for w in ["update", "document", "sync", "align", "context"]):
                    score += 0.35
                    score_reasons.append("workspace context file alignment signal")

            elif name == "auto-docs":
                if has_doc_intent and not has_context_intent:
                    score += 0.50
                    score_reasons.append("code documentation / docstring intent detected")

            elif name == "screenshot-to-code":
                has_vision_intent = _has_keyword(["screenshot", "mockup", "figma", "wireframe", "image to code", "design to code"])
                if has_vision_intent:
                    score += 0.55
                    score_reasons.append("visual reference / design-to-code intent detected")
                elif not any(w in task_lower for w in ["screenshot", "mockup", "figma", "wireframe"]):
                    # If prompt contains no visual-reference terms, penalize to prevent false-positive matching
                    score = min(score, 0.15)

            elif name == "powershell-scripting":
                if has_bash_intent and not has_powershell_intent:
                    score = min(score, 0.15)
                    rejected.append((name, "Bash specified; suppressing PowerShell scripting"))
                elif has_powershell_intent:
                    score += 0.55
                    score_reasons.append("PowerShell / Windows scripting intent detected")
                if any(f.endswith(".ps1") for f in ws_files) or "powershell" in ws_framework:
                    score += 0.30
                    score_reasons.append("workspace contains PowerShell scripts")

            elif name == "bash-scripting":
                if has_powershell_intent and not has_bash_intent:
                    score = min(score, 0.15)
                    rejected.append((name, "PowerShell specified; suppressing Bash scripting"))
                elif has_bash_intent:
                    score += 0.55
                    score_reasons.append("Bash / Linux shell scripting intent detected")
                if any(f.endswith(".sh") for f in ws_files) or "bash" in ws_framework:
                    score += 0.30
                    score_reasons.append("workspace contains shell script files")

            scores[name] = round(score, 3)
            reasons[name] = "; ".join(score_reasons) if score_reasons else "low relevance"

        # Filter by threshold (min 0.30 score)
        qualifying = [(name, scores[name]) for name, sc in scores.items() if sc >= 0.30]

        if not qualifying:
            # Legitimate no-skill fallback
            return SkillRoutingDecision(
                task_text=task_text,
                selected_skills=[],
                selected_skill_metadata=[],
                candidate_scores=scores,
                rejection_reasons=dict(rejected),
                decision_rationale="No skill met the relevance threshold (0.30)",
                signals_used=ws_signals,
                is_fallback=True,
            )

        # Sort qualifying candidates by score descending
        qualifying.sort(key=lambda x: x[1], reverse=True)

        selected_names = [s_name for s_name, _ in qualifying[:max_candidates]]

        rejection_dict = dict(rejected)
        for s_name, _ in qualifying[max_candidates:]:
            rejection_dict[s_name] = "Exceeded max candidates"

        # Domain-critical skill preservation (Part 8)
        # For vanilla web missions, vanilla-web is domain-critical and must not be pruned out
        if (has_vanilla_intent or any(f.endswith((".html", ".css", ".js")) for f in ws_files)) and not has_react_intent:
            if any(name == "vanilla-web" for name, _ in qualifying) and "vanilla-web" not in selected_names:
                if selected_names:
                    displaced = selected_names.pop()
                    rejection_dict[displaced] = "Exceeded max candidates (displaced by domain-critical vanilla-web)"
                selected_names.append("vanilla-web")
                if "vanilla-web" in rejection_dict:
                    del rejection_dict["vanilla-web"]

        # For react missions, react-frontend is domain-critical
        if has_react_intent and any(name == "react-frontend" for name, _ in qualifying) and "react-frontend" not in selected_names:
            if selected_names:
                displaced = selected_names.pop()
                rejection_dict[displaced] = "Exceeded max candidates (displaced by domain-critical react-frontend)"
            selected_names.append("react-frontend")
            if "react-frontend" in rejection_dict:
                del rejection_dict["react-frontend"]

        selected_metas = [self._metadata_index[s_name] for s_name in selected_names]

        rationale = f"Selected {', '.join(selected_names)} based on task intent and workspace signals"

        return SkillRoutingDecision(
            task_text=task_text,
            selected_skills=selected_names,
            selected_skill_metadata=selected_metas,
            candidate_scores=scores,
            rejection_reasons=rejection_dict,
            decision_rationale=rationale,
            signals_used=ws_signals,
            is_fallback=False,
        )

    def match_skills(
        self,
        task_text: str,
        active_tools: Optional[List[str]] = None,
        max_candidates: int = 3,
    ) -> List[SkillMetadata]:
        """
        Backward compatible query wrapper returning selected SkillMetadata.
        """
        decision = self.route_skills(task_text=task_text, max_candidates=max_candidates)
        return decision.selected_skill_metadata

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

    def get_skill_helpers(self, skill_name: str) -> List[Path]:
        """
        Discover executable helper scripts in a skill directory without running them.
        """
        if not self._metadata_index:
            self.index_skills()

        meta = self._metadata_index.get(skill_name)
        if not meta:
            return []
        s_dir = Path(meta.source_dir).resolve()
        helper_dirs = [s_dir / "scripts", s_dir / "helpers"]
        helpers: List[Path] = []
        for hd in helper_dirs:
            if hd.exists() and hd.is_dir():
                for p in hd.rglob("*"):
                    if p.is_file() and p.suffix in (".py", ".sh", ".bash", ".js"):
                        helpers.append(p)
        return helpers

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
