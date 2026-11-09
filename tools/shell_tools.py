# tools/shell_tools.py
# Shell execution tools for HERMES.
# ALL shell commands pass through the 15 security gates in tools/security.py first.
# Never call subprocess directly from orchestrator - always use these tools.

import os
import subprocess
import time
import shlex
import sys
import re
import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from core.workspace import workspace_manager
from tools.base import BaseTool, ToolResult
from tools.registry import tool
from tools.security import check_all_gates
import contextvars
from loguru import logger
import psutil

# Context variable tracking current mission ID in executing asyncio task/thread
CURRENT_MISSION_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("current_mission_id", default=None)

# Registry of active subprocesses for reliable termination during cancellation.
# Backward-compatible set[subprocess.Popen]
ACTIVE_SUBPROCESSES: set[subprocess.Popen] = set()

# Authoritative process-to-mission ownership mapping: proc -> mission_id
PROCESS_MISSION_MAP: dict[subprocess.Popen, Optional[str]] = {}


def register_active_subprocess(proc: subprocess.Popen, mission_id: Optional[str] = None) -> None:
    """Register an active subprocess with optional mission ownership."""
    effective_mission_id = mission_id if mission_id is not None else CURRENT_MISSION_ID.get()
    ACTIVE_SUBPROCESSES.add(proc)
    PROCESS_MISSION_MAP[proc] = effective_mission_id


def unregister_active_subprocess(proc: subprocess.Popen) -> None:
    """Unregister an active subprocess."""
    ACTIVE_SUBPROCESSES.discard(proc)
    PROCESS_MISSION_MAP.pop(proc, None)


def terminate_active_subprocesses(mission_id: Optional[str] = None) -> int:
    """
    Terminates active subprocesses tracked during mission execution.
    If mission_id is provided, only terminates subprocesses owned by that mission.
    If mission_id is None, terminates all tracked subprocesses.
    Safely terminates child process trees on Windows before killing parent.
    """
    count = 0
    targets = []
    for proc in list(ACTIVE_SUBPROCESSES):
        owner = PROCESS_MISSION_MAP.get(proc)
        if mission_id is None or owner == mission_id:
            targets.append(proc)

    for proc in targets:
        try:
            pid = proc.pid
            # 1. Terminate descendant processes first (process tree cleanup)
            try:
                parent_ps = psutil.Process(pid)
                children = parent_ps.children(recursive=True)
                for child in children:
                    try:
                        child.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                # Wait briefly for children to terminate
                gone, alive = psutil.wait_procs(children, timeout=1.0)
                for surviving in alive:
                    try:
                        surviving.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                pass

            # 2. Terminate the main tracked process
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                if os.name == "nt" and proc.poll() is None:
                    try:
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=1.0)
                    except Exception:
                        pass
                count += 1
        except Exception as e:
            logger.debug(f"Error terminating subprocess {getattr(proc, 'pid', 'unknown')}: {e}")
        finally:
            unregister_active_subprocess(proc)

    return count


def _split_compound_command(cmd: str) -> list[tuple[str, str]]:
    """
    Tokenizes a command string into a list of (subcommand, operator) pairs.
    Handles quotes (single and double) so && or ; inside quotes are not treated as operators.
    Operators recognized: '&&', '||', '|', '&', ';'
    Ignores '&' if it is part of a file descriptor redirection like '2>&1' or '>&'.
    """
    tokens = []
    current = []
    in_single = False
    in_double = False
    i = 0
    n = len(cmd)

    while i < n:
        c = cmd[i]
        if c == "'" and not in_double:
            in_single = not in_single
            current.append(c)
            i += 1
        elif c == '"' and not in_single:
            in_double = not in_double
            current.append(c)
            i += 1
        elif not in_single and not in_double:
            # Check 2-char operators first: '&&', '||'
            op2 = cmd[i:i+2]
            if op2 in ('&&', '||'):
                tokens.append((''.join(current).strip(), op2))
                current = []
                i += 2
                continue

            # Check file descriptor redirect like 2>&1 or >&2
            if c == '&' and i > 0 and cmd[i-1] == '>':
                current.append(c)
                i += 1
                continue

            # Check 1-char operators: '|', '&', ';'
            if c in ('|', '&', ';'):
                tokens.append((''.join(current).strip(), c))
                current = []
                i += 1
                continue

            current.append(c)
            i += 1
        else:
            current.append(c)
            i += 1

    if current or not tokens:
        tokens.append((''.join(current).strip(), ''))

    return tokens


