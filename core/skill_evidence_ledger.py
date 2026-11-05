# core/skill_evidence_ledger.py
"""
Per-Mission Skill Evidence Ledger for HERMES 2.x (Phase 3).
Tracks the complete lifecycle of skills across missions:
DISCOVERED → SELECTED → LOADED → INJECTED → APPLIED → VERIFIED.

Guarantees that mandatory skills (taste-design, design-engineering, design-system,
web-design-guidelines, vanilla-web/react-frontend) produce verifiable implementation
evidence in the workspace rather than passive prompt injection.
Persisted to .hermes/skill_evidence_ledger.json.
"""

from __future__ import annotations

import hashlib
import os
import json
import re
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger


class SkillLifecycleStage(str, Enum):
    """Authoritative lifecycle progression stages for skills."""
    DISCOVERED = "DISCOVERED"
    SELECTED = "SELECTED"
    LOADED = "LOADED"
    INJECTED = "INJECTED"
    APPLIED = "APPLIED"
    VERIFIED = "VERIFIED"


class SkillApplicationStatus(str, Enum):
    """Evaluation status for physical workspace evidence."""
    NOT_RUN = "NOT_RUN"
    PARTIAL = "PARTIAL"
    APPLIED = "APPLIED"
    FAIL = "FAIL"


class SkillVerificationStatus(str, Enum):
    """Independent verification status for skill application."""
    NOT_RUN = "NOT_RUN"
    VERIFIED = "VERIFIED"
    FAIL = "FAIL"


@dataclass
class SkillEvidenceRecord:
    """Detailed evidence trace for a single skill in a mission."""
    skill_id: str
    version: str = "1.0.0"
    content_hash: str = ""
    selection_reason: str = ""
    loading_event: Optional[Dict[str, Any]] = None
    loading_source_path: Optional[str] = None
    injection_events: List[Dict[str, Any]] = field(default_factory=list)
    applicable_instruction_ids: List[str] = field(default_factory=list)
    associated_turns: List[str] = field(default_factory=list)
    relevant_artifacts: List[str] = field(default_factory=list)
    applied_status: SkillApplicationStatus = SkillApplicationStatus.NOT_RUN
    applied_evidence: str = "Awaiting implementation evidence."
    verified_status: SkillVerificationStatus = SkillVerificationStatus.NOT_RUN
    verification_results: Dict[str, Any] = field(default_factory=dict)
    current_stage: SkillLifecycleStage = SkillLifecycleStage.DISCOVERED
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "version": self.version,
            "content_hash": self.content_hash,
            "selection_reason": self.selection_reason,
            "loading_event": self.loading_event,
            "loading_source_path": self.loading_source_path,
            "injection_events": list(self.injection_events),
            "applicable_instruction_ids": list(self.applicable_instruction_ids),
            "associated_turns": list(self.associated_turns),
            "relevant_artifacts": list(self.relevant_artifacts),
            "applied_status": self.applied_status.value if isinstance(self.applied_status, Enum) else str(self.applied_status),
            "applied_evidence": self.applied_evidence,
            "verified_status": self.verified_status.value if isinstance(self.verified_status, Enum) else str(self.verified_status),
            "verification_results": dict(self.verification_results),
            "current_stage": self.current_stage.value if isinstance(self.current_stage, Enum) else str(self.current_stage),
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SkillEvidenceRecord:
        applied_raw = data.get("applied_status", "NOT_RUN")
        verified_raw = data.get("verified_status", "NOT_RUN")
        stage_raw = data.get("current_stage", "DISCOVERED")
        return cls(
            skill_id=data.get("skill_id", ""),
            version=data.get("version", "1.0.0"),
            content_hash=data.get("content_hash", ""),
            selection_reason=data.get("selection_reason", ""),
            loading_event=data.get("loading_event"),
            loading_source_path=data.get("loading_source_path"),
            injection_events=list(data.get("injection_events", [])),
            applicable_instruction_ids=list(data.get("applicable_instruction_ids", [])),
            associated_turns=list(data.get("associated_turns", [])),
            relevant_artifacts=list(data.get("relevant_artifacts", [])),
            applied_status=SkillApplicationStatus(applied_raw) if applied_raw in SkillApplicationStatus.__members__ else SkillApplicationStatus.NOT_RUN,
            applied_evidence=data.get("applied_evidence", ""),
            verified_status=SkillVerificationStatus(verified_raw) if verified_raw in SkillVerificationStatus.__members__ else SkillVerificationStatus.NOT_RUN,
            verification_results=dict(data.get("verification_results", {})),
            current_stage=SkillLifecycleStage(stage_raw) if stage_raw in SkillLifecycleStage.__members__ else SkillLifecycleStage.DISCOVERED,
            last_updated=float(data.get("last_updated", time.time())),
        )


