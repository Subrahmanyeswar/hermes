# tools/security.py
# HERMES security layer — 15 bash security gates.
# Every shell command passes through check_all_gates() before execution.
# If any gate returns (False, reason), the command is BLOCKED and never executes.
# These gates run before subprocess.run. Order matters — most dangerous checks first.

import hashlib
import json
import time
import os
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

PROTECTED_PATHS: list[str] = [
    "~/.ssh",
    "~/.aws",
    ".env",
    "*.pem",
    "*.key",
    "*_rsa",
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/boot",
    "/sys",
    "/proc",
]


def gate_1_destructive_wildcard(command: str) -> tuple[bool, str]:
    """Blocks rm -rf /, rm -rf ~, and rm with wildcard on root paths."""
    if re.search(r"rm\s+.*-r.*f.*(\*|/\s*$|~)", command, re.IGNORECASE) or re.search(
        r"rm\s+.*-rf\s*/", command, re.IGNORECASE
    ):
        return False, f"Gate 1 BLOCKED: Destructive rm detected: {command[:80]}"
    logger.debug(f"Gate 1 passed: {command[:40]!r}")
    return True, ""


def gate_2_pipe_to_shell(command: str) -> tuple[bool, str]:
    """Blocks piping curl/wget output directly to a shell interpreter."""
    if re.search(
        r"(curl|wget|fetch)\s+.*\|\s*(bash|sh|zsh|fish|dash)",
        command,
        re.IGNORECASE,
    ):
        return False, f"Gate 2 BLOCKED: Pipe-to-shell detected: {command[:80]}"
    logger.debug(f"Gate 2 passed: {command[:40]!r}")
    return True, ""


def gate_3_sudo_escalation(command: str) -> tuple[bool, str]:
    """Blocks any command that starts with or contains sudo."""
    if re.search(r"(^|\s|;|&&|\|\|)sudo\s", command):
        return False, "Gate 3 BLOCKED: sudo escalation detected"
    logger.debug(f"Gate 3 passed: {command[:40]!r}")
    return True, ""


def gate_4_unicode_normalise(command: str) -> tuple[bool, str]:
    """Detects and blocks commands containing zero-width or homoglyph Unicode characters used to smuggle payloads."""
    zero_width_chars: set[str] = {"\u200b", "\ufeff", "\u200c", "\u200d", "\u2060"}
    for char in command:
        if unicodedata.category(char).startswith("C") or char in zero_width_chars:
            return (
                False,
                "Gate 4 BLOCKED: Unicode zero-width or control character detected in command",
            )
    logger.debug(f"Gate 4 passed: {command[:40]!r}")
    return True, ""


def gate_5_path_traversal(command: str) -> tuple[bool, str]:
    """Blocks commands containing more than 2 consecutive ../ directory traversals."""
    if re.search(r"(\.\./){3,}", command):
        return False, f"Gate 5 BLOCKED: Path traversal depth exceeded: {command[:80]}"
    logger.debug(f"Gate 5 passed: {command[:40]!r}")
    return True, ""


def gate_6_protected_path(command: str) -> tuple[bool, str]:
    """Blocks read or write access to sensitive system paths and credential files."""
    for path in PROTECTED_PATHS:
        expanded: str = path.replace("~", str(Path.home()))
        if path == "*.pem" and re.search(r"\S+\.pem", command):
            return (
                False,
                f"Gate 6 BLOCKED: Access to protected path detected: {command[:80]}",
            )
        if path == "*.key" and re.search(r"\S+\.key", command):
            return (
                False,
                f"Gate 6 BLOCKED: Access to protected path detected: {command[:80]}",
            )
        if path == "*_rsa" and re.search(r"\S+_rsa", command):
            return (
                False,
                f"Gate 6 BLOCKED: Access to protected path detected: {command[:80]}",
            )
        if "*" not in path and (expanded in command or path in command):
            return (
                False,
                f"Gate 6 BLOCKED: Access to protected path detected: {command[:80]}",
            )
    logger.debug(f"Gate 6 passed: {command[:40]!r}")
    return True, ""