def _translate_single_command(command: str, py: str, cwd: Optional[Path] = None) -> str:
    """Translate an atomic command into platform-appropriate syntax."""
    stripped_command = command.strip()
    if not stripped_command:
        return ""

    # Global POSIX redirection normalization
    stripped_command = stripped_command.replace("/dev/null", "NUL")

    # 1. Normalize python / python3 / pytest invocations to canonical venv python
    if stripped_command.startswith("python "):
        stripped_command = f'"{py}" ' + stripped_command[7:]
    elif stripped_command == "python":
        stripped_command = f'"{py}"'
    elif stripped_command.startswith("python3 "):
        stripped_command = f'"{py}" ' + stripped_command[8:]
    elif stripped_command == "python3":
        stripped_command = f'"{py}"'
    elif stripped_command.startswith("pytest "):
        stripped_command = f'"{py}" -m pytest ' + stripped_command[7:]
    elif stripped_command == "pytest":
        stripped_command = f'"{py}" -m pytest'

    # 2. Windows specific builtins
    is_windows = sys.platform == "win32" or Path("C:/Windows").exists()
    if is_windows:
        if stripped_command == "pwd":
            return f'"{py}" -c "import os; print(os.getcwd())"'

        try:
            parts = shlex.split(stripped_command, posix=False)
        except Exception:
            parts = stripped_command.split()

        if parts:
            lead = parts[0].strip('"\'')

            if lead == "pwd":
                return f'"{py}" -c "import os; print(os.getcwd())"'

            if lead == "ls":
                # Translate ls commands (e.g. ls -1, ls -la, ls) into canonical python directory listing
                non_flags = [p.strip('"\'') for p in parts[1:] if not p.strip('"\'').startswith("-")]
                target = non_flags[0] if non_flags else "."
                target_esc = target.replace('"', '\\"')
                py_code = "import os, sys; p = sys.argv[1] if len(sys.argv) > 1 else '.'; (print('\\n'.join(sorted(os.listdir(p)))) if os.path.isdir(p) else (print(p) if os.path.exists(p) else (print('ls: cannot access ' + p + ': No such file or directory', file=sys.stderr), sys.exit(1))))"
                return f'"{py}" -c "{py_code}" "{target_esc}"'

            if lead == "cat" and len(parts) > 1:
                target = parts[1].strip('"\'')
                target_esc = target.replace('"', '\\"')
                py_code = "import os, sys; p=sys.argv[1]; (sys.stdout.write(open(p, 'r', encoding='utf-8', errors='replace').read()) if os.path.exists(p) else (print('cat: ' + p + ': No such file or directory', file=sys.stderr), sys.exit(1)))"
                return f'"{py}" -c "{py_code}" "{target_esc}"'

            if lead == "head":
                n_lines = 10
                if len(parts) > 1:
                    arg = parts[1].strip('"\'')
                    if arg.startswith("-") and arg[1:].isdigit():
                        n_lines = int(arg[1:])
                    elif arg == "-n" and len(parts) > 2 and parts[2].strip('"\'').isdigit():
                        n_lines = int(parts[2].strip('"\''))
                py_code = f"import sys; [sys.stdout.write(l) for _, l in zip(range({n_lines}), sys.stdin)]"
                return f'"{py}" -c "{py_code}"'

            if lead == "tail":
                n_lines = 10
                if len(parts) > 1:
                    arg = parts[1].strip('"\'')
                    if arg.startswith("-") and arg[1:].isdigit():
                        n_lines = int(arg[1:])
                    elif arg == "-n" and len(parts) > 2 and parts[2].strip('"\'').isdigit():
                        n_lines = int(parts[2].strip('"\''))
                py_code = f"import sys, collections; sys.stdout.writelines(collections.deque(sys.stdin, {n_lines}))"
                return f'"{py}" -c "{py_code}"'

            if lead == "wc":
                flags = [p.strip('"\'') for p in parts[1:] if p.strip('"\'').startswith("-")]
                targets = [p.strip('"\'') for p in parts[1:] if not p.strip('"\'').startswith("-")]
                flags_str = "".join(f.lstrip("-") for f in flags) or "l"
                targets_str = " ".join(f'"{t.replace(chr(34), chr(92) + chr(34))}"' for t in targets)
                py_code = (
                    "import sys, os; flags = sys.argv[1]; targets = sys.argv[2:]; "
                    "lines_o = 'l' in flags; words_o = 'w' in flags; bytes_o = 'c' in flags; def_m = not (lines_o or words_o or bytes_o); "
                    "fmt = lambda l, w, c, n='': ' '.join(([str(l)] if (lines_o or def_m) else []) + ([str(w)] if (words_o or def_m) else []) + ([str(c)] if (bytes_o or def_m) else []) + ([n] if n else [])); "
                    "data = sys.stdin.buffer.read() if not targets else b''; "
                    "sys.stdout.write(fmt(data.count(b'\\n'), len(data.split()), len(data)) + '\\n') if not targets else "
                    "[sys.stdout.write(fmt(open(t, 'rb').read().count(b'\\n'), len(open(t, 'rb').read().split()), len(open(t, 'rb').read()), t) + '\\n') "
                    "if os.path.exists(t) else sys.stderr.write('wc: ' + t + ': No such file or directory\\n') for t in targets]"
                )
                return f'"{py}" -c "{py_code}" "{flags_str}" {targets_str}'.strip()

            if lead == "which" and len(parts) > 1:
                target = parts[1].strip('"\'')
                if target in ("python", "python3"):
                    return f'"{py}" -c "import sys; print(sys.executable)"'
                return f"where {target}"

            if lead == "sleep" and len(parts) > 1 and parts[1].isdigit():
                return f'"{py}" -c "import time; time.sleep({parts[1]})"'

            if lead == "mkdir" and "-p" in [p.strip('"\'') for p in parts[1:]]:
                targets = [p.strip('"\'') for p in parts[1:] if p.strip('"\'') != "-p"]
                target = targets[0] if targets else "."
                target_esc = target.replace('"', '\\"')
                return f'"{py}" -c "import os, sys; os.makedirs(sys.argv[1], exist_ok=True)" "{target_esc}"'

            if lead == "touch" and len(parts) > 1:
                target = parts[1].strip('"\'')
                target_esc = target.replace('"', '\\"')
                return f'"{py}" -c "import pathlib, sys; pathlib.Path(sys.argv[1]).touch(exist_ok=True)" "{target_esc}"'

            if lead == "rm":
                # Translate rm / rm -f / rm -rf into cross-platform Python unlinking
                flags = [p.strip('"\'') for p in parts[1:] if p.strip('"\'').startswith("-")]
                targets = [p.strip('"\'') for p in parts[1:] if not p.strip('"\'').startswith("-")]
                is_recursive = any("r" in f.lower() for f in flags)
                is_force = any("f" in f.lower() for f in flags)
                # Safeguard: Block destructive removal of protected foundation deliverables
                protected = {"index.html", "style.css", "app.js", "package.json", "assets", "images", "src", ".artifacts", ".hermes"}
                if (is_recursive or len(targets) > 1) and any(t.lower() in protected or any(t.lower().endswith("/" + p) or t.lower().endswith("\\" + p) for p in protected) for t in targets):
                    return f'"{py}" -c "import sys; print(\'SECURITY: Destructive deletion of active project deliverables is forbidden.\', file=sys.stderr); sys.exit(126)"'
                py_code = (
                    f"import os, sys, shutil; targets = sys.argv[1:]; force = {is_force}; recursive = {is_recursive}; "
                    "[((shutil.rmtree(t) if (os.path.isdir(t) and recursive) else os.rmdir(t) if os.path.isdir(t) else os.remove(t)) "
                    "if os.path.exists(t) else (sys.exit(1) if not force else None)) for t in targets]"
                )
                args_str = " ".join(f'"{t.replace(chr(34), chr(92) + chr(34))}"' for t in targets)
                return f'"{py}" -c "{py_code}" {args_str}'

            if lead == "export" and len(parts) > 1:
                return f"set {parts[1]}"

            # Detect PowerShell-specific cmdlets on Windows and wrap appropriately
            ps_cmdlets = {"get-content", "select-string", "test-path", "get-childitem", "set-content", "where-object", "invoke-webrequest", "out-file"}
            if lead.lower() in ps_cmdlets or lead.lower().startswith("$env:") or stripped_command.startswith("$"):
                cmd_escaped = stripped_command.replace('"', '`"')
                return f'powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "{cmd_escaped}"'

    # 3. If cwd or workspace_manager has an active directory, normalize redundant directory prefix
    try:
        from core.workspace import workspace_manager
        ws_dir = cwd or (Path(workspace_manager.workspace_root) if workspace_manager.is_locked and workspace_manager.workspace_root else None)
        if ws_dir and ws_dir.exists():
            ws_name = ws_dir.name
            for sep in ("/", "\\"):
                prefix = f"{ws_name}{sep}"
                if prefix in stripped_command:
                    tokens = stripped_command.split()
                    new_tokens = []
                    for tok in tokens:
                        unquoted = tok.strip("\"'")
                        if unquoted.startswith(prefix):
                            rel_sub = unquoted[len(prefix):]
                            if not (ws_dir / unquoted).exists() and (ws_dir / rel_sub).exists():
                                tok = tok.replace(prefix, "", 1)
                        new_tokens.append(tok)
                    stripped_command = " ".join(new_tokens)
    except Exception:
        pass

    return stripped_command


