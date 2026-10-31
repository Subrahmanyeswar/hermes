# core/alignment_verifier.py
"""
Deterministic Cross-File Alignment Verification Engine for HERMES Phase 11 (Stages 11.2 & 11.3).
Inspects workspace codebases, verifies cross-file coherence between HTML, CSS, and JS,
and validates against versioned contracts (ImplementationBlueprint, InterfaceManifest, QualityRubric).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse, unquote

from core.contracts.blueprint import ImplementationBlueprint
from core.contracts.manifest import InterfaceManifest
from core.contracts.rubric import QualityRubric


class DefectSeverity(str, Enum):
    """Severity classification for alignment defects."""
    ERROR = "ERROR"       # Hard failure: broken link, missing DOM ID, syntax error, etc.
    WARNING = "WARNING"   # Advisory failure: dynamic selector unverified, minor styling gap
    INFO = "INFO"         # Informational notice: diagnostic metric or notice


class DefectKind(str, Enum):
    """Categorized defect kind identifiers."""
    BROKEN_REFERENCE = "BROKEN_REFERENCE"             # HTML references missing CSS/JS/asset file
    MISSING_DOM_ID = "MISSING_DOM_ID"                 # JS/manifest expects DOM ID not present in HTML
    MISSING_CSS_CLASS = "MISSING_CSS_CLASS"           # Manifest/HTML expects CSS class not in stylesheet
    DUPLICATE_DOM_ID = "DUPLICATE_DOM_ID"             # Duplicate id attribute in same HTML document
    DEAD_LINK = "DEAD_LINK"                           # Internal link points to missing file
    DEAD_ANCHOR = "DEAD_ANCHOR"                       # Anchor hash points to missing ID in document
    UNRESOLVED_IMPORT = "UNRESOLVED_IMPORT"           # JS module imports symbol not exported by target
    EXPORT_MISMATCH = "EXPORT_MISMATCH"               # JS module lacks contract-required export
    UNPLANNED_FILE = "UNPLANNED_FILE"                 # File on disk not listed in blueprint (strict mode)
    MISSING_PLANNED_FILE = "MISSING_PLANNED_FILE"     # Planned blueprint file missing from disk
    PLACEHOLDER_DETECTED = "PLACEHOLDER_DETECTED"     # TODO, lorem ipsum, empty handler, or stub
    SYNTAX_ERROR = "SYNTAX_ERROR"                     # Unbalanced braces/brackets or invalid syntax
    PATH_TRAVERSAL_VIOLATION = "PATH_TRAVERSAL_VIOLATION" # Link/path escapes workspace root
    DYNAMIC_SELECTOR_UNVERIFIED = "DYNAMIC_SELECTOR_UNVERIFIED" # Dynamic JS query selector (advisory)
    ACCESSIBILITY_VIOLATION = "ACCESSIBILITY_VIOLATION" # Controls lacking accessible name or labels
    FORM_FIELD_MISMATCH = "FORM_FIELD_MISMATCH"       # Form missing contract required field
    MISSING_REQUIRED_CONTROL = "MISSING_REQUIRED_CONTROL" # Form or control missing from document
    RESPONSIVE_CONTRACT_VIOLATION = "RESPONSIVE_CONTRACT_VIOLATION" # Missing responsive rules
    REALISTIC_DATA_VIOLATION = "REALISTIC_DATA_VIOLATION" # Trivial mock/dummy data in place of domain data


@dataclass
class AlignmentDefect:
    """Detailed record of an alignment defect."""
    kind: DefectKind
    severity: DefectSeverity
    message: str
    file_path: str
    line_number: Optional[int] = None
    target: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "severity": self.severity.value,
            "message": self.message,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "target": self.target,
            "details": self.details,
        }


@dataclass
class AlignmentCheck:
    """Individual alignment check result category."""
    name: str
    status: str       # "PASS", "FAIL", "WARNING", "SKIPPED"
    message: str
    defects: List[AlignmentDefect] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "defects": [d.to_dict() for d in self.defects],
        }


@dataclass
class AlignmentReport:
    """Authoritative alignment verification report."""
    status: str       # "PASS", "FAIL", "WARNING"
    hard_error_count: int
    warning_count: int
    checks: List[AlignmentCheck]
    defects: List[AlignmentDefect]
    files_examined: List[str]
    limitations: List[str] = field(default_factory=list)
    report_hash: str = ""

    def __post_init__(self):
        if not self.report_hash:
            self.report_hash = self.compute_hash()

    def compute_hash(self) -> str:
        d = {
            "status": self.status,
            "hard_error_count": self.hard_error_count,
            "warning_count": self.warning_count,
            "checks": [c.to_dict() for c in self.checks],
            "files_examined": sorted(self.files_examined),
        }
        canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "hard_error_count": self.hard_error_count,
            "warning_count": self.warning_count,
            "checks": [c.to_dict() for c in self.checks],
            "defects": [d.to_dict() for d in self.defects],
            "files_examined": self.files_examined,
            "limitations": self.limitations,
            "report_hash": self.report_hash,
        }

    def summary(self) -> str:
        lines = [
            f"=== HERMES Alignment Verification Report [{self.status}] ===",
            f"Hard Errors: {self.hard_error_count} | Warnings: {self.warning_count} | Files: {len(self.files_examined)}",
            f"Report Hash: {self.report_hash[:16]}...",
        ]
        for check in self.checks:
            lines.append(f"  [{check.status}] {check.name}: {check.message}")
        if self.defects:
            lines.append("Defects Identified:")
            for d in self.defects:
                loc = f":{d.line_number}" if d.line_number else ""
                lines.append(f"  - [{d.severity.value}] {d.kind.value} in {d.file_path}{loc}: {d.message}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Path Containment & Asset Resolver
# ---------------------------------------------------------------------------

class AssetLinkResolver:
    """
    Resolves file paths, URLs, and anchors relative to document locations
    while strictly enforcing workspace containment.
    """

    @staticmethod
    def is_external_url(target: str) -> bool:
        t = target.strip().lower()
        return (
            t.startswith("http://")
            or t.startswith("https://")
            or t.startswith("//")
            or t.startswith("mailto:")
            or t.startswith("tel:")
            or t.startswith("data:")
            or t.startswith("javascript:")
        )

    @classmethod
    def is_safe_contained_path(cls, workspace_root: Path, target: Path) -> bool:
        """
        Verify candidate path is strictly contained within workspace_root.
        Enforces component-aware canonical containment, resolves symlinks, junctions,
        and reparse points, and fails closed.
        """
        try:
            ws_resolved = workspace_root.resolve()
            target_resolved = target.resolve()
            return target_resolved.is_relative_to(ws_resolved)
        except Exception:
            return False

    @classmethod
    def resolve_target_path(
        cls,
        workspace_root: Path,
        source_file_rel: str,
        target_ref: str,
    ) -> Tuple[Optional[Path], Optional[str], Optional[str]]:
        """
        Resolves a target reference against the workspace root and source file.
        Returns (resolved_path, anchor_fragment, error_kind).
        - If external URL, returns (None, None, None).
        - If pure in-page anchor '#section', returns (source_file_path, 'section', None).
        - If path traversal violation, returns (None, None, "PATH_TRAVERSAL_VIOLATION").
        """
        ref = target_ref.strip()
        if not ref or cls.is_external_url(ref):
            return None, None, None

        ws_resolved = workspace_root.resolve()

        # Handle pure in-page anchor
        if ref.startswith("#"):
            anchor = ref[1:].strip()
            source_abs = (ws_resolved / source_file_rel).resolve()
            return source_abs, anchor, None

        # Split path and anchor
        if "#" in ref:
            path_part, anchor_part = ref.split("#", 1)
        else:
            path_part, anchor_part = ref, None

        # Remove query parameters if present
        if "?" in path_part:
            path_part = path_part.split("?", 1)[0]

        path_part = unquote(path_part.strip())
        if not path_part:
            # e.g., "?foo=bar#section"
            source_abs = (ws_resolved / source_file_rel).resolve()
            return source_abs, anchor_part, None

        # Compute source directory
        source_abs = (ws_resolved / source_file_rel).resolve()
        source_dir = source_abs.parent if source_abs.is_file() or source_file_rel.endswith((".html", ".js", ".css")) else ws_resolved

        # If starts with leading slash '/', treat as workspace-root-relative
        if path_part.startswith("/"):
            candidate = (ws_resolved / path_part.lstrip("/")).resolve()
        else:
            candidate = (source_dir / path_part).resolve()

        # Workspace containment security check
        if not cls.is_safe_contained_path(ws_resolved, candidate):
            return None, None, DefectKind.PATH_TRAVERSAL_VIOLATION.value

        return candidate, anchor_part, None


# ---------------------------------------------------------------------------
# HTML Scanner
# ---------------------------------------------------------------------------

@dataclass
class HtmlDocumentInfo:
    file_path: str
    ids: Dict[str, int] = field(default_factory=dict)                          # id -> line_number
    duplicate_ids: List[Tuple[str, int]] = field(default_factory=list)          # [(id, line)]
    classes: Set[Tuple[str, int]] = field(default_factory=set)                  # {(class_name, line)}
    linked_css: List[Tuple[str, int]] = field(default_factory=list)             # [(href, line)]
    linked_js: List[Tuple[str, int]] = field(default_factory=list)              # [(src, line)]
    linked_assets: List[Tuple[str, str, int]] = field(default_factory=list)     # [(src, tag, line)]
    nav_links: List[Tuple[str, int]] = field(default_factory=list)              # [(href, line)]
    anchors: Set[str] = field(default_factory=set)                              # name / id anchors
    has_html_tag: bool = False
    has_body_tag: bool = False
    placeholders: List[Tuple[str, int]] = field(default_factory=list)
    buttons: List[Tuple[str, str, int]] = field(default_factory=list)
    inputs: List[Tuple[str, str, str, str, int]] = field(default_factory=list)
    forms: Dict[str, Tuple[List[str], int]] = field(default_factory=dict)
    labels: Dict[str, int] = field(default_factory=dict)


class _HtmlParserInternal(HTMLParser):
    def __init__(self, doc_info: HtmlDocumentInfo):
        super().__init__()
        self.doc = doc_info
        self._curr_button_id: Optional[str] = None
        self._curr_button_aria: str = ""
        self._curr_button_text: List[str] = []
        self._curr_button_line: int = 1
        self._curr_form_id: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        line = self.getpos()[0]

        tag_lower = tag.lower()
        if tag_lower == "html":
            self.doc.has_html_tag = True
        elif tag_lower == "body":
            self.doc.has_body_tag = True

        # DOM ID extraction and duplicate check
        if "id" in attr_dict:
            dom_id = attr_dict["id"].strip()
            if dom_id:
                if dom_id in self.doc.ids:
                    self.doc.duplicate_ids.append((dom_id, line))
                else:
                    self.doc.ids[dom_id] = line
                    self.doc.anchors.add(dom_id)

        # Anchor tag with name
        if tag_lower == "a" and "name" in attr_dict:
            name_val = attr_dict["name"].strip()
            if name_val:
                self.doc.anchors.add(name_val)

        # Class attribute extraction
        if "class" in attr_dict:
            class_val = attr_dict["class"].strip()
            for cls_token in class_val.split():
                cls_clean = cls_token.strip()
                if cls_clean:
                    self.doc.classes.add((cls_clean, line))

        # Linked CSS: <link rel="stylesheet" href="...">
        if tag_lower == "link":
            rel = attr_dict.get("rel", "").lower()
            href = attr_dict.get("href", "").strip()
            if href and ("stylesheet" in rel or href.endswith(".css")):
                self.doc.linked_css.append((href, line))

        # Linked JS: <script src="...">
        if tag_lower == "script":
            src = attr_dict.get("src", "").strip()
            if src:
                self.doc.linked_js.append((src, line))

        # Linked Media/Assets: <img>, <video>, <audio>, <source>
        if tag_lower in ("img", "video", "audio", "source"):
            src = attr_dict.get("src", "").strip()
            if not src and tag_lower == "source":
                src = attr_dict.get("srcset", "").strip()
            if src:
                self.doc.linked_assets.append((src, tag_lower, line))

        # Navigation Links: <a href="...">
        if tag_lower == "a":
            href = attr_dict.get("href", "").strip()
            if href:
                self.doc.nav_links.append((href, line))

        # Forms
        if tag_lower == "form":
            f_id = attr_dict.get("id", "").strip()
            self._curr_form_id = f_id if f_id else None
            if f_id:
                self.doc.forms[f_id] = ([], line)

        # Form Controls (inputs, selects, textareas)
        if tag_lower in ("input", "select", "textarea"):
            inp_id = attr_dict.get("id", "").strip()
            inp_name = attr_dict.get("name", "").strip()
            inp_type = attr_dict.get("type", "text").strip().lower()
            aria_or_ph = (attr_dict.get("aria-label") or attr_dict.get("placeholder") or attr_dict.get("title") or "").strip()
            self.doc.inputs.append((inp_id, inp_name, inp_type, aria_or_ph, line))
            if self._curr_form_id and self._curr_form_id in self.doc.forms:
                field_ident = inp_name or inp_id
                if field_ident:
                    self.doc.forms[self._curr_form_id][0].append(field_ident)

        # Labels
        if tag_lower == "label":
            for_target = attr_dict.get("for", "").strip()
            if for_target:
                self.doc.labels[for_target] = line

        # Buttons
        if tag_lower == "button":
            self._curr_button_id = attr_dict.get("id", "").strip()
            self._curr_button_aria = (attr_dict.get("aria-label") or attr_dict.get("title") or "").strip()
            self._curr_button_text = []
            self._curr_button_line = line

    def handle_data(self, data: str):
        if self._curr_button_id is not None or self._curr_button_text:
            self._curr_button_text.append(data.strip())

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower == "button":
            text_val = " ".join(filter(None, self._curr_button_text)).strip()
            acc_name = text_val or self._curr_button_aria
            self.doc.buttons.append((self._curr_button_id or "", acc_name, self._curr_button_line))
            self._curr_button_id = None
            self._curr_button_aria = ""
            self._curr_button_text = []
        elif tag_lower == "form":
            self._curr_form_id = None


class HtmlAlignmentScanner:
    """Scans HTML files for DOM IDs, classes, linked files, and anti-placeholder tokens."""

    @classmethod
    def scan_file(cls, rel_path: str, content: str) -> HtmlDocumentInfo:
        doc = HtmlDocumentInfo(file_path=rel_path)
        parser = _HtmlParserInternal(doc)

        try:
            parser.feed(content)
        except Exception:
            # Fallback regex scanning if parser encounters structural quirks
            pass

        # Scan for anti-placeholder tokens in HTML
        cls._scan_placeholders(rel_path, content, doc)
        return doc

    @classmethod
    def _scan_placeholders(cls, rel_path: str, content: str, doc: HtmlDocumentInfo):
        lines = content.splitlines()
        for idx, line in enumerate(lines, start=1):
            line_lower = line.lower()
            if "lorem ipsum" in line_lower:
                doc.placeholders.append((f"Found placeholder text 'Lorem ipsum' on line {idx}", idx))
            if re.search(r"<!--\s*(TODO|FIXME|TBD|PLACEHOLDER)\b", line, re.IGNORECASE):
                doc.placeholders.append((f"Found TODO/placeholder comment on line {idx}", idx))


# ---------------------------------------------------------------------------
# CSS Scanner
# ---------------------------------------------------------------------------

@dataclass
class CssDocumentInfo:
    file_path: str
    classes: Set[str] = field(default_factory=set)
    ids: Set[str] = field(default_factory=set)
    keyframes: Set[str] = field(default_factory=set)
    custom_properties: Set[str] = field(default_factory=set)
    url_references: List[Tuple[str, int]] = field(default_factory=list)        # [(url, line)]
    is_empty_or_stub: bool = False
    placeholders: List[Tuple[str, int]] = field(default_factory=list)
    syntax_errors: List[str] = field(default_factory=list)


class CssAlignmentScanner:
    """Comment-safe and string-safe scanner for CSS stylesheets."""

    @classmethod
    def scan_file(cls, rel_path: str, content: str) -> CssDocumentInfo:
        info = CssDocumentInfo(file_path=rel_path)

        # Check comment-stripped content
        stripped = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL).strip()
        if len(stripped) < 15:
            info.is_empty_or_stub = True

        # Check balance of curly braces
        if stripped.count("{") != stripped.count("}"):
            info.syntax_errors.append(f"Unbalanced braces '{{' and '}}' in {rel_path}")

        # Extract url(...) references line by line
        for idx, line in enumerate(content.splitlines(), start=1):
            line_no_comment = re.sub(r"/\*.*?\*/", "", line)
            url_matches = re.findall(r"url\(\s*['\"]?([^)'\"]+?)['\"]?\s*\)", line_no_comment)
            for u in url_matches:
                u_clean = u.strip()
                if u_clean and not AssetLinkResolver.is_external_url(u_clean):
                    info.url_references.append((u_clean, idx))

        # Strip strings so content: ".fake-class" is not treated as a class definition
        no_strings = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '""', stripped)

        # Extract classes: .class-name
        class_matches = re.findall(r"\.([a-zA-Z0-9_-]+)(?=[^a-zA-Z0-9_-]|$)", no_strings)
        info.classes.update(class_matches)

        # Extract IDs: #id-name
        id_matches = re.findall(r"#([a-zA-Z0-9_-]+)(?=[^a-zA-Z0-9_-]|$)", no_strings)
        info.ids.update(id_matches)

        # Extract keyframes: @keyframes name
        kf_matches = re.findall(r"@keyframes\s+([a-zA-Z0-9_-]+)", no_strings)
        info.keyframes.update(kf_matches)

        # Extract custom properties: --property-name
        prop_matches = re.findall(r"(--[a-zA-Z0-9_-]+)\s*:", no_strings)
        info.custom_properties.update(prop_matches)

        # Check for placeholders
        for idx, line in enumerate(content.splitlines(), start=1):
            if re.search(r"/\*\s*(TODO|FIXME|PLACEHOLDER)\b", line, re.IGNORECASE):
                info.placeholders.append((f"Found TODO comment in CSS on line {idx}", idx))

        return info


# ---------------------------------------------------------------------------
# JavaScript Scanner
# ---------------------------------------------------------------------------

@dataclass
class JsImport:
    symbols: List[str]
    from_source: str
    is_default: bool = False
    line: int = 1


@dataclass
class JsExport:
    name: str
    is_default: bool = False
    line: int = 1


@dataclass
class JsDocumentInfo:
    file_path: str
    get_element_ids: List[Tuple[str, int]] = field(default_factory=list)       # [(id, line)]
    query_selectors: List[Tuple[str, int]] = field(default_factory=list)       # [(sel, line)]
    dynamic_selectors: List[Tuple[str, int]] = field(default_factory=list)     # [(expr, line)]
    event_listeners: List[Tuple[str, str, int]] = field(default_factory=list)  # [(target, event, line)]
    imports: List[JsImport] = field(default_factory=list)
    exports: List[JsExport] = field(default_factory=list)
    syntax_errors: List[str] = field(default_factory=list)
    placeholders: List[Tuple[str, int]] = field(default_factory=list)
    is_empty_or_stub: bool = False


class JsAlignmentScanner:
    """Comment-safe scanner for JavaScript scripts and ES modules."""

    @classmethod
    def scan_file(cls, rel_path: str, content: str, abs_path: Optional[Path] = None) -> JsDocumentInfo:
        info = JsDocumentInfo(file_path=rel_path)

        # Check genuine syntax via node --check if file is on disk and node is available
        if abs_path and abs_path.is_file():
            cls._check_node_syntax(abs_path, info)

        # Block comments replaced with spaces to preserve line numbering
        def _preserve_lines(m):
            return "".join("\n" if c == "\n" else " " for c in m.group(0))

        no_block_comments = re.sub(r"/\*.*?\*/", _preserve_lines, content, flags=re.DOTALL)
        no_comments = re.sub(r"//[^\n]*", "", no_block_comments).strip()

        if len(no_comments) < 20:
            info.is_empty_or_stub = True

        # Fallback brace/bracket balance check if no syntax error already reported
        if not info.syntax_errors:
            for open_ch, close_ch, name in [("{", "}", "braces"), ("(", ")", "parentheses"), ("[", "]", "brackets")]:
                if no_comments.count(open_ch) != no_comments.count(close_ch):
                    info.syntax_errors.append(f"Unbalanced {name} '{open_ch}' and '{close_ch}' in {rel_path}")

        raw_lines = content.splitlines()
        code_lines = no_block_comments.splitlines()

        # Line-by-line scanning for DOM queries, event hooks, and placeholders
        for idx, line in enumerate(raw_lines, start=1):
            line_stripped = line.strip()

            # Placeholder detection
            if re.search(r"//\s*(TODO|FIXME|PLACEHOLDER)\b|/\*\s*(TODO|FIXME|PLACEHOLDER)\b", line, re.IGNORECASE):
                info.placeholders.append((f"Found TODO/placeholder comment in JS on line {idx}", idx))
            if "lorem ipsum" in line.lower():
                info.placeholders.append((f"Found 'Lorem ipsum' in JS on line {idx}", idx))

            # Strip single-line comments for code analysis on this line
            code_line_base = code_lines[idx - 1] if idx - 1 < len(code_lines) else line
            code_line = re.sub(r"//.*$", "", code_line_base)

            # Match document.getElementById(...)
            for m in re.finditer(r"\bdocument\s*\.\s*getElementById\s*\(([^)]+)\)", code_line):
                prefix = code_line[:m.start()]
                quote_count = sum(prefix.count(q) for q in ('"', "'", '`'))
                if quote_count % 2 != 0:
                    continue  # inside a string literal, skip!

                raw_arg = m.group(1).strip()
                static_m = re.match(r"^['\"]([a-zA-Z0-9_-]+)['\"]$", raw_arg)
                if static_m:
                    info.get_element_ids.append((static_m.group(1), idx))
                else:
                    info.dynamic_selectors.append((raw_arg, idx))

            # Match document.querySelector(...) / querySelectorAll(...)
            for m in re.finditer(r"\bdocument\s*\.\s*querySelector(?:All)?\s*\(([^)]+)\)", code_line):
                prefix = code_line[:m.start()]
                quote_count = sum(prefix.count(q) for q in ('"', "'", '`'))
                if quote_count % 2 != 0:
                    continue

                raw_arg = m.group(1).strip()
                static_m = re.match(r"^['\"]([^'\"]+)['\"]$", raw_arg)
                if static_m:
                    info.query_selectors.append((static_m.group(1), idx))
                else:
                    info.dynamic_selectors.append((raw_arg, idx))
            # Event listeners: addEventListener('event', ...)
            ev_matches = re.findall(r"\.addEventListener\(\s*['\"]([a-zA-Z0-9_-]+)['\"]", line)
            for ev in ev_matches:
                info.event_listeners.append(("", ev, idx))

        # ES Module import / export extraction across entire content
        cls._extract_esm(no_comments, info)

        return info

    @classmethod
    def _extract_esm(cls, code: str, info: JsDocumentInfo):
        # import { a, b as c } from './path.js'
        import_named = re.findall(r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]", code)
        for sym_str, src in import_named:
            symbols = [s.strip().split(" as ")[0].strip() for s in sym_str.split(",") if s.strip()]
            info.imports.append(JsImport(symbols=symbols, from_source=src))

        # import DefaultName from './path.js'
        import_default = re.findall(r"import\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s+from\s*['\"]([^'\"]+)['\"]", code)
        for sym, src in import_default:
            info.imports.append(JsImport(symbols=[sym], from_source=src, is_default=True))

        # export function / const / let / class / default
        export_fns = re.findall(r"export\s+(?:async\s+)?function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)", code)
        for fn in export_fns:
            info.exports.append(JsExport(name=fn))

        export_vars = re.findall(r"export\s+(?:const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)", code)
        for v in export_vars:
            info.exports.append(JsExport(name=v))

        export_classes = re.findall(r"export\s+class\s+([a-zA-Z_$][a-zA-Z0-9_$]*)", code)
        for c in export_classes:
            info.exports.append(JsExport(name=c))

        export_named = re.findall(r"export\s*\{([^}]+)\}", code)
        for sym_str in export_named:
            for s in sym_str.split(","):
                s_clean = s.strip().split(" as ")[-1].strip()
                if s_clean:
                    info.exports.append(JsExport(name=s_clean))

        if re.search(r"export\s+default\b", code):
            info.exports.append(JsExport(name="default", is_default=True))

    @classmethod
    def _check_node_syntax(cls, file_path: Path, info: JsDocumentInfo):
        import subprocess
        try:
            res = subprocess.run(
                ["node", "--check", str(file_path)],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res.returncode != 0:
                first_line = (res.stderr.strip().splitlines() or ["Syntax error"])[0]
                info.syntax_errors.append(f"JavaScript compiler syntax error in {file_path.name}: {first_line}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Core Alignment Verifier Engine
# ---------------------------------------------------------------------------

def verify_project_alignment(
    workspace_root: Path | str,
    blueprint: Optional[ImplementationBlueprint] = None,
    interface_manifest: Optional[InterfaceManifest] = None,
    quality_rubric: Optional[QualityRubric] = None,
    strict_file_set: bool = False,
) -> AlignmentReport:
    """
    Main entry point for deterministic cross-file alignment verification.
    Validates filesystem assets against each other and against versioned contracts.
    """
    ws_path = Path(workspace_root).resolve()
    if not ws_path.exists() or not ws_path.is_dir():
        defect = AlignmentDefect(
            kind=DefectKind.BROKEN_REFERENCE,
            severity=DefectSeverity.ERROR,
            message=f"Workspace root directory does not exist: {ws_path}",
            file_path=".",
        )
        check = AlignmentCheck(name="workspace_root", status="FAIL", message="Missing workspace root", defects=[defect])
        return AlignmentReport(
            status="FAIL",
            hard_error_count=1,
            warning_count=0,
            checks=[check],
            defects=[defect],
            files_examined=[],
        )

    # 1. Discover all project files
    all_files: List[Path] = []
    for root, _, files in os.walk(ws_path):
        for f in files:
            p = Path(root) / f
            # Ignore hidden files, venv, git, node_modules
            rel = p.relative_to(ws_path).as_posix()
            if any(part.startswith(".") for part in p.parts):
                continue
            if any(part in ("venv", "node_modules", "__pycache__", "dist", "build") for part in p.parts):
                continue
            all_files.append(p)

    examined_rel_files = [f.relative_to(ws_path).as_posix() for f in all_files]

    # Scanned data structures
    html_docs: Dict[str, HtmlDocumentInfo] = {}
    css_docs: Dict[str, CssDocumentInfo] = {}
    js_docs: Dict[str, JsDocumentInfo] = {}

    all_defects: List[AlignmentDefect] = []
    checks: List[AlignmentCheck] = []
    limitations: List[str] = []

    # 2. Parse all HTML, CSS, and JS files
    for file_path in all_files:
        rel_posix = file_path.relative_to(ws_path).as_posix()
        ext = file_path.suffix.lower()

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            all_defects.append(
                AlignmentDefect(
                    kind=DefectKind.SYNTAX_ERROR,
                    severity=DefectSeverity.ERROR,
                    message=f"Failed to read file: {e}",
                    file_path=rel_posix,
                )
            )
            continue

        if ext in (".html", ".htm"):
            html_docs[rel_posix] = HtmlAlignmentScanner.scan_file(rel_posix, content)
        elif ext == ".css":
            css_docs[rel_posix] = CssAlignmentScanner.scan_file(rel_posix, content)
        elif ext in (".js", ".mjs"):
            js_docs[rel_posix] = JsAlignmentScanner.scan_file(rel_posix, content, abs_path=file_path)

    # -----------------------------------------------------------------------
    # Check 1: HTML Document Structure & Intra-file Duplicate DOM IDs
    # -----------------------------------------------------------------------
    check1_defects: List[AlignmentDefect] = []
    for rel_html, doc in html_docs.items():
        # Check intra-document duplicate IDs
        for dup_id, line in doc.duplicate_ids:
            check1_defects.append(
                AlignmentDefect(
                    kind=DefectKind.DUPLICATE_DOM_ID,
                    severity=DefectSeverity.ERROR,
                    message=f"Duplicate DOM ID '{dup_id}' found in same document",
                    file_path=rel_html,
                    line_number=line,
                    target=dup_id,
                )
            )

    check1_status = "FAIL" if check1_defects else "PASS"
    checks.append(
        AlignmentCheck(
            name="html_dom_id_uniqueness",
            status=check1_status,
            message="All DOM IDs unique per HTML document" if not check1_defects else f"Found {len(check1_defects)} duplicate DOM ID(s)",
            defects=check1_defects,
        )
    )

    # -----------------------------------------------------------------------
    # Check 2: HTML References to CSS, JS, and Media Assets
    # -----------------------------------------------------------------------
    check2_defects: List[AlignmentDefect] = []
    for rel_html, doc in html_docs.items():
        # Verify linked CSS
        for css_href, line in doc.linked_css:
            resolved_path, _, err = AssetLinkResolver.resolve_target_path(ws_path, rel_html, css_href)
            if err == DefectKind.PATH_TRAVERSAL_VIOLATION.value:
                check2_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.PATH_TRAVERSAL_VIOLATION,
                        severity=DefectSeverity.ERROR,
                        message=f"Path traversal escape detected in CSS reference '{css_href}'",
                        file_path=rel_html,
                        line_number=line,
                        target=css_href,
                    )
                )
            elif resolved_path is not None and not resolved_path.exists():
                check2_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.BROKEN_REFERENCE,
                        severity=DefectSeverity.ERROR,
                        message=f"HTML references stylesheet '{css_href}' which does not exist",
                        file_path=rel_html,
                        line_number=line,
                        target=css_href,
                    )
                )

        # Verify linked JS
        for js_src, line in doc.linked_js:
            resolved_path, _, err = AssetLinkResolver.resolve_target_path(ws_path, rel_html, js_src)
            if err == DefectKind.PATH_TRAVERSAL_VIOLATION.value:
                check2_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.PATH_TRAVERSAL_VIOLATION,
                        severity=DefectSeverity.ERROR,
                        message=f"Path traversal escape detected in script reference '{js_src}'",
                        file_path=rel_html,
                        line_number=line,
                        target=js_src,
                    )
                )
            elif resolved_path is not None and not resolved_path.exists():
                check2_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.BROKEN_REFERENCE,
                        severity=DefectSeverity.ERROR,
                        message=f"HTML references script '{js_src}' which does not exist",
                        file_path=rel_html,
                        line_number=line,
                        target=js_src,
                    )
                )

        # Verify linked Assets (images, audio, video)
        for asset_src, tag, line in doc.linked_assets:
            resolved_path, _, err = AssetLinkResolver.resolve_target_path(ws_path, rel_html, asset_src)
            if err == DefectKind.PATH_TRAVERSAL_VIOLATION.value:
                check2_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.PATH_TRAVERSAL_VIOLATION,
                        severity=DefectSeverity.ERROR,
                        message=f"Path traversal escape detected in asset reference '{asset_src}'",
                        file_path=rel_html,
                        line_number=line,
                        target=asset_src,
                    )
                )
            elif resolved_path is not None and not resolved_path.exists():
                check2_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.BROKEN_REFERENCE,
                        severity=DefectSeverity.ERROR,
                        message=f"HTML <{tag}> references asset '{asset_src}' which does not exist",
                        file_path=rel_html,
                        line_number=line,
                        target=asset_src,
                    )
                )

    # Verify CSS url() asset references
    for rel_css, doc in css_docs.items():
        for url_ref, line in doc.url_references:
            resolved_path, _, err = AssetLinkResolver.resolve_target_path(ws_path, rel_css, url_ref)
            if err == DefectKind.PATH_TRAVERSAL_VIOLATION.value:
                check2_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.PATH_TRAVERSAL_VIOLATION,
                        severity=DefectSeverity.ERROR,
                        message=f"Path traversal escape detected in CSS url \'{url_ref}\'",
                        file_path=rel_css,
                        line_number=line,
                        target=url_ref,
                    )
                )
            elif resolved_path is not None and not resolved_path.exists():
                check2_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.BROKEN_REFERENCE,
                        severity=DefectSeverity.ERROR,
                        message=f"CSS stylesheet references asset \'{url_ref}\' which does not exist",
                        file_path=rel_css,
                        line_number=line,
                        target=url_ref,
                    )
                )
            elif resolved_path is not None and not resolved_path.exists():
                check2_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.BROKEN_REFERENCE,
                        severity=DefectSeverity.ERROR,
                        message=f"HTML <{tag}> references asset '{asset_src}' which does not exist",
                        file_path=rel_html,
                        line_number=line,
                        target=asset_src,
                    )
                )

    check2_status = "FAIL" if check2_defects else "PASS"
    checks.append(
        AlignmentCheck(
            name="html_linked_resources",
            status=check2_status,
            message="All linked scripts, stylesheets, and assets resolve" if not check2_defects else f"Found {len(check2_defects)} broken resource reference(s)",
            defects=check2_defects,
        )
    )

    # -----------------------------------------------------------------------
    # Check 3: Navigation Links and Anchors
    # -----------------------------------------------------------------------
    check3_defects: List[AlignmentDefect] = []
    for rel_html, doc in html_docs.items():
        for href, line in doc.nav_links:
            resolved_path, anchor, err = AssetLinkResolver.resolve_target_path(ws_path, rel_html, href)
            if err == DefectKind.PATH_TRAVERSAL_VIOLATION.value:
                check3_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.PATH_TRAVERSAL_VIOLATION,
                        severity=DefectSeverity.ERROR,
                        message=f"Path traversal escape detected in navigation link '{href}'",
                        file_path=rel_html,
                        line_number=line,
                        target=href,
                    )
                )
            elif resolved_path is not None:
                # Target file existence check
                if not resolved_path.exists():
                    check3_defects.append(
                        AlignmentDefect(
                            kind=DefectKind.DEAD_LINK,
                            severity=DefectSeverity.ERROR,
                            message=f"Navigation link '{href}' targets missing file",
                            file_path=rel_html,
                            line_number=line,
                            target=href,
                        )
                    )
                elif anchor:
                    # Target document exists; check anchor resolution
                    target_rel = resolved_path.relative_to(ws_path).as_posix()
                    target_doc = html_docs.get(target_rel)
                    if target_doc is not None:
                        if anchor not in target_doc.anchors:
                            check3_defects.append(
                                AlignmentDefect(
                                    kind=DefectKind.DEAD_ANCHOR,
                                    severity=DefectSeverity.ERROR,
                                    message=f"Anchor '#{anchor}' does not exist in target document '{target_rel}'",
                                    file_path=rel_html,
                                    line_number=line,
                                    target=href,
                                )
                            )

    check3_status = "FAIL" if check3_defects else "PASS"
    checks.append(
        AlignmentCheck(
            name="navigation_and_anchors",
            status=check3_status,
            message="All navigation links and anchor fragments resolve" if not check3_defects else f"Found {len(check3_defects)} dead link or anchor defect(s)",
            defects=check3_defects,
        )
    )

    # -----------------------------------------------------------------------
    # Check 4: JavaScript DOM Queries vs HTML DOM Elements
    # -----------------------------------------------------------------------
    check4_defects: List[AlignmentDefect] = []
    # Collect all available DOM IDs across HTML entrypoints
    all_html_ids: Set[str] = set()
    for doc in html_docs.values():
        all_html_ids.update(doc.ids.keys())

    for rel_js, js_info in js_docs.items():
        # Check static getElementById
        for gid, line in js_info.get_element_ids:
            if gid not in all_html_ids:
                check4_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.MISSING_DOM_ID,
                        severity=DefectSeverity.ERROR,
                        message=f"JS references DOM ID '{gid}' via getElementById, but ID is not defined in any HTML document",
                        file_path=rel_js,
                        line_number=line,
                        target=gid,
                    )
                )

        # Check static querySelector('#id')
        for qsel, line in js_info.query_selectors:
            # Check simple #id selector
            id_m = re.search(r"#([a-zA-Z0-9_-]+)", qsel.strip())
            if id_m:
                qid = id_m.group(1)
                if qid not in all_html_ids:
                    check4_defects.append(
                        AlignmentDefect(
                            kind=DefectKind.MISSING_DOM_ID,
                            severity=DefectSeverity.ERROR,
                            message=f"JS references DOM ID '{qid}' via querySelector('{qsel}'), but ID is not defined in HTML",
                            file_path=rel_js,
                            line_number=line,
                            target=qid,
                        )
                    )

        # Record dynamic selectors as warnings (not hard errors!)
        for dyn_expr, line in js_info.dynamic_selectors:
            check4_defects.append(
                AlignmentDefect(
                    kind=DefectKind.DYNAMIC_SELECTOR_UNVERIFIED,
                    severity=DefectSeverity.WARNING,
                    message=f"Dynamic DOM query '{dyn_expr}' detected; static verification bypassed",
                    file_path=rel_js,
                    line_number=line,
                    target=dyn_expr,
                )
            )

    hard_dom_defects = [d for d in check4_defects if d.severity == DefectSeverity.ERROR]
    check4_status = "FAIL" if hard_dom_defects else ("WARNING" if check4_defects else "PASS")
    checks.append(
        AlignmentCheck(
            name="js_dom_element_alignment",
            status=check4_status,
            message="All statically queried DOM elements match HTML IDs" if not hard_dom_defects else f"Found {len(hard_dom_defects)} missing DOM ID reference(s)",
            defects=check4_defects,
        )
    )

    # -----------------------------------------------------------------------
    # Check 5: JS Module Imports and Exports
    # -----------------------------------------------------------------------
    check5_defects: List[AlignmentDefect] = []
    for rel_js, js_info in js_docs.items():
        for imp in js_info.imports:
            # Resolve module source file
            resolved_mod, _, err = AssetLinkResolver.resolve_target_path(ws_path, rel_js, imp.from_source)
            if err == DefectKind.PATH_TRAVERSAL_VIOLATION.value:
                check5_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.PATH_TRAVERSAL_VIOLATION,
                        severity=DefectSeverity.ERROR,
                        message=f"Path traversal escape in JS import '{imp.from_source}'",
                        file_path=rel_js,
                        line_number=imp.line,
                        target=imp.from_source,
                    )
                )
            elif resolved_mod is not None:
                if not resolved_mod.exists():
                    check5_defects.append(
                        AlignmentDefect(
                            kind=DefectKind.UNRESOLVED_IMPORT,
                            severity=DefectSeverity.ERROR,
                            message=f"Cannot resolve JS module '{imp.from_source}'",
                            file_path=rel_js,
                            line_number=imp.line,
                            target=imp.from_source,
                        )
                    )
                else:
                    target_rel = resolved_mod.relative_to(ws_path).as_posix()
                    target_js = js_docs.get(target_rel)
                    if target_js is not None:
                        target_exports = {e.name for e in target_js.exports}
                        has_default = any(e.is_default for e in target_js.exports)
                        if imp.is_default and not has_default:
                            check5_defects.append(
                                AlignmentDefect(
                                    kind=DefectKind.UNRESOLVED_IMPORT,
                                    severity=DefectSeverity.ERROR,
                                    message=f"Module '{target_rel}' has no default export for import in '{rel_js}'",
                                    file_path=rel_js,
                                    line_number=imp.line,
                                    target=imp.from_source,
                                )
                            )
                        elif not imp.is_default:
                            for sym in imp.symbols:
                                if sym not in target_exports:
                                    check5_defects.append(
                                        AlignmentDefect(
                                            kind=DefectKind.UNRESOLVED_IMPORT,
                                            severity=DefectSeverity.ERROR,
                                            message=f"Symbol '{sym}' not exported by '{target_rel}'",
                                            file_path=rel_js,
                                            line_number=imp.line,
                                            target=sym,
                                        )
                                    )

    check5_status = "FAIL" if check5_defects else "PASS"
    checks.append(
        AlignmentCheck(
            name="js_module_import_export",
            status=check5_status,
            message="All JS module imports match declared exports" if not check5_defects else f"Found {len(check5_defects)} unresolved import defect(s)",
            defects=check5_defects,
        )
    )

    # -----------------------------------------------------------------------
    # Check 6: Syntax Balance and Structural Sanity
    # -----------------------------------------------------------------------
    check6_defects: List[AlignmentDefect] = []
    for rel_js, js_info in js_docs.items():
        for err_msg in js_info.syntax_errors:
            check6_defects.append(
                AlignmentDefect(
                    kind=DefectKind.SYNTAX_ERROR,
                    severity=DefectSeverity.ERROR,
                    message=err_msg,
                    file_path=rel_js,
                )
            )

    for rel_css, css_info in css_docs.items():
        for err_msg in css_info.syntax_errors:
            check6_defects.append(
                AlignmentDefect(
                    kind=DefectKind.SYNTAX_ERROR,
                    severity=DefectSeverity.ERROR,
                    message=err_msg,
                    file_path=rel_css,
                )
            )

    check6_status = "FAIL" if check6_defects else "PASS"
    checks.append(
        AlignmentCheck(
            name="syntax_integrity",
            status=check6_status,
            message="No syntax or balance errors found in CSS/JS" if not check6_defects else f"Found {len(check6_defects)} syntax defect(s)",
            defects=check6_defects,
        )
    )

    # -----------------------------------------------------------------------
    # Check 7: Implementation Blueprint Reconciliation (if provided)
    # -----------------------------------------------------------------------
    check7_defects: List[AlignmentDefect] = []
    if blueprint is not None:
        planned_rel_set: Set[str] = set()
        for fp in blueprint.planned_files:
            norm_plan = fp.path.replace("\\", "/").lstrip("./")
            planned_rel_set.add(norm_plan)
            target_file = ws_path / norm_plan
            if not target_file.exists():
                check7_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.MISSING_PLANNED_FILE,
                        severity=DefectSeverity.ERROR,
                        message=f"Blueprint planned file '{norm_plan}' ({fp.purpose}) does not exist on disk",
                        file_path=norm_plan,
                        target=norm_plan,
                    )
                )

        # If strict_file_set enabled, check for unplanned files
        if strict_file_set:
            for actual_rel in examined_rel_files:
                if actual_rel not in planned_rel_set:
                    check7_defects.append(
                        AlignmentDefect(
                            kind=DefectKind.UNPLANNED_FILE,
                            severity=DefectSeverity.WARNING,
                            message=f"File '{actual_rel}' on disk was not planned in ImplementationBlueprint",
                            file_path=actual_rel,
                            target=actual_rel,
                        )
                    )

        check7_status = "FAIL" if any(d.severity == DefectSeverity.ERROR for d in check7_defects) else ("WARNING" if check7_defects else "PASS")
        checks.append(
            AlignmentCheck(
                name="blueprint_reconciliation",
                status=check7_status,
                message="All planned blueprint files exist" if not check7_defects else f"Found {len(check7_defects)} blueprint reconciliation defect(s)",
                defects=check7_defects,
            )
        )
    else:
        checks.append(
            AlignmentCheck(
                name="blueprint_reconciliation",
                status="SKIPPED",
                message="No ImplementationBlueprint supplied; skipped",
            )
        )

    # -----------------------------------------------------------------------
    # Check 8: Interface Manifest Reconciliation (if provided)
    # -----------------------------------------------------------------------
    check8_defects: List[AlignmentDefect] = []
    if interface_manifest is not None:
        # 1. Element ID contracts
        for elem_key, elem_contract in interface_manifest.element_ids.items():
            if not elem_contract.required:
                continue
            owning_rel = elem_contract.owning_file.replace("\\", "/").lstrip("./")
            doc = html_docs.get(owning_rel)
            if doc is None:
                check8_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.MISSING_PLANNED_FILE,
                        severity=DefectSeverity.ERROR,
                        message=f"Owning file '{owning_rel}' for DOM element '{elem_contract.dom_id}' not found",
                        file_path=owning_rel,
                        target=elem_contract.dom_id,
                    )
                )
            elif elem_contract.dom_id not in doc.ids:
                check8_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.MISSING_DOM_ID,
                        severity=DefectSeverity.ERROR,
                        message=f"Manifest element ID '{elem_contract.dom_id}' missing in owning file '{owning_rel}'",
                        file_path=owning_rel,
                        target=elem_contract.dom_id,
                    )
                )

        # 2. CSS Class contracts
        all_css_classes: Set[str] = set()
        for cdoc in css_docs.values():
            all_css_classes.update(cdoc.classes)

        for cls_name, cls_contract in interface_manifest.css_classes.items():
            owning_css = cls_contract.owning_file.replace("\\", "/").lstrip("./")
            css_doc = css_docs.get(owning_css)
            if css_doc is None and not (ws_path / owning_css).exists():
                check8_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.MISSING_PLANNED_FILE,
                        severity=DefectSeverity.ERROR,
                        message=f"Owning stylesheet '{owning_css}' for CSS class '{cls_name}' not found",
                        file_path=owning_css,
                        target=cls_name,
                    )
                )
            elif cls_name not in all_css_classes:
                check8_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.MISSING_CSS_CLASS,
                        severity=DefectSeverity.ERROR,
                        message=f"Manifest contract-owned CSS class '{cls_name}' is not defined in stylesheets",
                        file_path=owning_css,
                        target=cls_name,
                    )
                )

        # 3. JS Module contracts
        for mod_name, mod_contract in interface_manifest.js_modules.items():
            mod_file = mod_contract.file_path.replace("\\", "/").lstrip("./")
            js_doc = js_docs.get(mod_file)
            if js_doc is None:
                check8_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.MISSING_PLANNED_FILE,
                        severity=DefectSeverity.ERROR,
                        message=f"Owning JS module file '{mod_file}' for '{mod_name}' not found",
                        file_path=mod_file,
                        target=mod_name,
                    )
                )
            else:
                existing_exports = {e.name for e in js_doc.exports}
                for exp_sym in mod_contract.exports:
                    if exp_sym not in existing_exports and exp_sym != "default":
                        check8_defects.append(
                            AlignmentDefect(
                                kind=DefectKind.EXPORT_MISMATCH,
                                severity=DefectSeverity.ERROR,
                                message=f"Manifest module '{mod_name}' missing contract export '{exp_sym}'",
                                file_path=mod_file,
                                target=exp_sym,
                            )
                        )

        # 4. Navigation Link contracts
        for nav_contract in interface_manifest.navigation_links:
            source_rel = nav_contract.source_file.replace("\\", "/").lstrip("./")
            resolved_p, anchor_frag, err = AssetLinkResolver.resolve_target_path(ws_path, source_rel, nav_contract.target_href)
            if err == DefectKind.PATH_TRAVERSAL_VIOLATION.value:
                check8_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.PATH_TRAVERSAL_VIOLATION,
                        severity=DefectSeverity.ERROR,
                        message=f"Path traversal escape in manifest navigation link '{nav_contract.target_href}'",
                        file_path=source_rel,
                        target=nav_contract.target_href,
                    )
                )
            elif resolved_p is not None and not resolved_p.exists():
                check8_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.DEAD_LINK,
                        severity=DefectSeverity.ERROR,
                        message=f"Manifest navigation link '{nav_contract.target_href}' points to missing file",
                        file_path=source_rel,
                        target=nav_contract.target_href,
                    )
                )

                # 5. Form contracts
        for form_id, form_contract in interface_manifest.forms.items():
            owning_rel = form_contract.owning_file.replace("\\", "/").lstrip("./")
            doc = html_docs.get(owning_rel)
            if doc is None:
                check8_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.MISSING_PLANNED_FILE,
                        severity=DefectSeverity.ERROR,
                        message=f"Owning file '{owning_rel}' for form '{form_id}' not found",
                        file_path=owning_rel,
                        target=form_id,
                    )
                )
            elif form_id not in doc.ids and form_id not in doc.forms:
                check8_defects.append(
                    AlignmentDefect(
                        kind=DefectKind.MISSING_REQUIRED_CONTROL,
                        severity=DefectSeverity.ERROR,
                        message=f"Manifest required form '{form_id}' missing in '{owning_rel}'",
                        file_path=owning_rel,
                        target=form_id,
                    )
                )
            else:
                form_fields, f_line = doc.forms.get(form_id, ([], 1))
                doc_inputs = {inp[1] for inp in doc.inputs if inp[1]}.union({inp[0] for inp in doc.inputs if inp[0]})
                for req_field in form_contract.fields:
                    if req_field not in form_fields and req_field not in doc_inputs:
                        check8_defects.append(
                            AlignmentDefect(
                                kind=DefectKind.FORM_FIELD_MISMATCH,
                                severity=DefectSeverity.ERROR,
                                message=f"Form '{form_id}' missing contract required field '{req_field}'",
                                file_path=owning_rel,
                                line_number=f_line,
                                target=req_field,
                            )
                        )

        # 6. Asset Reference contracts
        for asset in interface_manifest.asset_references:
            if asset.required:
                src_rel = asset.source_file.replace("\\", "/").lstrip("./")
                resolved_p, _, err = AssetLinkResolver.resolve_target_path(ws_path, src_rel, asset.asset_path)
                if resolved_p is None or not resolved_p.exists():
                    check8_defects.append(
                        AlignmentDefect(
                            kind=DefectKind.BROKEN_REFERENCE,
                            severity=DefectSeverity.ERROR,
                            message=f"Manifest required asset '{asset.asset_path}' referenced by '{src_rel}' does not exist on disk",
                            file_path=src_rel,
                            target=asset.asset_path,
                        )
                    )

        check8_status = "FAIL" if check8_defects else "PASS"
        checks.append(
            AlignmentCheck(
                name="manifest_reconciliation",
                status=check8_status,
                message="All manifest elements, classes, modules, and links verified" if not check8_defects else f"Found {len(check8_defects)} manifest reconciliation defect(s)",
                defects=check8_defects,
            )
        )
    else:
        checks.append(
            AlignmentCheck(
                name="manifest_reconciliation",
                status="SKIPPED",
                message="No InterfaceManifest supplied; skipped",
            )
        )

    # -----------------------------------------------------------------------
    # Check 9: Anti-Placeholder Quality Gate (Rubric & Behavioral)
    # -----------------------------------------------------------------------
    check9_defects: List[AlignmentDefect] = []

    # Check HTML placeholders
    for rel_html, doc in html_docs.items():
        for msg, line in doc.placeholders:
            check9_defects.append(
                AlignmentDefect(
                    kind=DefectKind.PLACEHOLDER_DETECTED,
                    severity=DefectSeverity.ERROR,
                    message=msg,
                    file_path=rel_html,
                    line_number=line,
                )
            )

    # Check CSS placeholders
    for rel_css, doc in css_docs.items():
        if doc.is_empty_or_stub:
            check9_defects.append(
                AlignmentDefect(
                    kind=DefectKind.PLACEHOLDER_DETECTED,
                    severity=DefectSeverity.ERROR,
                    message="CSS file is empty or contains only trivial comments without style rules",
                    file_path=rel_css,
                )
            )
        for msg, line in doc.placeholders:
            check9_defects.append(
                AlignmentDefect(
                    kind=DefectKind.PLACEHOLDER_DETECTED,
                    severity=DefectSeverity.ERROR,
                    message=msg,
                    file_path=rel_css,
                    line_number=line,
                )
            )

    # Check JS placeholders
    for rel_js, doc in js_docs.items():
        if doc.is_empty_or_stub:
            check9_defects.append(
                AlignmentDefect(
                    kind=DefectKind.PLACEHOLDER_DETECTED,
                    severity=DefectSeverity.ERROR,
                    message="JavaScript file is empty or contains only trivial comments without logic",
                    file_path=rel_js,
                )
            )
        for msg, line in doc.placeholders:
            check9_defects.append(
                AlignmentDefect(
                    kind=DefectKind.PLACEHOLDER_DETECTED,
                    severity=DefectSeverity.ERROR,
                    message=msg,
                    file_path=rel_js,
                    line_number=line,
                )
            )

    check9_status = "FAIL" if check9_defects else "PASS"
    checks.append(
        AlignmentCheck(
            name="anti_placeholder_gate",
            status=check9_status,
            message="No placeholder tokens, TODOs, or empty stubs detected" if not check9_defects else f"Found {len(check9_defects)} placeholder defect(s)",
            defects=check9_defects,
        )
    )

    # -----------------------------------------------------------------------
        # -----------------------------------------------------------------------
    # Check 10: Interactive Controls & Accessibility Contract
    # -----------------------------------------------------------------------
    check10_defects: List[AlignmentDefect] = []
    has_a11y_mandate = False
    if quality_rubric and any(
        getattr(r, "rule_type", "") == "accessibility" or "accessibility" in getattr(r, "title", "").lower() or "accessibility" in getattr(r, "description", "").lower()
        for r in getattr(quality_rubric, "hard_requirements", [])
    ):
        has_a11y_mandate = True

    if has_a11y_mandate:
        for rel_html, doc in html_docs.items():
            for btn_id, acc_name, line in doc.buttons:
                if not acc_name.strip():
                    check10_defects.append(
                        AlignmentDefect(
                            kind=DefectKind.ACCESSIBILITY_VIOLATION,
                            severity=DefectSeverity.ERROR,
                            message=f"Interactive button (id='{btn_id or 'anonymous'}') lacks an accessible name or label",
                            file_path=rel_html,
                            line_number=line,
                            target=btn_id or "button",
                        )
                    )

            for inp_id, inp_name, inp_type, aria_or_ph, line in doc.inputs:
                if inp_type in ("hidden", "submit", "button", "reset", "image"):
                    continue
                has_label = (inp_id and inp_id in doc.labels) or bool(aria_or_ph.strip())
                if not has_label:
                    ident = inp_id or inp_name or f"type={inp_type}"
                    check10_defects.append(
                        AlignmentDefect(
                            kind=DefectKind.ACCESSIBILITY_VIOLATION,
                            severity=DefectSeverity.ERROR,
                            message=f"Form input '{ident}' lacks associated <label> or aria-label/placeholder",
                            file_path=rel_html,
                            line_number=line,
                            target=ident,
                        )
                    )

        check10_status = "FAIL" if check10_defects else "PASS"
        checks.append(
            AlignmentCheck(
                name="accessibility_and_controls",
                status=check10_status,
                message="All interactive controls and forms satisfy accessibility and label contracts" if not check10_defects else f"Found {len(check10_defects)} accessibility defect(s)",
                defects=check10_defects,
            )
        )
    else:
        checks.append(
            AlignmentCheck(
                name="accessibility_and_controls",
                status="SKIPPED",
                message="No accessibility requirements declared in contract; skipped",
            )
        )

    # -----------------------------------------------------------------------
    # Check 11: Responsive Design Contract
    # -----------------------------------------------------------------------
    check11_defects: List[AlignmentDefect] = []
    requires_responsive = False
    if quality_rubric and any("responsive" in r.title.lower() or "responsive" in r.description.lower() for r in quality_rubric.hard_requirements):
        requires_responsive = True

    if requires_responsive and css_docs:
        all_css_text = ""
        for rel_css in css_docs:
            p = ws_path / rel_css
            if p.exists():
                all_css_text += p.read_text(encoding="utf-8", errors="replace")

        has_media = "@media" in all_css_text.lower()
        has_responsive_container = any(k in all_css_text.lower() for k in ("flex-wrap", "grid-template-columns", "minmax("))
        if not (has_media or has_responsive_container):
            check11_defects.append(
                AlignmentDefect(
                    kind=DefectKind.RESPONSIVE_CONTRACT_VIOLATION,
                    severity=DefectSeverity.ERROR,
                    message="Project contract requires responsive layout, but no @media queries or responsive rules found in stylesheets",
                    file_path=list(css_docs.keys())[0] if css_docs else "styles.css",
                )
            )

    check11_status = "FAIL" if check11_defects else "PASS"
    checks.append(
        AlignmentCheck(
            name="responsive_design_contract",
            status=check11_status,
            message="Responsive layout requirements verified in stylesheets" if not check11_defects else "Responsive layout contract missing in stylesheets",
            defects=check11_defects,
        )
    )

    # Aggregate All Defects & Build Report
    # -----------------------------------------------------------------------
    for c in checks:
        all_defects.extend(c.defects)

    hard_errors = sum(1 for d in all_defects if d.severity == DefectSeverity.ERROR)
    warnings = sum(1 for d in all_defects if d.severity == DefectSeverity.WARNING)

    overall_status = "FAIL" if hard_errors > 0 else ("WARNING" if warnings > 0 else "PASS")

    # Record limitations
    if any(d.kind == DefectKind.DYNAMIC_SELECTOR_UNVERIFIED for d in all_defects):
        limitations.append("Dynamic DOM selectors detected; dynamic target evaluation bypassed")
    limitations.append("JavaScript syntax validation utilizes Node.js compiler checks when available, with heuristic balance fallback")

    report = AlignmentReport(
        status=overall_status,
        hard_error_count=hard_errors,
        warning_count=warnings,
        checks=checks,
        defects=all_defects,
        files_examined=examined_rel_files,
        limitations=limitations,
    )

    return report