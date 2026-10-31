# core/planning/requirement_types.py
"""
Typed Requirement Classification and Evidence Verification for HERMES 2.x.

Prevents naive file regex matchers from confusing:
- Libraries (e.g., 'Three.js', 'React.js', 'Chart.js') with local files to write.
- Runtimes (e.g., 'Node.js', 'npm', 'Python') with workspace deliverables.
- Remote documentation/spec URLs (e.g., 'https://.../GSLVmk3_CON.html') with workspace files.
"""

from __future__ import annotations

import re
import shutil
import sys
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from core.runtime_state.models import RequirementType


# Canonical lists of known libraries, runtimes, and tools
KNOWN_DEPENDENCIES: Set[str] = {
    "three.js", "three", "orbitcontrols", "react.js", "react", "vue.js", "vue",
    "angular.js", "angular", "svelte.js", "svelte", "next.js", "next",
    "nuxt.js", "nuxt", "express.js", "express", "d3.js", "d3", "chart.js",
    "babylon.js", "babylon", "anime.js", "gsap.js", "gsap", "moment.js",
    "lodash.js", "lodash", "axios.js", "axios", "electron.js", "electron",
    "tailwind", "tailwindcss", "bootstrap", "font-awesome", "fontawesome",
    "lucide", "lucide-icons", "phaser.js", "phaser", "pixi.js", "pixi",
}

KNOWN_RUNTIMES: Set[str] = {
    "node.js", "node", "nodejs", "npm", "npx", "yarn", "pnpm", "bun",
    "python", "python3", "pip", "pip3", "git", "bash", "powershell",
    "sh", "zsh", "cmd",
}

URL_REGEX = re.compile(r'https?://[^\s<>"\')]+', re.IGNORECASE)
FILE_TOKEN_REGEX = re.compile(r'`?([a-zA-Z0-9_\-/\\]+\.(?:html|css|json|jsx|js|py|md|txt|tsx|ts|sql|sh))\b`?', re.IGNORECASE)


def extract_urls(text: str) -> List[str]:
    """Extract all URLs from text."""
    if not text:
        return []
    return URL_REGEX.findall(text)


def extract_url_basenames(text: str) -> Set[str]:
    """Extract base filenames contained inside URLs (e.g. 'GSLVmk3_CON.html')."""
    urls = extract_urls(text)
    basenames = set()
    for u in urls:
        path_part = u.split("?")[0].split("#")[0].rstrip("/")
        if "/" in path_part:
            base = path_part.split("/")[-1].lower()
            if "." in base:
                basenames.add(base)
    return basenames


def strip_urls(text: str) -> str:
    """Remove URLs from text so path segments are not extracted as local deliverables."""
    if not text:
        return ""
    return URL_REGEX.sub(" ", text)


def classify_requirement_token(token: str, url_basenames: Optional[Set[str]] = None) -> RequirementType:
    """
    Classify a candidate requirement token into its strong architectural type.
    """
    cleaned = token.strip().lower().lstrip("`'\"").rstrip("`'\"")
    base_name = cleaned.replace("\\", "/").split("/")[-1]

    if url_basenames and base_name in url_basenames:
        return RequirementType.SOURCE_REFERENCE

    if cleaned.startswith(("http://", "https://")):
        return RequirementType.SOURCE_REFERENCE

    if base_name in KNOWN_RUNTIMES or cleaned in KNOWN_RUNTIMES:
        return RequirementType.RUNTIME

    if base_name in KNOWN_DEPENDENCIES or cleaned in KNOWN_DEPENDENCIES:
        return RequirementType.DEPENDENCY

    # Check for library naming patterns like 'xyz.js' where xyz is a known package
    if base_name.endswith(".js"):
        root = base_name[:-3]
        if root in KNOWN_DEPENDENCIES or root in KNOWN_RUNTIMES:
            return RequirementType.DEPENDENCY if root in KNOWN_DEPENDENCIES else RequirementType.RUNTIME

    return RequirementType.OUTPUT_ARTIFACT