def _command_for_platform(command: str, cwd: Optional[Path] = None) -> str:
    """Translate compound POSIX shell commands and python calls using canonical python."""
    stripped_command = command.strip()
    if not stripped_command:
        return ""

    from core.runtime_identity import get_canonical_python_executable
    py = get_canonical_python_executable()

    # Split compound commands (&&, ||, |, &, ;) while respecting quotes and redirects
    pairs = _split_compound_command(stripped_command)

    # If single atomic command without operators, fastpath
    if len(pairs) == 1 and not pairs[0][1]:
        return _translate_single_command(pairs[0][0], py, cwd=cwd)

    # Translate each sub-command and reconnect with operator
    translated_pairs = []
    is_windows = sys.platform == "win32" or Path("C:/Windows").exists()
    for subcmd, op in pairs:
        t_sub = _translate_single_command(subcmd, py, cwd=cwd)
        # On Windows cmd.exe, ';' maps to '&' for sequential execution
        norm_op = ('&' if (op == ';' and is_windows) else op)
        translated_pairs.append((t_sub, norm_op))

    result = ""
    for sub, op in translated_pairs:
        if result:
            result += " "
        result += sub
        if op:
            result += f" {op}"

    return result


def _parse_npm_command_details(command: str, work_dir: Path) -> tuple[bool, Optional[str], Path]:
    """
    Parses npm command to detect if it runs a script (e.g. test or run <script>),
    and resolves the effective directory respecting any --prefix argument.
    Returns: (is_script_run, script_name, effective_dir)
    """
    cmd_clean = command.strip()
    if not re.search(r"\bnpm(?:\.cmd|\.exe)?\b", cmd_clean, re.I):
        return False, None, work_dir

    # Extract --prefix if present: --prefix <dir>, --prefix=<dir>, --prefix "<dir>", --prefix '<dir>'
    prefix_match = re.search(r'''--prefix(?:=|\s+)(?:"([^"]+)"|'([^']+)'|([^\s]+))''', cmd_clean)
    if prefix_match:
        prefix_val = prefix_match.group(1) or prefix_match.group(2) or prefix_match.group(3)
        effective_dir = (work_dir / prefix_val).resolve()
    else:
        effective_dir = work_dir.resolve()

    # Strip --prefix parameter to easily match the subcommand and arguments
    cmd_no_prefix = re.sub(r'''--prefix(?:=|\s+)(?:"[^"]*"|'[^']*'|[^\s]+)''', '', cmd_clean)

    # Check for npm test / npm t / npm tst / npm run test / npm run-script test
    if re.search(r"\bnpm(?:\.cmd|\.exe)?\s+(?:run(?:-script)?\s+)?(?:test|t|tst)\b", cmd_no_prefix, re.I):
        return True, "test", effective_dir

    # Check for npm run <script> / npm run-script <script>
    run_match = re.search(r"\bnpm(?:\.cmd|\.exe)?\s+(?:run(?:-script)?)\s+([a-zA-Z0-9_\-:]+)", cmd_no_prefix, re.I)
    if run_match:
        return True, run_match.group(1), effective_dir

    # Check for npm start
    if re.search(r"\bnpm(?:\.cmd|\.exe)?\s+start\b", cmd_no_prefix, re.I):
        return True, "start", effective_dir

    return False, None, effective_dir


