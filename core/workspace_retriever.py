# core/workspace_retriever.py
"""
Multi-Signal Workspace Retrieval Engine for HERMES vNext (Phase 7).
Ranks relevant files and symbols using user mentions, filename matches,
AST symbol matches, dependency graph expansion, and test pairings.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple

from loguru import logger
from core.workspace_indexer import WorkspaceIndexStore, DB_PATH


@dataclass
class RetrievedFile:
    rel_path: str
    score: float
    reasons: List[str] = field(default_factory=list)
    symbols: List[str] = field(default_factory=list)
    is_test_file: bool = False
    is_dependency: bool = False


class WorkspaceRetriever:
    """
    Deterministic multi-signal retriever across the persistent SQLite index.
    """

    def __init__(self, store: Optional[WorkspaceIndexStore] = None):
        self.store = store or WorkspaceIndexStore()

    def retrieve_relevant_files(
        self,
        workspace_root: str,
        query: str,
        max_files: int = 5,
        expand_dependencies: bool = True,
        include_tests: bool = True
    ) -> List[RetrievedFile]:
        """
        Rank and retrieve files relevant to the query.
        Signals:
          1. Explicit User Mentions (10.0)
          2. Filename Token Matches (4.0)
          3. AST Symbol Matches (3.0)
          4. Test File Pairings (3.5)
          5. Dependency Graph Expansion (2.0)
        """
        ws_id = str(Path(workspace_root).resolve())
        query_lower = query.lower()
        words = set(re.findall(r"[a-zA-Z0-9_\-]+", query_lower))
        stop_words = {"the", "and", "for", "with", "from", "file", "code", "this", "that", "what", "where", "how"}
        keywords = {w for w in words if len(w) > 2 and w not in stop_words}

        scores: Dict[str, float] = {}
        reasons: Dict[str, List[str]] = {}
        symbols_map: Dict[str, List[str]] = {}

        with self.store._get_conn() as conn:
            # 1. Fetch all indexed files
            files = conn.execute("SELECT rel_path, extension, language, mtime FROM files WHERE workspace_id = ?", (ws_id,)).fetchall()
            if not files:
                return []

            # 2. Fetch all symbols
            symbols = conn.execute("SELECT rel_path, symbol_name, symbol_type FROM symbols WHERE workspace_id = ?", (ws_id,)).fetchall()
            for s in symbols:
                rp = s["rel_path"].replace("\\", "/")
                if rp not in symbols_map:
                    symbols_map[rp] = []
                symbols_map[rp].append(s["symbol_name"])

            # 3. Fetch all imports
            imports = conn.execute("SELECT rel_path, imported_module FROM imports WHERE workspace_id = ?", (ws_id,)).fetchall()
            imports_by_file: Dict[str, Set[str]] = {}
            for imp in imports:
                rp = imp["rel_path"].replace("\\", "/")
                if rp not in imports_by_file:
                    imports_by_file[rp] = set()
                imports_by_file[rp].add(imp["imported_module"].lower())

        # Evaluate individual files
        file_paths = [f["rel_path"].replace("\\", "/") for f in files]
        for rp in file_paths:
            rp_lower = rp.lower()
            fname = Path(rp).name.lower()
            fname_stem = Path(rp).stem.lower()
            current_score = 0.0
            cur_reasons = []

            # Signal 1: Explicit Mention in Query
            generic_stems = {"service", "test", "tests", "file", "module", "component", "impl", "util", "utils", "helper", "base", "common", "core", "lib", "main", "index"}
            if rp_lower in query_lower or fname in query_lower or (fname_stem in words and fname_stem not in generic_stems and len(fname_stem) > 3):
                current_score += 10.0
                cur_reasons.append("explicit_user_mention")

            # Signal 2: Filename & Path Keyword Matches
            for kw in keywords:
                if kw in fname or (len(fname_stem) > 3 and fname_stem in kw) or kw.startswith(fname_stem) or fname_stem.startswith(kw) or (len(kw) > 4 and kw[:4] in fname):
                    current_score += 4.0
                    cur_reasons.append(f"filename_match_{kw}")
                elif kw in rp_lower:
                    current_score += 2.0
                    cur_reasons.append(f"path_match_{kw}")

            # Signal 3: AST Symbol Matches
            file_symbols = symbols_map.get(rp, [])
            matched_sym_kws = set()
            for sym in file_symbols:
                sym_lower = sym.lower()
                for kw in keywords:
                    if (kw in sym_lower or sym_lower.startswith(kw) or (len(kw) > 4 and kw[:4] in sym_lower)) and kw not in matched_sym_kws:
                        current_score += 3.0
                        cur_reasons.append(f"symbol_match_{sym}:{kw}")
                        matched_sym_kws.add(kw)

            # Signal 3b: Domain Configuration Files Match
            if (rp_lower.startswith("config/") or rp_lower.endswith((".yaml", ".yml", ".json", ".toml", ".ini", ".conf"))) and any(kw in fname_stem or fname_stem in kw for kw in keywords):
                if any(term in query_lower for term in ["config", "timeout", "production", "default", "setting", "env", "yaml"]):
                    current_score += 4.5
                    cur_reasons.append("domain_config_match")

            # Signal 3c: Multi-Keyword Alignment Density Boost
            cur_matched_kws = {
                r.split("_")[-1].split(":")[0]
                for r in cur_reasons
                if any(r.startswith(p) for p in ["filename_match_", "path_match_", "symbol_match_"])
            }
            if len(cur_matched_kws) >= 2:
                current_score += 2.0 * len(cur_matched_kws)
                cur_reasons.append(f"keyword_density_boost_x{len(cur_matched_kws)}")

            if current_score > 0:
                scores[rp] = current_score
                reasons[rp] = cur_reasons

        # Helper for module path matching
        def matches_module(mod_str: str, file_rel: str) -> bool:
            mod_norm = mod_str.strip().lower()
            file_norm = file_rel.replace("\\", "/").lower()
            file_stem = Path(file_norm).stem
            file_no_ext = file_norm.rsplit(".", 1)[0]
            mod_as_path = mod_norm.replace(".", "/")

            # Fully qualified module e.g. "src.auth.service" -> matches "src/auth/service.py"
            if file_no_ext == mod_as_path or file_no_ext.endswith(f"/{mod_as_path}") or file_norm == f"{mod_as_path}.py":
                return True

            # Simple module name without dots e.g. "token_service"
            if "." not in mod_norm and file_norm.endswith((".py", ".ts", ".js")):
                if file_stem == mod_norm:
                    return True

            return False

        # Sort candidate files by score
        sorted_candidates = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_candidates = [rp for rp, _ in sorted_candidates[:max(12, max_files * 2)]]

        # Signal 4: Dependency Graph Expansion (callees + callers, up to 2 hops)
        if expand_dependencies and top_candidates:
            expanded_deps: Set[str] = set()
            for top_rp in list(top_candidates):
                top_score = scores.get(top_rp, 0.0)
                top_pkg = Path(top_rp).parent.as_posix().lower()
                imported_mods = imports_by_file.get(top_rp, set())
                for other_rp in file_paths:
                    if any(matches_module(m, other_rp) for m in imported_mods):
                        other_pkg = Path(other_rp).parent.as_posix().lower()
                        same_pkg_boost = 2.0 if top_pkg == other_pkg else 0.0
                        dep_boost = (10.0 if top_score >= 20.0 else (6.0 if top_score >= 15.0 else 3.0)) + same_pkg_boost
                        dep_reason = f"imported_by_{Path(top_rp).name}"
                        if other_rp not in scores:
                            scores[other_rp] = dep_boost
                            reasons[other_rp] = [dep_reason]
                        elif dep_reason not in reasons.get(other_rp, []):
                            scores[other_rp] += dep_boost
                            reasons[other_rp].append(dep_reason)
                        expanded_deps.add(other_rp)

            # 2nd hop for top dependencies (callees)
            for dep_rp in list(expanded_deps)[:8]:
                dep_imported = imports_by_file.get(dep_rp, set())
                for other_rp in file_paths:
                    if any(matches_module(m, other_rp) for m in dep_imported):
                        dep_reason = f"transitive_dep_via_{Path(dep_rp).name}"
                        if other_rp not in scores:
                            scores[other_rp] = 3.5
                            reasons[other_rp] = [dep_reason]
                        elif dep_reason not in reasons.get(other_rp, []):
                            scores[other_rp] += 3.5
                            reasons[other_rp].append(dep_reason)

            # Caller expansion: files that import top candidates
            for top_rp in list(top_candidates[:10]):
                for caller_rp in file_paths:
                    caller_mods = imports_by_file.get(caller_rp, set())
                    if any(matches_module(m, top_rp) for m in caller_mods):
                        caller_rp_lower = caller_rp.replace("\\", "/").lower()
                        if any(kw in caller_rp_lower for kw in keywords):
                            caller_reason = f"caller_of_{Path(top_rp).name}"
                            if caller_rp not in scores:
                                scores[caller_rp] = 4.0
                                reasons[caller_rp] = [caller_reason]
                            elif caller_reason not in reasons.get(caller_rp, []):
                                scores[caller_rp] += 4.0
                                reasons[caller_rp].append(caller_reason)

        # Signal 5: Test File Pairing (e.g. auth/service.py <-> tests/auth/test_service.py)
        if include_tests and top_candidates:
            for top_rp in list(top_candidates[:6]):
                stem = Path(top_rp).stem.lower()
                pkg = Path(top_rp).parent.name.lower()
                for other_rp in file_paths:
                    other_posix = other_rp.replace("\\", "/").lower()
                    other_stem = Path(other_rp).stem.lower()
                    other_pkg = Path(other_rp).parent.name.lower()
                    if "test" in other_posix:
                        if other_stem in (f"test_{stem}", f"{stem}_test") or f"test_{stem}" in other_stem or (stem.replace("_service", "") in other_stem and (pkg in other_posix or other_pkg == pkg)):
                            is_same_pkg = (pkg in other_posix or other_pkg == pkg or not pkg)
                            test_boost = 4.5 if is_same_pkg else 1.0
                            test_reason = f"test_for_{Path(top_rp).name}"
                            if other_rp not in scores:
                                scores[other_rp] = test_boost
                                reasons[other_rp] = [test_reason]
                            elif test_reason not in reasons.get(other_rp, []):
                                scores[other_rp] += test_boost
                                reasons[other_rp].append(test_reason)

        # Final ranked results
        final_sorted = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:max_files]
        results = []
        for rp, score in final_sorted:
            fname = Path(rp).name.lower()
            is_test = "test" in fname
            is_dep = any("imported_by" in r or "transitive_dep" in r for r in reasons.get(rp, []))
            results.append(RetrievedFile(
                rel_path=rp,
                score=round(score, 2),
                reasons=reasons.get(rp, []),
                symbols=symbols_map.get(rp, [])[:6],
                is_test_file=is_test,
                is_dependency=is_dep
            ))

        return results

    def assemble_context(self, workspace_root: str, query: str, max_files: int = 5) -> str:
        """Format retrieved files and symbol signatures into structured prompt context."""
        retrieved = self.retrieve_relevant_files(workspace_root, query, max_files=max_files)
        if not retrieved:
            return ""

        lines = [f"Relevant Workspace Files ({len(retrieved)} retrieved):"]
        for rf in retrieved:
            flag = " [TEST]" if rf.is_test_file else (" [DEP]" if rf.is_dependency else "")
            sym_str = f" | Symbols: {', '.join(rf.symbols)}" if rf.symbols else ""
            lines.append(f" - {rf.rel_path}{flag} (relevance: {rf.score}){sym_str}")

        return "\n".join(lines)


# Global singleton
workspace_retriever = WorkspaceRetriever()
