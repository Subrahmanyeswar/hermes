# core/server/launcher.py
"""
HERMES Windows & Cross-Platform GUI Launcher and Process Lifecycle Manager.

Responsibilities:
1. Canonical execution via Python 3.12 virtual environment.
2. Port conflict safety: detects existing HERMES instances to prevent duplicates,
   and strictly refuses to terminate unrelated third-party processes.
3. Health verification: verifies backend readiness via /api/health before launching browser.
4. Process management: non-blocking detached startup, PID tracking, and graceful stop helper.
5. Log persistence: redirects stdout and stderr to data/logs/hermes_gui_server.log.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
import psutil
from loguru import logger

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PID_FILE = ROOT / ".hermes_server.pid"
LOG_DIR = ROOT / "data" / "logs"
LOG_FILE = LOG_DIR / "hermes_gui_server.log"


def check_port_in_use(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """Check if TCP port is currently accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        res = sock.connect_ex((host, port))
        return res == 0


def get_process_on_port(port: int = DEFAULT_PORT) -> Optional[psutil.Process]:
    """Find the psutil.Process currently listening on the specified port."""
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port:
                if conn.pid:
                    try:
                        return psutil.Process(conn.pid)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        return None
    except Exception as e:
        logger.debug(f"Could not inspect net_connections: {e}")
    return None


def compute_local_code_fingerprint() -> str:
    """Compute local fingerprint to verify runtime code matches the server on port."""
    try:
        import hashlib
        h = hashlib.sha256()
        for rel in ["core/server/app.py", "core/server/runtime_adapter.py", "core/agent_loop/loop.py"]:
            target = ROOT / rel
            if target.exists():
                h.update(target.read_bytes())
        return h.hexdigest()[:16]
    except Exception:
        return "unknown"