@tool(
    name="bash_exec",
    description="Execute any shell command (pip install, git log, wc -l, echo, curl, grep, find, pwd, ls). Use this for installing packages, viewing git history, counting lines in a file, checking ports, and any system command that is not running a .py file or pytest.",
    permissions=["shell"],
    risk_score=0.7,
    blocked_in=["safe"],
)
class BashExecTool(BaseTool):
    """Execute a shell command after passing all security gates."""

    class Input(BaseModel):
        """Validated input for BashExecTool."""

        command: str = Field(
            ...,
            description="The shell command to execute",
            min_length=1,
            max_length=2000,
        )
        working_dir: str = Field(
            default=".",
            description="Working directory for command execution, relative to project root",
        )
        timeout_seconds: int = Field(
            default=30,
            ge=1,
            le=300,
            description="Maximum seconds to wait for command to complete",
        )

    def execute(self, inp: Input) -> ToolResult:
        """Execute a shell command and return stdout, stderr, exit code, and duration."""
        passed, reason = check_all_gates(inp.command)
        if not passed:
            logger.warning(
                f"bash_exec BLOCKED | cmd={inp.command[:100]!r} | reason={reason}"
            )
            return ToolResult(
                success=False,
                output="",
                error=f"BLOCKED by security gate: {reason}",
                exit_code=126,
            )

        # Force working directory to workspace root for security
        from core.workspace import workspace_manager
        cwd = workspace_manager.workspace_root or Path.cwd()
        if inp.working_dir and inp.working_dir != ".":
            target_dir = Path(inp.working_dir)
            if not target_dir.is_absolute():
                work_dir = (cwd / target_dir).resolve()
            else:
                work_dir = target_dir.resolve()
        else:
            work_dir = Path(cwd).resolve()

        if not work_dir.exists():
            if workspace_manager.is_locked and workspace_manager.workspace_root and (
                work_dir == workspace_manager.workspace_root or
                workspace_manager.workspace_root in work_dir.parents
            ):
                try:
                    work_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(f"ShellTools: bootstrapped greenfield workspace directory {work_dir}")
                except Exception as mkdir_err:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Failed to bootstrap working directory {work_dir}: {mkdir_err}",
                        exit_code=1,
                    )
            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Working directory does not exist: {inp.working_dir}",
                    exit_code=1,
                )

        start_time = time.monotonic()

        # Intercept persistent HTTP dev server commands to prevent blocking the agent loop
        cmd_clean = inp.command.strip().lower()
        if any(k in cmd_clean for k in ("http.server", "npx serve", "serve .", "live-server", "python3 -m http.server")) or (("npm start" in cmd_clean or "yarn start" in cmd_clean) and ("server" in cmd_clean or "preview" in cmd_clean)):
            from core.browser.dev_server import DevServerManager
            from tools.browser_tools import _run_async

            # Parse optional port e.g. python -m http.server 8000
            port_match = re.search(r"http\.server\s+(\d+)", inp.command, re.IGNORECASE)
            assigned_port = int(port_match.group(1)) if port_match else None

            try:
                dev_mgr = DevServerManager()
                # Terminate any non-matching stale servers first
                dev_mgr.stop_stale_servers_not_matching(work_dir)
                server_info = _run_async(
                    dev_mgr.start_static_server(
                        directory=work_dir,
                        name=f"managed_{work_dir.name}",
                        port=assigned_port,
                        timeout=10.0,
                    )
                )
                duration = time.monotonic() - start_time
                pid_str = f"PID {server_info.process.pid}" if server_info.process else "active"
                return ToolResult(
                    success=True,
                    output=(
                        f"Managed development server started in background: {server_info.url}/ "
                        f"({pid_str}) serving {work_dir}. "
                        f"Server is verified ready. Use browser_open_preview to view."
                    ),
                    duration_seconds=duration,
                    exit_code=0,
                )
            except Exception as srv_err:
                logger.error(f"Failed to start managed background server: {srv_err}")
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Failed to start managed background server: {srv_err}",
                    exit_code=1,
                    duration_seconds=time.monotonic() - start_time,
                )

        # Determine platform command and runtime shell used
        command_to_run = _command_for_platform(inp.command, cwd=work_dir)
        is_windows = sys.platform == "win32" or Path("C:/Windows").exists()
        if is_windows:
            # Strip trailing POSIX background operator '&' on Windows to prevent syntax/hanging errors
            trimmed_cmd = command_to_run.rstrip()
            if trimmed_cmd.endswith("&") and not trimmed_cmd.endswith("&&"):
                command_to_run = trimmed_cmd[:-1].strip()
            shell_used = "powershell" if command_to_run.lower().startswith("powershell") else "cmd.exe"
        else:
            shell_used = "/bin/sh"

        # Command safety: Inspect package.json before executing npm commands (especially npm test)
        # Prevents running missing scripts and accepting fake zero exit codes
        is_npm_script, req_script, effective_dir = _parse_npm_command_details(inp.command, work_dir)

        if is_npm_script:
            pkg_json = effective_dir / "package.json"
            if not pkg_json.exists():
                duration = time.monotonic() - start_time
                err_msg = (
                    f"Execution blocked: Cannot execute '{inp.command}' because 'package.json' "
                    f"does not exist in project directory '{effective_dir}'."
                )
                logger.warning(f"bash_exec SAFETY_BLOCKED | cmd={inp.command!r} | reason=missing package.json at {effective_dir}")
                return ToolResult(
                    success=False,
                    output="",
                    error=err_msg,
                    exit_code=1,
                    duration_seconds=duration,
                    details={
                        "command": inp.command,
                        "cwd": str(work_dir),
                        "effective_dir": str(effective_dir),
                        "shell_used": shell_used,
                        "classification": "MISSING_PACKAGE_JSON",
                        "package_json_inspected": True,
                        "package_json_found": False,
                    },
                )

            # package.json exists - inspect scripts
            try:
                pkg_data = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
                scripts = pkg_data.get("scripts", {})
                if req_script == "test":
                    if "test" not in scripts or not str(scripts.get("test", "")).strip():
                        duration = time.monotonic() - start_time
                        err_msg = (
                            f"Execution blocked: Cannot execute '{inp.command}' because no 'test' script is defined "
                            f"in package.json at '{pkg_json}'. Defined scripts: {list(scripts.keys())}."
                        )
                        logger.warning(f"bash_exec SAFETY_BLOCKED | cmd={inp.command!r} | reason=missing test script in package.json")
                        return ToolResult(
                            success=False,
                            output="",
                            error=err_msg,
                            exit_code=1,
                            duration_seconds=duration,
                            details={
                                "command": inp.command,
                                "cwd": str(work_dir),
                                "effective_dir": str(effective_dir),
                                "shell_used": shell_used,
                                "classification": "MISSING_TEST_SCRIPT",
                                "package_json_inspected": True,
                                "package_json_found": True,
                                "defined_scripts": list(scripts.keys()),
                            },
                        )
                else:
                    if req_script not in scripts or not str(scripts.get(req_script, "")).strip():
                        duration = time.monotonic() - start_time
                        err_msg = (
                            f"Execution blocked: Cannot execute '{inp.command}' because script '{req_script}' "
                            f"is not defined in package.json at '{pkg_json}'. Defined scripts: {list(scripts.keys())}."
                        )
                        logger.warning(f"bash_exec SAFETY_BLOCKED | cmd={inp.command!r} | reason=missing '{req_script}' script")
                        return ToolResult(
                            success=False,
                            output="",
                            error=err_msg,
                            exit_code=1,
                            duration_seconds=duration,
                            details={
                                "command": inp.command,
                                "cwd": str(work_dir),
                                "effective_dir": str(effective_dir),
                                "shell_used": shell_used,
                                "classification": "MISSING_NPM_SCRIPT",
                                "package_json_inspected": True,
                                "package_json_found": True,
                                "requested_script": req_script,
                                "defined_scripts": list(scripts.keys()),
                            },
                        )
            except Exception as parse_err:
                duration = time.monotonic() - start_time
                err_msg = f"Execution blocked: Could not parse package.json at '{pkg_json}': {parse_err}"
                return ToolResult(
                    success=False,
                    output="",
                    error=err_msg,
                    exit_code=1,
                    duration_seconds=duration,
                    details={
                        "command": inp.command,
                        "cwd": str(work_dir),
                        "effective_dir": str(effective_dir),
                        "shell_used": shell_used,
                        "classification": "INVALID_PACKAGE_JSON",
                        "package_json_inspected": True,
                    },
                )

        proc = None
        try:

            from core.runtime_identity import get_canonical_subprocess_env
            proc = subprocess.Popen(
                command_to_run,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(work_dir),
                env=get_canonical_subprocess_env({"PWD": str(work_dir)}),
                stdin=subprocess.DEVNULL,
            )
            mid = getattr(inp, "_mission_id", None) or CURRENT_MISSION_ID.get()
            register_active_subprocess(proc, mission_id=mid)
            stdout, stderr = proc.communicate(timeout=inp.timeout_seconds)
            duration = time.monotonic() - start_time
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            if proc:
                try:
                    p = psutil.Process(proc.pid)
                    children = p.children(recursive=True)
                    for child in children:
                        try:
                            child.kill()
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {inp.timeout_seconds} seconds",
                exit_code=124,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error executing command: {str(e)}",
                exit_code=1,
                duration_seconds=duration,
            )
        finally:
            if proc:
                unregister_active_subprocess(proc)

        combined_output = stdout
        if stderr:
            combined_output += (
                f"\n[STDERR]:\n{stderr}" if stdout else stderr
            )

        success = exit_code == 0
        logger.info(
            f"bash_exec | exit={exit_code} | duration={duration:.2f}s | "
            f"cmd={inp.command[:60]!r}"
        )
        classification = "SUCCESS" if success else "NON_ZERO_EXIT"
        if not success:
            err_lower = (stderr + " " + stdout).lower()
            if exit_code == 124:
                classification = "TIMEOUT"
            elif exit_code == 126:
                classification = "SECURITY_BLOCKED"
            elif exit_code == 127 or "not recognized as an internal or external command" in err_lower or "command not found" in err_lower:
                classification = "COMMAND_NOT_FOUND"
            elif "syntaxerror" in err_lower or "bracket mismatch" in err_lower or "syntax error" in err_lower:
                classification = "SYNTAX_ERROR"
            elif "missing script" in err_lower or "no test specified" in err_lower:
                classification = "MISSING_TEST_SCRIPT"

        details = {
            "command": inp.command,
            "cmd_to_run": command_to_run,
            "shell_used": shell_used,
            "cwd": str(work_dir),
            "effective_dir": str(effective_dir if is_npm_script else work_dir),
            "pid": getattr(proc, "pid", None),
            "exit_code": exit_code,
            "duration_seconds": duration,
            "timed_out": False,
            "stdout_chars": len(stdout),
            "stderr_chars": len(stderr),
            "classification": classification,
        }
        return ToolResult(
            success=success,
            output=combined_output,
            error=stderr if not success else None,
            exit_code=exit_code,
            duration_seconds=duration,
            details=details,
        )