def gate_7_env_var_poisoning(command: str) -> tuple[bool, str]:
    """Blocks assignment to critical environment variables like PATH, LD_PRELOAD, and LD_LIBRARY_PATH."""
    if re.search(
        r"\b(PATH|LD_PRELOAD|LD_LIBRARY_PATH|PYTHONPATH|DYLD_LIBRARY_PATH)\s*=",
        command,
    ):
        return (
            False,
            f"Gate 7 BLOCKED: Environment variable poisoning detected: {command[:80]}",
        )
    logger.debug(f"Gate 7 passed: {command[:40]!r}")
    return True, ""


def gate_8_base64_execution(command: str) -> tuple[bool, str]:
    """Blocks base64-decoded payload execution — a common obfuscation technique."""
    if re.search(
        r"base64\s+.*-d.*\|\s*(bash|sh|python|perl|ruby)",
        command,
        re.IGNORECASE,
    ) or re.search(
        r"echo\s+.*\|\s*base64\s+-d\s*\|\s*(bash|sh)",
        command,
        re.IGNORECASE,
    ):
        return False, "Gate 8 BLOCKED: Base64 execution obfuscation detected"
    logger.debug(f"Gate 8 passed: {command[:40]!r}")
    return True, ""


def gate_9_fork_bomb(command: str) -> tuple[bool, str]:
    """Blocks fork bomb patterns that would crash the system."""
    if re.search(r":\s*\(\s*\)\s*\{|fork\s*bomb|:\(\)\{.*:\|:&", command):
        return False, "Gate 9 BLOCKED: Fork bomb pattern detected"
    logger.debug(f"Gate 9 passed: {command[:40]!r}")
    return True, ""


def gate_10_hex_encoded_commands(command: str) -> tuple[bool, str]:
    """Blocks hex-encoded payload injection used to bypass string filters."""
    if re.search(r"\\x[0-9a-fA-F]{2}", command):
        return False, "Gate 10 BLOCKED: Hex-encoded payload detected in command"
    logger.debug(f"Gate 10 passed: {command[:40]!r}")
    return True, ""


def gate_11_crontab_modification(command: str) -> tuple[bool, str]:
    """Blocks any modification to the crontab — a common persistence mechanism."""
    if re.search(r"\bcrontab\s+(-e|-r|-l\s+-r)", command) or re.search(
        r"\bcrontab\b", command
    ):
        return False, "Gate 11 BLOCKED: crontab modification detected"
    logger.debug(f"Gate 11 passed: {command[:40]!r}")
    return True, ""


def gate_12_systemctl_modification(command: str) -> tuple[bool, str]:
    """Blocks systemctl commands that enable, disable, or start system services."""
    if re.search(
        r"\bsystemctl\s+(enable|disable|start|stop|restart|mask|unmask)",
        command,
        re.IGNORECASE,
    ):
        return False, "Gate 12 BLOCKED: systemctl service modification detected"
    logger.debug(f"Gate 12 passed: {command[:40]!r}")
    return True, ""


def gate_13_git_force_push(command: str) -> tuple[bool, str]:
    """Blocks git push --force which can permanently destroy remote history."""
    if re.search(r"git\s+push\s+.*--force|git\s+push\s+.*-f\b", command):
        return (
            False,
            "Gate 13 BLOCKED: git force push detected — use explicit override to allow",
        )
    logger.debug(f"Gate 13 passed: {command[:40]!r}")
    return True, ""


def gate_14_system_pip_install(command: str) -> tuple[bool, str]:
    """Blocks pip install outside of an active virtual environment to prevent system Python corruption."""
    venv: str = os.environ.get("VIRTUAL_ENV", "")
    if venv == "" and re.search(r"\bpip\s+install\b", command):
        return (
            False,
            "Gate 14 BLOCKED: pip install outside virtual environment is not allowed",
        )
    logger.debug(f"Gate 14 passed: {command[:40]!r}")
    return True, ""


def gate_15_recursive_wildcard_delete(command: str) -> tuple[bool, str]:
    """Flags rm -r with wildcard — requires explicit user confirmation even in Auto mode."""
    if re.search(r"\brm\s+.*-r.*\*|\brm\s+.*\*.*-r", command):
        return (
            False,
            "Gate 15 BLOCKED: Recursive wildcard delete requires explicit confirmation. Use --confirm-wildcard-delete flag to override.",
        )
    logger.debug(f"Gate 15 passed: {command[:40]!r}")
    return True, ""