def extract_typed_requirements(
    prompt: str,
    written_files: Optional[Iterable[str]] = None,
) -> Dict[RequirementType, List[str]]:
    """
    Partition prompt requirements into strong typed categories.
    """
    res: Dict[RequirementType, List[str]] = {
        RequirementType.OUTPUT_ARTIFACT: [],
        RequirementType.DEPENDENCY: [],
        RequirementType.RUNTIME: [],
        RequirementType.SOURCE_REFERENCE: [],
        RequirementType.BEHAVIORAL: [],
        RequirementType.ACCEPTANCE_TEST: [],
    }

    if not prompt:
        return res

    # 1. Source reference URLs
    urls = extract_urls(prompt)
    res[RequirementType.SOURCE_REFERENCE].extend(urls)
    url_basenames = extract_url_basenames(prompt)

    # 2. Text without URLs for local candidate matching
    clean_text = strip_urls(prompt)

    # 3. Candidate files
    matches = FILE_TOKEN_REGEX.findall(clean_text)
    seen = set()
    for raw in matches:
        norm = raw.replace("\\", "/").lstrip("./").strip()
        if not norm or norm.lower() in seen:
            continue
        seen.add(norm.lower())

        rtype = classify_requirement_token(norm, url_basenames)
        res[rtype].append(norm)

    # 4. Check for known runtimes and dependencies mentioned by name without extensions
    lower_text = clean_text.lower()
    for rt in KNOWN_RUNTIMES:
        if re.search(r'\b' + re.escape(rt) + r'\b', lower_text):
            if rt not in [x.lower() for x in res[RequirementType.RUNTIME]]:
                res[RequirementType.RUNTIME].append(rt)

    for dep in KNOWN_DEPENDENCIES:
        if re.search(r'\b' + re.escape(dep) + r'\b', lower_text):
            if dep not in [x.lower() for x in res[RequirementType.DEPENDENCY]]:
                res[RequirementType.DEPENDENCY].append(dep)

    # 5. Written files augmentation if candidate output artifacts are empty
    if not res[RequirementType.OUTPUT_ARTIFACT]:
        if written_files:
            for wf in written_files:
                norm_wf = wf.replace("\\", "/").lstrip("./").strip()
                if classify_requirement_token(norm_wf, url_basenames) == RequirementType.OUTPUT_ARTIFACT:
                    if norm_wf not in res[RequirementType.OUTPUT_ARTIFACT]:
                        res[RequirementType.OUTPUT_ARTIFACT].append(norm_wf)

    return res


def extract_target_artifacts(
    prompt: str,
    written_files: Optional[Iterable[str]] = None,
) -> List[str]:
    """
    Authoritative list of expected local workspace files.
    Guaranteed clean of libraries, runtimes, and reference URLs.
    """
    typed = extract_typed_requirements(prompt, written_files)
    artifacts = typed[RequirementType.OUTPUT_ARTIFACT]
    if not artifacts:
        # Fallback heuristic: if written_files present, use non-dependency written files
        if written_files:
            clean_written = [
                f for f in written_files
                if classify_requirement_token(f) == RequirementType.OUTPUT_ARTIFACT
            ]
            if clean_written:
                return clean_written
        # Default fallback for websites / general projects
        if any(kw in prompt.lower() for kw in ("website", "html", "webgl", "landing page", "frontend")):
            return ["index.html"]
    return artifacts


def verify_dependency_evidence(
    dependency: str,
    workspace_root: Path,
) -> Tuple[bool, str]:
    """
    Verify evidence of a required dependency in the workspace.
    Checks:
    1. HTML script tags / CDN links / import maps in HTML files.
    2. package.json dependencies / devDependencies.
    3. Python requirements.txt or import statements.
    """
    dep_lower = dependency.lower().replace(".js", "").strip()

    if not workspace_root.exists():
        return False, f"Workspace {workspace_root} does not exist"

    # 1. Check HTML files for CDN script, import map, or local module
    for html_file in workspace_root.glob("*.html"):
        try:
            content = html_file.read_text(encoding="utf-8", errors="replace").lower()
            if dep_lower in content:
                # Evidence confirmed in HTML
                return True, f"Found '{dependency}' referenced in {html_file.name}"
        except Exception:
            pass

    # 2. Check package.json
    pkg_json = workspace_root / "package.json"
    if pkg_json.exists():
        try:
            content = pkg_json.read_text(encoding="utf-8", errors="replace").lower()
            if dep_lower in content:
                return True, f"Found '{dependency}' in package.json"
        except Exception:
            pass

    # 3. Check JS / TS source files for import / require
    for js_file in list(workspace_root.glob("*.js")) + list(workspace_root.glob("src/**/*.js")):
        try:
            content = js_file.read_text(encoding="utf-8", errors="replace").lower()
            if dep_lower in content or f"from '{dep_lower}'" in content or f'from "{dep_lower}"' in content:
                return True, f"Found '{dependency}' imported in {js_file.name}"
        except Exception:
            pass

    return False, f"No evidence of dependency '{dependency}' found in HTML, package.json, or source scripts."


def verify_runtime_evidence(runtime: str) -> Tuple[bool, str]:
    """
    Verify that a required runtime (e.g. 'Node.js', 'Python') is available.
    """
    rt_lower = runtime.lower().replace(".js", "").strip()
    if rt_lower in ("node", "nodejs", "npm", "npx"):
        exe = shutil.which("node") or shutil.which("node.exe")
        if exe:
            return True, f"Node.js runtime available at {exe}"
        return False, "Node.js executable not found on PATH"

    if rt_lower in ("python", "python3", "pip"):
        exe = sys.executable or shutil.which("python")
        if exe:
            return True, f"Python runtime available at {exe}"
        return False, "Python executable not found"

    # General executable lookup
    exe = shutil.which(rt_lower)
    if exe:
        return True, f"Runtime tool '{runtime}' available at {exe}"
    return False, f"Runtime tool '{runtime}' not found on PATH"