@tool(
    name="run_python",
    description="Execute a .py Python script file. ONLY use when the user asks to run/execute a specific .py file. Do NOT use for pip install or shell commands.",
    permissions=["shell"],
    risk_score=0.5,
    blocked_in=["safe"],
)
class RunPythonTool(BaseTool):
    """Execute a Python file with the current interpreter after security checks."""

    class Input(BaseModel):
        """Validated input for RunPythonTool."""

        file_path: str = Field(
            ...,
            description="Path to the Python file to execute, relative to project root",
            min_length=1,
            max_length=500,
        )
        args: list[str] = Field(
            default_factory=list,
            description="Command line arguments to pass to the script",
        )
        working_dir: str = Field(
            default=".",
            description="Working directory, defaults to project root",
        )
        timeout_seconds: int = Field(default=60, ge=1, le=600)

    def execute(self, inp: Input) -> ToolResult:
        """Run a Python file and return stdout, stderr, exit code, and duration."""
        file_path = Path(inp.file_path)
        if not file_path.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Python file not found: {inp.file_path}",
                exit_code=1,
            )
        if not file_path.suffix == ".py":
            return ToolResult(
                success=False,
                output="",
                error=f"File is not a Python file: {inp.file_path}",
                exit_code=1,
            )

        work_dir = Path(inp.working_dir).resolve()
        if not work_dir.exists():
            from core.workspace import workspace_manager
            if workspace_manager.is_locked and workspace_manager.workspace_root and (
                work_dir == workspace_manager.workspace_root or
                workspace_manager.workspace_root in work_dir.parents
            ):
                try:
                    work_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(f"ShellTools: bootstrapped greenfield workspace directory {work_dir}")
                except Exception as mkdir_err:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Failed to bootstrap working directory {work_dir}: {mkdir_err}",
                        exit_code=1,
                    )
            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Working directory does not exist: {inp.working_dir}",
                    exit_code=1,
                )

        from core.runtime_identity import get_canonical_python_executable, get_canonical_subprocess_env
        canonical_py = get_canonical_python_executable()
        args_str = " ".join(shlex.quote(a) for a in inp.args)
        command = f'"{canonical_py}" {shlex.quote(str(file_path))} {args_str}'.strip()
        passed, reason = check_all_gates(command)
        if not passed:
            logger.warning(
                f"run_python BLOCKED | cmd={command[:100]!r} | reason={reason}"
            )
            return ToolResult(
                success=False,
                output="",
                error=f"BLOCKED by security gate: {reason}",
                exit_code=126,
            )

        start_time = time.monotonic()
        proc = None
        try:
            cmd_list = [canonical_py, str(file_path)] + inp.args
            proc = subprocess.Popen(
                cmd_list,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(work_dir),
                env=get_canonical_subprocess_env(),
                stdin=subprocess.DEVNULL,
            )
            register_active_subprocess(proc)
            stdout, stderr = proc.communicate(timeout=inp.timeout_seconds)
            duration = time.monotonic() - start_time
            result_returncode = proc.returncode
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {inp.timeout_seconds} seconds",
                exit_code=124,
                duration_seconds=duration,
            )
        except OSError as e:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error executing Python file: {str(e)}",
                exit_code=1,
                duration_seconds=duration,
            )
        finally:
            if proc:
                unregister_active_subprocess(proc)

        combined_output = stdout
        if stderr:
            combined_output += (
                f"\n[STDERR]:\n{stderr}" if stdout else stderr
            )

        success = result_returncode == 0
        logger.info(
            f"run_python | exit={result_returncode} | duration={duration:.2f}s | "
            f"file={inp.file_path[:60]!r}"
        )
        return ToolResult(
            success=success,
            output=combined_output,
            error=stderr if not success else None,
            exit_code=result_returncode,
            duration_seconds=duration,
        )


