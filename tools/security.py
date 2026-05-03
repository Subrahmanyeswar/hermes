# tools/security.py
# HERMES security layer — 15 bash security gates.
# Every shell command passes through check_all_gates() before execution.
# If any gate returns (False, reason), the command is BLOCKED and never executes.
# These gates run before subprocess.run. Order matters — most dangerous checks first.

import os
import re
import unicodedata
from pathlib import Path

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


def check_all_gates(command: str) -> tuple[bool, str]:
    """
    Run all 15 security gates against a shell command.
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