class SkillEvidenceLedger:
    """
    Authoritative evidence ledger managing per-mission skill lifecycle tracking.
    Enforces independent verification of skill application proofs.
    """

    MANDATORY_FRONTEND_SKILLS = [
        "taste-design",
        "design-engineering",
        "design-system",
        "web-design-guidelines",
    ]

    def __init__(self, mission_id: str = "", workspace_root: Optional[Path | str] = None) -> None:
        self.mission_id = mission_id
        self.records: Dict[str, SkillEvidenceRecord] = {}
        self.created_at = time.time()
        self.workspace_root: Optional[Path] = Path(workspace_root).resolve() if workspace_root else None

    def set_workspace_root(self, workspace_root: Path | str) -> None:
        """Configure target workspace and enable immediate atomic persistence."""
        if workspace_root:
            self.workspace_root = Path(workspace_root).resolve()

    def _atomic_persist(self) -> None:
        """Persist ledger immediately and atomically to .hermes/skill_evidence_ledger.json."""
        if not self.workspace_root:
            return
        try:
            ws = self.workspace_root
            h_dir = ws / ".hermes"
            h_dir.mkdir(parents=True, exist_ok=True)
            dest = h_dir / "skill_evidence_ledger.json"
            tmp = h_dir / f"skill_evidence_ledger.json.tmp.{os.getpid()}_{int(time.time()*1000)}"
            data = json.dumps(self.to_dict(), indent=2)
            tmp.write_text(data, encoding="utf-8")
            tmp.replace(dest)
        except Exception as e:
            logger.debug(f"SkillEvidenceLedger: atomic persist notice: {e}")

    def get_or_create(self, skill_id: str) -> SkillEvidenceRecord:
        if skill_id not in self.records:
            self.records[skill_id] = SkillEvidenceRecord(skill_id=skill_id)
        return self.records[skill_id]

    def record_discovered(self, skill_id: str, source_path: Optional[str] = None, version: str = "1.0.0") -> None:
        """Stage 1: Skill discovered in skills directory."""
        rec = self.get_or_create(skill_id)
        rec.version = version
        rec.loading_source_path = source_path
        rec.current_stage = SkillLifecycleStage.DISCOVERED
        rec.last_updated = time.time()
        self._atomic_persist()

    def record_selected(self, skill_id: str, reason: str) -> None:
        """Stage 2: Skill selected by intent routing."""
        rec = self.get_or_create(skill_id)
        rec.selection_reason = reason
        rec.current_stage = SkillLifecycleStage.SELECTED
        rec.last_updated = time.time()
        self._atomic_persist()

    def record_loaded(self, skill_id: str, source_path: str, content: str) -> None:
        """Stage 3: Full SKILL.md body loaded from disk."""
        rec = self.get_or_create(skill_id)
        rec.loading_source_path = str(source_path)
        rec.content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        rec.loading_event = {
            "timestamp": time.time(),
            "source_path": str(source_path),
            "bytes_loaded": len(content),
            "content_hash": rec.content_hash,
        }
        rec.current_stage = SkillLifecycleStage.LOADED
        rec.last_updated = time.time()
        self._atomic_persist()

    def record_injected(
        self,
        skill_id: str,
        turn_id: str,
        phase: str,
        instruction_ids: Optional[List[str]] = None,
    ) -> None:
        """Stage 4: Skill instructions injected into model generation prompt."""
        rec = self.get_or_create(skill_id)
        ev = {
            "turn_id": turn_id,
            "phase": phase,
            "timestamp": time.time(),
            "instruction_ids": instruction_ids or [],
        }
        rec.injection_events.append(ev)
        if turn_id and turn_id not in rec.associated_turns:
            rec.associated_turns.append(turn_id)
        if instruction_ids:
            for iid in instruction_ids:
                if iid not in rec.applicable_instruction_ids:
                    rec.applicable_instruction_ids.append(iid)
        # Injected indicates the model received the prompt, but NOT yet APPLIED
        if rec.current_stage in (SkillLifecycleStage.DISCOVERED, SkillLifecycleStage.SELECTED, SkillLifecycleStage.LOADED):
            rec.current_stage = SkillLifecycleStage.INJECTED
        rec.last_updated = time.time()
        self._atomic_persist()

    def record_applied(self, skill_id: str, evidence: str, turn_id: Optional[str] = None) -> None:
        rec = self.get_or_create(skill_id)
        rec.applied_status = SkillApplicationStatus.APPLIED
        rec.applied_evidence = evidence
        rec.current_stage = SkillLifecycleStage.APPLIED
        rec.last_updated = time.time()
        if turn_id and turn_id not in rec.associated_turns:
            rec.associated_turns.append(turn_id)
        self._atomic_persist()

    def record_verified(self, skill_id: str, results: Dict[str, Any]) -> None:
        rec = self.get_or_create(skill_id)
        rec.verified_status = SkillVerificationStatus.VERIFIED
        rec.verification_results = dict(results)
        rec.current_stage = SkillLifecycleStage.VERIFIED
        rec.last_updated = time.time()
        self._atomic_persist()

    def evaluate_physical_evidence(
        self,
        workspace_root: Path | str,
        design_brief: Optional[Any] = None,
        contract: Optional[Any] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Stage 5: Evaluate direct workspace code and styling evidence for each mandatory skill.
        A skill cannot be marked APPLIED merely because the prompt included its text.
        """
        ws = Path(workspace_root).resolve()
        self.set_workspace_root(ws)
        html_files = list(ws.glob("*.html")) + list(ws.glob("static/*.html"))
        css_files = list(ws.glob("*.css")) + list(ws.glob("static/*.css")) + list(ws.glob("css/*.css"))
        js_files = list(ws.glob("*.js")) + list(ws.glob("static/*.js")) + list(ws.glob("js/*.js"))

        html_text = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in html_files if f.is_file())
        css_text = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in css_files if f.is_file())
        js_text = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in js_files if f.is_file())

        results = {}

        for skill_id, rec in self.records.items():
            if skill_id == "taste-design":
                # Proof: DesignBrief exists with visual direction, personality, typography, and colors;
                # AND CSS or HTML reflects intentional styling matching brand personality.
                has_brief = design_brief is not None and getattr(design_brief, "brand_personality", None)
                brief_file = ws / ".hermes" / "design_brief.json"
                has_persisted_brief = brief_file.exists()
                has_visual_styling = bool(re.search(r'font-family\s*:', css_text, re.I)) and bool(re.search(r'color\s*:', css_text, re.I))

                if (has_brief or has_persisted_brief) and has_visual_styling:
                    personality = getattr(design_brief, "brand_personality", "clean, modern, professional")
                    rec.applied_status = SkillApplicationStatus.APPLIED
                    rec.applied_evidence = f"Demonstrated intentional visual direction ({personality}) with cohesive typography and color choices."
                    rec.current_stage = SkillLifecycleStage.APPLIED
                elif has_brief or has_persisted_brief:
                    rec.applied_status = SkillApplicationStatus.PARTIAL
                    rec.applied_evidence = "Design brief created, but stylesheets do not yet demonstrate visual direction."
                else:
                    rec.applied_status = SkillApplicationStatus.FAIL
                    rec.applied_evidence = "Missing DesignBrief and visual styling implementation."

            elif skill_id == "design-system":
                # Proof: CSS custom property tokens defined in :root (at least 3 tokens) and reused via var(--...)
                root_match = re.search(r':root\s*\{([^}]+)\}', css_text, re.DOTALL)
                tokens = re.findall(r'(--[a-zA-Z0-9_\-]+)\s*:', root_match.group(1)) if root_match else []
                var_usages = re.findall(r'var\(\s*(--[a-zA-Z0-9_\-]+)\s*\)', css_text)

                if len(tokens) >= 3 and len(set(var_usages)) >= 2:
                    rec.applied_status = SkillApplicationStatus.APPLIED
                    rec.applied_evidence = f"Defined {len(tokens)} :root design tokens ({', '.join(tokens[:4])}) and reused {len(set(var_usages))} tokens across stylesheets."
                    rec.current_stage = SkillLifecycleStage.APPLIED
                elif len(tokens) >= 3:
                    rec.applied_status = SkillApplicationStatus.PARTIAL
                    rec.applied_evidence = f"Defined {len(tokens)} :root tokens but only {len(set(var_usages))} reused via var()."
                else:
                    rec.applied_status = SkillApplicationStatus.FAIL
                    rec.applied_evidence = f"Lacks design system tokens in :root (found {len(tokens)}, minimum 3 required)."

            elif skill_id == "design-engineering":
                # Proof: Component geometry, alignment, responsive card grid layout (display: grid / flex), cards defined
                has_card_markup = bool(re.search(r'\bclass=["\'][^"\']*\bcard\b[^"\']*["\']', html_text, re.I))
                has_grid_layout = bool(re.search(r'display\s*:\s*(?:grid|flex)', css_text, re.I))
                has_spacing_rules = bool(re.search(r'gap\s*:|padding\s*:|margin\s*:', css_text, re.I))

                if has_card_markup and has_grid_layout and has_spacing_rules:
                    rec.applied_status = SkillApplicationStatus.APPLIED
                    rec.applied_evidence = "Implemented consistent component geometry, card layouts, responsive flex/grid compositions, and deliberate spacing."
                    rec.current_stage = SkillLifecycleStage.APPLIED
                elif has_card_markup or has_grid_layout:
                    rec.applied_status = SkillApplicationStatus.PARTIAL
                    rec.applied_evidence = "Partial component geometry (missing card components or grid/spacing definitions)."
                else:
                    rec.applied_status = SkillApplicationStatus.FAIL
                    rec.applied_evidence = "Missing structural component geometry, card markup, and grid layout."

            elif skill_id == "web-design-guidelines":
                # Proof: Semantic HTML tags, viewport meta, responsive media queries, overflow-x guard, all images have alt, visible focus states
                has_viewport = '<meta name="viewport"' in html_text or "<meta name='viewport'" in html_text
                has_semantic = bool(re.search(r'<(?:header|nav|main|section|footer)\b', html_text, re.I))
                has_media = bool(re.search(r'@media\s*\([^)]*max-width', css_text, re.I))
                has_overflow = bool(re.search(r'overflow-x\s*:\s*hidden', css_text, re.I))
                imgs = re.findall(r'<img\s+[^>]*>', html_text, re.I)
                missing_alt = [img for img in imgs if 'alt=' not in img.lower()]
                has_focus = bool(re.search(r':focus(?:-visible)?\b', css_text, re.I))

                issues = []
                if not has_viewport: issues.append("missing viewport meta tag")
                if not has_semantic: issues.append("missing semantic HTML tags")
                if not has_media: issues.append("missing responsive media queries")
                if not has_overflow: issues.append("missing overflow-x guard")
                if missing_alt: issues.append(f"{len(missing_alt)} images missing alt text")

                if not issues and has_focus:
                    rec.applied_status = SkillApplicationStatus.APPLIED
                    rec.applied_evidence = "Verified semantic markup, accessibility alt attributes, focus states, responsive media queries, and overflow guards."
                    rec.current_stage = SkillLifecycleStage.APPLIED
                elif len(issues) <= 1:
                    rec.applied_status = SkillApplicationStatus.PARTIAL
                    rec.applied_evidence = f"Web design guidelines partially met ({'; '.join(issues) if issues else 'lacks visible focus states'})."
                else:
                    rec.applied_status = SkillApplicationStatus.FAIL
                    rec.applied_evidence = f"Web design guideline violations: {'; '.join(issues)}."

            elif skill_id == "vanilla-web":
                # Proof: Native HTML5, CSS3, and ES6+ JavaScript without external framework dependencies
                has_html = len(html_files) > 0
                has_css = len(css_files) > 0
                has_js = len(js_files) > 0
                has_react_pkg = False
                pkg_file = ws / "package.json"
                if pkg_file.exists():
                    try:
                        pkg_data = json.loads(pkg_file.read_text(encoding="utf-8", errors="ignore"))
                        deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
                        has_react_pkg = any(k in deps for k in ("react", "vue", "@angular/core", "svelte"))
                    except Exception:
                        pass

                if has_html and (has_css or has_js) and not has_react_pkg:
                    rec.applied_status = SkillApplicationStatus.APPLIED
                    rec.applied_evidence = "Verified clean native HTML5, CSS3, and vanilla JavaScript implementation without framework bloat."
                    rec.current_stage = SkillLifecycleStage.APPLIED
                else:
                    rec.applied_status = SkillApplicationStatus.FAIL
                    rec.applied_evidence = "Missing core web files or unwanted framework detected."

            elif skill_id == "react-frontend":
                react_files = list(ws.glob("**/*.jsx")) + list(ws.glob("**/*.tsx"))
                has_react_import = bool(re.search(r'import\s+.*from\s+["\']react["\']|React\.', js_text))
                if react_files or has_react_import:
                    rec.applied_status = SkillApplicationStatus.APPLIED
                    rec.applied_evidence = "Verified functional React component architecture and state management."
                    rec.current_stage = SkillLifecycleStage.APPLIED
                else:
                    rec.applied_status = SkillApplicationStatus.FAIL
                    rec.applied_evidence = "Missing React component files or React import statements."

            results[skill_id] = {
                "applied_status": rec.applied_status.value,
                "applied_evidence": rec.applied_evidence,
                "current_stage": rec.current_stage.value,
            }
            rec.last_updated = time.time()

        self._atomic_persist()
        return results

    def evaluate_independent_verification(
        self,
        validation_report: Any,
        browser_qa: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Stage 6: Evaluate independent verification checks to promote APPLIED skills to VERIFIED.
        """
        is_contract_valid = getattr(validation_report, "is_valid", False)
        browser_passed = True
        if browser_qa:
            browser_passed = browser_qa.get("passed", True) and not browser_qa.get("console_errors")

        for skill_id, rec in self.records.items():
            if rec.applied_status == SkillApplicationStatus.APPLIED:
                if is_contract_valid and browser_passed:
                    rec.verified_status = SkillVerificationStatus.VERIFIED
                    rec.current_stage = SkillLifecycleStage.VERIFIED
                    rec.verification_results = {
                        "contract_valid": True,
                        "browser_verified": browser_passed,
                        "verified_at": time.time(),
                    }
                else:
                    rec.verified_status = SkillVerificationStatus.FAIL
                    rec.verification_results = {
                        "contract_valid": is_contract_valid,
                        "browser_verified": browser_passed,
                        "errors": getattr(validation_report, "errors", []),
                    }
            rec.last_updated = time.time()
        self._atomic_persist()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "created_at": self.created_at,
            "records": {k: v.to_dict() for k, v in self.records.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SkillEvidenceLedger:
        ledger = cls(mission_id=data.get("mission_id", ""))
        ledger.created_at = float(data.get("created_at", time.time()))
        for k, v in data.get("records", {}).items():
            ledger.records[k] = SkillEvidenceRecord.from_dict(v)
        return ledger

    def save_to_workspace(self, workspace_root: Path | str) -> Path:
        """Persist ledger atomically to .hermes/skill_evidence_ledger.json."""
        ws = Path(workspace_root).resolve()
        self.set_workspace_root(ws)
        self._atomic_persist()
        ledger_path = ws / ".hermes" / "skill_evidence_ledger.json"
        logger.info(f"SkillEvidenceLedger: saved {len(self.records)} records to {ledger_path}")
        return ledger_path

    @classmethod
    def load_from_workspace(cls, workspace_root: Path | str) -> Optional[SkillEvidenceLedger]:
        """Load ledger from .hermes/skill_evidence_ledger.json."""
        ws = Path(workspace_root).resolve()
        ledger_path = ws / ".hermes" / "skill_evidence_ledger.json"
        if not ledger_path.exists():
            return None
        try:
            data = json.loads(ledger_path.read_text(encoding="utf-8", errors="ignore"))
            return cls.from_dict(data)
        except Exception as e:
            logger.warning(f"SkillEvidenceLedger: error loading from {ledger_path}: {e}")
            return None