@tool(
    name="run_tests",
    description="Run pytest on a test file or test directory. ONLY use when the user explicitly asks to run tests or pytest. Do NOT use for running regular Python scripts.",
    permissions=["shell"],
    risk_score=0.4,
    blocked_in=["safe"],
)
class RunTestsTool(BaseTool):
    """Run pytest for a file or directory after security checks."""

    class Input(BaseModel):
        """Validated input for RunTestsTool."""

        test_path: str = Field(
            ...,
            description="Path to the test file or directory to run",
            min_length=1,
            max_length=500,
        )
        verbose: bool = Field(default=True, description="Run with -v flag for detailed output")
        timeout_seconds: int = Field(default=120, ge=1, le=600)

    def execute(self, inp: Input) -> ToolResult:
        """Run pytest and return full output, exit code, and duration."""
        test_path = Path(inp.test_path)
        if not test_path.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Test path does not exist: {inp.test_path}",
                exit_code=1,
            )

        from core.runtime_identity import get_canonical_python_executable, get_canonical_subprocess_env
        canonical_py = get_canonical_python_executable()
        flags = "-v" if inp.verbose else ""
        command = f'"{canonical_py}" -m pytest {shlex.quote(inp.test_path)} {flags}'.strip()
        passed, reason = check_all_gates(command)
        if not passed:
            logger.warning(
                f"run_tests BLOCKED | cmd={command[:100]!r} | reason={reason}"
            )
            return ToolResult(
                success=False,
                output="",
                error=f"BLOCKED by security gate: {reason}",
                exit_code=126,
            )

        start_time = time.monotonic()
        proc = None
        try:
            cmd_list = [canonical_py, "-m", "pytest", inp.test_path] + (
                ["-v"] if inp.verbose else []
            )
            proc = subprocess.Popen(
                cmd_list,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=get_canonical_subprocess_env(),
                stdin=subprocess.DEVNULL,
            )
            register_active_subprocess(proc)
            stdout, stderr = proc.communicate(timeout=inp.timeout_seconds)
            duration = time.monotonic() - start_time
            result_returncode = proc.returncode
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {inp.timeout_seconds} seconds",
                exit_code=124,
                duration_seconds=duration,
            )
        except OSError as e:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error running tests: {str(e)}",
                exit_code=1,
                duration_seconds=duration,
            )
        finally:
            if proc:
                unregister_active_subprocess(proc)

        combined_output = stdout
        if stderr:
            combined_output += (
                f"\n[STDERR]:\n{stderr}" if stdout else stderr
            )

        summary_line = ""
        for line in stdout.split("\n"):
            if "passed" in line or "failed" in line or "error" in line:
                summary_line = line.strip()
                break

        success = result_returncode == 0
        logger.info(
            f"run_tests | exit={result_returncode} | duration={duration:.2f}s | "
            f"summary={summary_line!r}"
        )
        return ToolResult(
            success=success,
            output=combined_output,
            error=stderr if not success else None,
            exit_code=result_returncode,
            duration_seconds=duration,
        )


# Convenience aliases
ShellInput = BashExecTool.Input
execute_shell_command = BashExecTool().execute