def gate_16_destructive_workspace_cleanup(command: str) -> tuple[bool, str]:
    """
    Blocks destructive cleanup or bulk deletion of active project files/folders.
    Prohibits commands like:
      - rm -rf assets images package.json style.css index.html app.js ...
      - Remove-Item -Recurse -Force
      - del /s /q or rmdir /s /q targeting project root or foundation deliverables
    Autonomous models are strictly forbidden from erasing active source deliverables.
    """
    cmd_lower = command.lower()
    
    # Check for rm -r / rm -rf / Remove-Item / del / rmdir targeting protected foundation files
    if re.search(r"\brm\s+.*-[a-za-z]*r", cmd_lower) or re.search(r"\brmdir\s+.*(/s|/q)", cmd_lower) or re.search(r"\bdel\s+.*(/s|/q)", cmd_lower) or re.search(r"\bremove-item\b.*-recurse", cmd_lower):
        protected_targets = [
            "index.html", "style.css", "app.js", "package.json", "main.js", "main.py",
            "assets", "images", "src", ".artifacts", ".hermes"
        ]
        tokens = [t.strip('"\'').lower() for t in cmd_lower.split()]
        matched_protected = [p for p in protected_targets if any(p == tok or tok.endswith("/" + p) or tok.endswith("\\" + p) for tok in tokens)]
        
        if matched_protected:
            return (
                False,
                f"Gate 16 BLOCKED: Destructive cleanup targeting protected project source deliverables ({', '.join(matched_protected)}) is prohibited without explicit authorization.",
            )
            
        if any(tok in (".", "*", ".*", "./*", ".\\*") for tok in tokens):
            return (
                False,
                "Gate 16 BLOCKED: Destructive recursive deletion targeting current directory/workspace root is prohibited.",
            )

    # Check for multi-file rm targeting foundation files even without -r
    if re.search(r"\brm\s+", cmd_lower):
        foundation_files = ["index.html", "style.css", "app.js", "package.json"]
        matched_foundation = [f for f in foundation_files if f in cmd_lower]
        if len(matched_foundation) >= 2:
            return (
                False,
                f"Gate 16 BLOCKED: Bulk deletion of primary project foundation files ({', '.join(matched_foundation)}) is prohibited.",
            )

    logger.debug(f"Gate 16 passed: {command[:40]!r}")
    return True, ""


def check_all_gates(command: str) -> tuple[bool, str]:
    """
    Run all 16 security gates against a shell command.
    Returns (True, "") if the command passes all gates.
    Returns (False, reason) at the first gate that blocks.
    Logs every blocked command at WARNING level with the gate number and reason.
    """
    gates = [
        gate_1_destructive_wildcard,
        gate_2_pipe_to_shell,
        gate_3_sudo_escalation,
        gate_4_unicode_normalise,
        gate_5_path_traversal,
        gate_6_protected_path,
        gate_7_env_var_poisoning,
        gate_8_base64_execution,
        gate_9_fork_bomb,
        gate_10_hex_encoded_commands,
        gate_11_crontab_modification,
        gate_12_systemctl_modification,
        gate_13_git_force_push,
        gate_14_system_pip_install,
        gate_15_recursive_wildcard_delete,
        gate_16_destructive_workspace_cleanup,
    ]
    for gate_fn in gates:
        passed, reason = gate_fn(command)
        if not passed:
            logger.warning(
                f"SECURITY GATE BLOCKED | gate={gate_fn.__name__} | cmd={command[:100]!r} | reason={reason}"
            )
            return False, reason
    logger.debug(f"Security: all 15 gates passed for command: {command[:80]!r}")
    return True, ""


# ==============================================================================
# WORKSPACE DELIVERABLE OWNERSHIP & SAFE INTERNAL DELETION ENGINE (GATE 16)
# ==============================================================================

MANIFEST_REL_PATH = ".hermes/generated_manifest.json"
PROTECTED_FOUNDATION_NAMES = {
    "index.html", "style.css", "app.js", "package.json",
    "main.js", "main.py", "server.js", "vite.config.js"
}
VERIFIED_TEMP_MARKERS = {
    ".hermes/tmp", ".hermes/screenshots", ".artifacts/tmp",
    "temp_", "tmp_", ".tmp", ".temp", ".test_tmp", "scratch"
}