def verify_hermes_health(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
    """Query /api/health to verify if a listening service is a genuine HERMES runtime."""
    try:
        r = httpx.get(f"http://{host}:{port}/api/health", timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "ok" and "model_stack" in data:
                local_fp = compute_local_code_fingerprint()
                remote_fp = data.get("code_fingerprint")
                if remote_fp:
                    data["code_match"] = bool(local_fp == remote_fp)
                return data
    except Exception:
        pass
    return None


def verify_runtime_identity(
    health_data: Optional[Dict[str, Any]],
    expected_pid: Optional[int] = None,
    expected_fingerprint: Optional[str] = None,
    expected_python_version: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Validate runtime identity attributes against expected parameters.
    Returns (is_valid, reason).
    """
    if not health_data or not isinstance(health_data, dict):
        return False, "MISSING_HEALTH_DATA"

    if health_data.get("status") != "ok":
        return False, "INVALID_STATUS"

    if "model_stack" not in health_data or not isinstance(health_data.get("model_stack"), dict):
        return False, "MALFORMED_MODEL_STACK"

    # Python version check
    py_ver = health_data.get("python_version")
    if not py_ver or not isinstance(py_ver, str):
        return False, "MISSING_PYTHON_VERSION"
    if expected_python_version and not py_ver.startswith(expected_python_version):
        return False, f"PYTHON_VERSION_MISMATCH: expected {expected_python_version}, got {py_ver}"

    # PID check if specified
    if expected_pid is not None:
        actual_pid = health_data.get("pid")
        if actual_pid is None:
            return False, "MISSING_PID"
        if actual_pid != expected_pid:
            return False, f"PID_MISMATCH: expected {expected_pid}, got {actual_pid}"

    # Code fingerprint check
    local_fp = expected_fingerprint or compute_local_code_fingerprint()
    remote_fp = health_data.get("code_fingerprint")
    if not remote_fp:
        return False, "MISSING_CODE_FINGERPRINT"
    if remote_fp != local_fp:
        return False, f"CODE_FINGERPRINT_MISMATCH: server={remote_fp}, local={local_fp}"

    return True, "IDENTITY_VERIFIED"


def is_hermes_process(proc: Optional[psutil.Process]) -> bool:
    """Verify whether a psutil.Process instance is a genuine HERMES runtime process."""
    if not proc:
        return False
    try:
        if not proc.is_running():
            return False
        cmdline_list = proc.cmdline() if hasattr(proc, "cmdline") else []
        cmdline = " ".join(cmdline_list)
        if ("uvicorn" in cmdline and "core.server" in cmdline) or ("main.py" in cmdline and "serve" in cmdline):
            return True
        # Also check current working directory or process exe
        try:
            cwd = str(proc.cwd()) if hasattr(proc, "cwd") else ""
            proc_name = proc.name().lower() if hasattr(proc, "name") else ""
            if str(ROOT).lower() in cwd.lower() and "python" in proc_name:
                if "core.server" in cmdline or "uvicorn" in cmdline:
                    return True
        except (psutil.AccessDenied, psutil.NoSuchProcess, Exception):
            pass
    except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
        return False
    return False



def get_port_status(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> Dict[str, Any]:
    """
    Comprehensive port inspection:
    Returns {
        "in_use": bool,
        "pid": Optional[int],
        "process_name": Optional[str],
        "is_hermes": bool,
        "health": Optional[dict],
    }
    """
    in_use = check_port_in_use(host, port)
    if not in_use:
        return {
            "in_use": False,
            "pid": None,
            "process_name": None,
            "is_hermes": False,
            "health": None,
        }

    proc = get_process_on_port(port)
    pid = proc.pid if proc else None
    name = proc.name() if proc else None
    health = verify_hermes_health(host, port)
    is_hermes = health is not None

    # Secondary check via verified process commandline if health endpoint is slow or loading
    if not is_hermes and proc:
        is_hermes = is_hermes_process(proc)

    return {
        "in_use": True,
        "pid": pid,
        "process_name": name,
        "is_hermes": is_hermes,
        "health": health,
    }


def wait_for_health(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 15.0) -> Optional[Dict[str, Any]]:
    """Poll the health endpoint until healthy or timeout expires."""
    start = time.time()
    while time.time() - start < timeout:
        h = verify_hermes_health(host, port)
        if h:
            return h
        time.sleep(0.3)
    return None


def ensure_ollama_running() -> bool:
    """Ensure Ollama daemon is running if ollama executable exists."""
    if check_port_in_use("127.0.0.1", 11434):
        return True

    ollama_candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path("C:/Users/SUBBU/AppData/Local/Programs/Ollama/ollama.exe"),
        Path("C:/Program Files/Ollama/ollama.exe"),
    ]
    ollama_bin = None
    for p in ollama_candidates:
        if p.exists():
            ollama_bin = p
            break

    if not ollama_bin:
        return False

    try:
        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        subprocess.Popen(
            [str(ollama_bin), "serve"],
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(15):
            time.sleep(0.2)
            if check_port_in_use("127.0.0.1", 11434):
                print(f"[+] Ollama daemon auto-started from {ollama_bin}")
                return True
    except Exception as e:
        logger.warning(f"Could not auto-start Ollama: {e}")
    return False


def launch_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    log_path: Optional[Path] = None,
    timeout: float = 15.0,
) -> int:
    """
    Launch HERMES local GUI server safely on Windows / cross-platform.
    Returns 0 on success, 1 on error.
    """
    ensure_ollama_running()
    print(f"[*] Checking status of port {port} on {host}...")
    status = get_port_status(host, port)

    if status["in_use"]:
        if status["is_hermes"]:
            print(f"[+] HERMES server is already running on http://{host}:{port}/ (PID: {status['pid']}).")
            if open_browser:
                print(f"[*] Opening browser at http://{host}:{port}/ ...")
                webbrowser.open(f"http://{host}:{port}/")
            return 0
        else:
            print(f"[!] ERROR: Port {port} is occupied by an external process:")
            print(f"    Process ID: {status['pid']}")
            print(f"    Process Name: {status['process_name']}")
            print("    HERMES will NOT kill unrelated third-party processes.")
            print(f"    Please stop the conflicting process or choose a different port.")
            return 1

    # Verify built GUI assets exist
    gui_dist = ROOT / "gui" / "dist"
    if not (gui_dist / "index.html").exists():
        print(f"[!] WARNING: Built GUI bundle not found at {gui_dist}.")
        print("    Running frontend build (npm run build)...")
        try:
            subprocess.run(["npm", "run", "build"], cwd=str(ROOT / "gui"), check=True)
            print("[+] Frontend build succeeded.")
        except Exception as e:
            print(f"[!] ERROR: Failed to build frontend: {e}")
            print("    Please run 'cd gui && npm run build' manually.")
            return 1

    # Ensure log directory exists
    target_log = log_path or LOG_FILE
    target_log.parent.mkdir(parents=True, exist_ok=True)

    print(f"[*] Launching HERMES server with canonical interpreter: {sys.executable}")
    print(f"    Logs: {target_log}")

    log_handle = open(target_log, "a", encoding="utf-8")
    log_handle.write(f"\n--- HERMES Server Launch at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_handle.flush()

    # Launch background server
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "core.server.app:app",
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        "info",
    ]

    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=log_handle,
        stderr=log_handle,
        creationflags=creationflags,
    )

    # Record PID
    pid_data = {
        "pid": proc.pid,
        "host": host,
        "port": port,
        "started_at": time.time(),
        "log_file": str(target_log),
    }
    PID_FILE.write_text(json.dumps(pid_data, indent=2), encoding="utf-8")

    # Poll health
    print(f"[*] Waiting for backend readiness at http://{host}:{port}/api/health (timeout={timeout}s) ...")
    health = wait_for_health(host, port, timeout=timeout)

    if not health:
        print("[!] ERROR: Backend health check timed out or failed to start.")
        # Check if process is still alive
        if proc.poll() is not None:
            print(f"[!] Server process exited prematurely with code {proc.returncode}.")
        try:
            proc.kill()
            proc.wait(timeout=2.0)
        except Exception:
            pass
        if PID_FILE.exists():
            PID_FILE.unlink(missing_ok=True)

        try:
            log_handle.close()
        except Exception:
            pass

        # Print tail of log file
        if target_log.exists():
            lines = target_log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
            print("\n[Log Output Tail]:")
            for line in lines:
                print(f"  {line}")
        return 1

    try:
        log_handle.close()
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("  HERMES Graphical Harness is LIVE and Ready")
    print("=" * 60)
    print(f"  URL:            http://{host}:{port}/")
    print(f"  Python:         {health.get('python_version')} ({sys.executable})")
    print(f"  Workspace:      {health.get('workspace_root')}")
    print(f"  Runtime Mode:   {health.get('runtime_mode', 'auto').upper()}")
    print("  Model Stack:")
    stack = health.get("model_stack", {})
    print(f"    • Tier 1: {stack.get('tier1')}")
    print(f"    • Tier 2: {stack.get('tier2')}")
    print(f"    • Tier 3: {stack.get('tier3')}")
    print("=" * 60 + "\n")

    if open_browser:
        print(f"[*] Opening browser to http://{host}:{port}/ ...")
        webbrowser.open(f"http://{host}:{port}/")

    return 0


def stop_server(port: int = DEFAULT_PORT) -> bool:
    """
    Safely stop running HERMES server on port.
    Never terminates unrelated third-party processes.
    Strictly verifies process identity before any kill/terminate action.
    Returns True if stopped, False if error.
    """
    print(f"[*] Checking for running HERMES server on port {port}...")
    status = get_port_status(DEFAULT_HOST, port)

    # 1. Port is not in use: already stopped
    if not status["in_use"]:
        print(f"[+] No server detected listening on port {port}.")
        # Clean up stale PID file safely
        if PID_FILE.exists():
            try:
                data = json.loads(PID_FILE.read_text(encoding="utf-8"))
                stale_pid = data.get("pid")
                # Confirm stale pid is not running before unlinking
                if stale_pid:
                    try:
                        p = psutil.Process(stale_pid)
                        if not p.is_running():
                            PID_FILE.unlink(missing_ok=True)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        PID_FILE.unlink(missing_ok=True)
                else:
                    PID_FILE.unlink(missing_ok=True)
            except Exception:
                PID_FILE.unlink(missing_ok=True)
        return True

    # 2. Port is in use, but NOT verified HERMES -> Refuse termination
    if not status["is_hermes"]:
        print(f"[!] SAFETY ERROR: Process on port {port} (PID: {status['pid']}, Name: {status['process_name']}) is NOT a verified HERMES instance.")
        print("    Refusing to terminate unrelated third-party process.")
        return False

    pid = status["pid"]
    # Check PID file cross-verification
    if PID_FILE.exists():
        try:
            data = json.loads(PID_FILE.read_text(encoding="utf-8"))
            file_pid = data.get("pid")
            if file_pid and not pid:
                pid = file_pid
        except Exception:
            pass

    if not pid:
        print(f"[!] Could not determine PID for HERMES process on port {port}.")
        return False

    # 3. Strict identity check on the target process before termination
    try:
        proc = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        print(f"[!] Process PID {pid} is no longer accessible or not running.")
        if PID_FILE.exists():
            PID_FILE.unlink(missing_ok=True)
        return True

    # Confirm process identity matches HERMES
    if not is_hermes_process(proc) and not status.get("health"):
        print(f"[!] SAFETY ERROR: Process PID {pid} ({proc.name()}) does not match HERMES identity.")
        print("    Refusing to terminate unverified process.")
        return False

    print(f"[*] Stopping verified HERMES server (PID: {pid})...")
    try:
        proc.terminate()
        try:
            proc.wait(timeout=4.0)
        except psutil.TimeoutExpired:
            print("[*] Graceful shutdown timeout; force terminating...")
            proc.kill()
            proc.wait(timeout=2.0)
    except psutil.NoSuchProcess:
        pass
    except Exception as e:
        print(f"[!] Error stopping process {pid}: {e}")
        return False

    if PID_FILE.exists():
        PID_FILE.unlink(missing_ok=True)

    # Verify port released
    time.sleep(0.5)
    if not check_port_in_use(DEFAULT_HOST, port):
        print(f"[+] HERMES server stopped successfully. Port {port} is released.")
        return True
    else:
        print(f"[!] WARNING: Port {port} is still in use.")
        return False



if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HERMES GUI Launcher & Lifecycle Manager")
    parser.add_argument("action", choices=["launch", "stop", "status"], default="launch", nargs="?")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host (must be loopback)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")

    args = parser.parse_args()
    if args.action == "launch":
        code = launch_server(host=args.host, port=args.port, open_browser=not args.no_browser)
        sys.exit(code)
    elif args.action == "stop":
        ok = stop_server(port=args.port)
        sys.exit(0 if ok else 1)
    elif args.action == "status":
        stat = get_port_status(args.host, args.port)
        print(json.dumps(stat, indent=2))
        sys.exit(0)