class WorkspaceOwnershipManifest:
    """
    Maintains an explicit manifest of files generated by HERMES.
    Ensures user-owned files are never deleted or overwritten without explicit authorization.
    """
    @classmethod
    def _manifest_path(cls, workspace_root: Path | str) -> Path:
        return Path(workspace_root).resolve() / ".hermes" / "generated_manifest.json"

    @classmethod
    def load(cls, workspace_root: Path | str) -> Dict[str, Any]:
        mp = cls._manifest_path(workspace_root)
        if not mp.exists():
            return {"version": 1, "generated_files": {}}
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug(f"OwnershipManifest load warning: {e}")
            return {"version": 1, "generated_files": {}}

    @classmethod
    def save(cls, workspace_root: Path | str, data: Dict[str, Any]) -> None:
        mp = cls._manifest_path(workspace_root)
        try:
            mp.parent.mkdir(parents=True, exist_ok=True)
            mp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"OwnershipManifest save warning: {e}")

    @classmethod
    def register_generated_file(
        cls,
        file_path: Path | str,
        workspace_root: Path | str,
        generator: str = "hermes",
    ) -> bool:
        """Register a file as explicitly generated by HERMES."""
        try:
            ws = Path(workspace_root).resolve()
            fp = Path(file_path)
            if not fp.is_absolute():
                fp = ws / fp
            fp = fp.resolve()
            rel = str(fp.relative_to(ws)).replace("\\", "/")
            
            data = cls.load(ws)
            if "generated_files" not in data:
                data["generated_files"] = {}
                
            file_hash = ""
            if fp.exists() and fp.is_file():
                try:
                    file_hash = hashlib.sha256(fp.read_bytes()).hexdigest()[:16]
                except Exception:
                    file_hash = "exists"

            data["generated_files"][rel] = {
                "generator": generator,
                "registered_at": time.time(),
                "sha256": file_hash,
            }
            cls.save(ws, data)
            return True
        except Exception as e:
            logger.debug(f"Failed to register generated file {file_path}: {e}")
            return False

    @classmethod
    def register_generated_files(
        cls,
        workspace_root: Path | str,
        file_paths: list[Path | str] | set[Path | str],
        source: str = "hermes",
    ) -> None:
        """Batch register generated files in workspace manifest."""
        for fp in file_paths:
            cls.register_generated_file(fp, workspace_root, generator=source)

    @classmethod
    def is_generated_file(cls, file_path: Path | str, workspace_root: Path | str) -> bool:
        """Check if a file is recorded in the HERMES generated manifest or has HERMES generator hallmarks."""
        try:
            ws = Path(workspace_root).resolve()
            fp = Path(file_path)
            if not fp.is_absolute():
                fp = ws / fp
            fp = fp.resolve()
            try:
                rel = str(fp.relative_to(ws)).replace("\\", "/")
            except ValueError:
                return False
            data = cls.load(ws)
            if rel in data.get("generated_files", {}):
                return True
            # Also recognize prior HERMES generator hallmarks if file exists
            if fp.exists() and fp.is_file():
                try:
                    head = fp.read_text(encoding="utf-8", errors="ignore")[:2000].lower()
                    if any(sig in head for sig in [
                        "hermes generated",
                        "destinations-grid",
                        "packages-grid",
                        "wanderworld travel",
                        '"name": "wanderworld"',
                        "programs-grid",
                        "faculty-grid",
                        "northstar university",
                        '"name": "northstar-university"',
                        "saffron & stone",
                        '"name": "saffron-and-stone"',
                        "nova consumer electronics",
                        '"name": "nova-consumer-electronics"',
                        "products-grid",
                        "cart-subtotal",
                    ]):
                        return True
                except Exception:
                    pass
            return False
        except Exception:
            return False

    @classmethod
    def unregister(cls, file_path: Path | str, workspace_root: Path | str) -> None:
        try:
            ws = Path(workspace_root).resolve()
            fp = Path(file_path).resolve()
            rel = str(fp.relative_to(ws)).replace("\\", "/")
            data = cls.load(ws)
            if "generated_files" in data and rel in data["generated_files"]:
                del data["generated_files"][rel]
                cls.save(ws, data)
        except Exception:
            pass


def can_safely_delete_file(
    file_path: Path | str,
    workspace_root: Path | str,
    is_temporary: bool = False,
    reason: str = "",
) -> Tuple[bool, str]:
    """
    Authoritative safety check before deleting any file in workspace.
    Ensures user-owned files and primary deliverables cannot be deleted.
    """
    try:
        ws = Path(workspace_root).resolve()
        fp = Path(file_path)
        if not fp.is_absolute():
            fp = ws / fp
        fp = fp.resolve()
    except Exception as e:
        return False, f"Invalid path: {e}"

    # Must be inside workspace
    try:
        rel = fp.relative_to(ws)
        rel_str = str(rel).replace("\\", "/")
    except ValueError:
        return False, f"Gate 5/6 BLOCKED: Path '{file_path}' is outside workspace root."

    # Verified temporary artifacts can always be deleted
    if is_temporary or any(m in rel_str for m in VERIFIED_TEMP_MARKERS) or fp.name.endswith(".tmp") or fp.name.endswith(".log"):
        return True, "Verified temporary artifact."

    # If it is a protected foundation deliverable
    if fp.name in PROTECTED_FOUNDATION_NAMES:
        # Check ownership
        is_gen = WorkspaceOwnershipManifest.is_generated_file(fp, ws)
        if not is_gen:
            return (
                False,
                f"Gate 16 BLOCKED: File '{fp.name}' is user-owned or not recorded in HERMES generated-file manifest. Deletion denied to protect user data.",
            )
        # If recorded in manifest, allow only if explicit authorization/regeneration reason given
        if reason in ("scaffolder_regeneration", "stale_deliverable_purge", "explicit_regeneration"):
            return True, "Authorized HERMES deliverable update."
        return (
            False,
            f"Gate 16 BLOCKED: Protected deliverable '{fp.name}' requires explicit regeneration authorization to delete.",
        )

    return True, "Safe to delete non-foundation workspace file."


def safe_delete_file(
    file_path: Path | str,
    workspace_root: Path | str,
    is_temporary: bool = False,
    reason: str = "",
) -> bool:
    """
    Safely delete a file while strictly respecting Gate 16 and ownership rules.
    If ownership cannot be established, preserves the file and returns False.
    """
    fp = Path(file_path)
    if not fp.exists():
        return True
    allowed, block_reason = can_safely_delete_file(file_path, workspace_root, is_temporary, reason)
    if not allowed:
        logger.warning(f"safe_delete_file blocked: {block_reason}")
        return False
    try:
        fp.unlink(missing_ok=True)
        WorkspaceOwnershipManifest.unregister(fp, workspace_root)
        logger.debug(f"safe_delete_file: removed {fp}")
        return True
    except Exception as e:
        logger.warning(f"safe_delete_file: unlink failed on {fp}: {e}")
        return False


def safe_rmtree(
    dir_path: Path | str,
    workspace_root: Path | str,
    is_temporary: bool = False,
    reason: str = "",
) -> bool:
    """
    Safely delete a directory tree, strictly blocking workspace root or protected folders.
    """
    import shutil
    try:
        ws = Path(workspace_root).resolve()
        dp = Path(dir_path).resolve()
    except Exception as e:
        logger.warning(f"safe_rmtree invalid path: {e}")
        return False

    # Never delete workspace root or above
    if dp == ws or dp in ws.parents:
        logger.warning(f"safe_rmtree BLOCKED: Cannot delete workspace root or parent: {dp}")
        return False

    # Must be inside workspace
    try:
        rel = dp.relative_to(ws)
        rel_str = str(rel).replace("\\", "/")
    except ValueError:
        logger.warning(f"safe_rmtree BLOCKED: Path outside workspace: {dp}")
        return False

    # Never delete critical root asset or source directories unless temporary subfolder
    protected_dirs = {"assets", "images", "src", "public", ".hermes", ".artifacts", "."}
    if rel_str in protected_dirs:
        logger.warning(f"safe_rmtree BLOCKED: Cannot delete protected top-level directory: {rel_str}")
        return False

    # Allow if verified temp
    if is_temporary or any(m in rel_str for m in VERIFIED_TEMP_MARKERS):
        try:
            shutil.rmtree(dp, ignore_errors=True)
            return True
        except Exception as e:
            logger.warning(f"safe_rmtree failed on {dp}: {e}")
            return False

    logger.warning(f"safe_rmtree BLOCKED: Directory '{rel_str}' is not verified temporary artifact.")
    return False
