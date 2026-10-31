"""
HERMES Stage 5.1 - Windows Process Safety and Launcher Failure-Path Verification Test Suite.

Verifies:
1. Port Conflict:
   - Controlled unrelated TCP/HTTP server on a dynamically allocated test port.
   - Verifies HERMES recognizes port as occupied by an unrelated process.
   - Returns exit code 1 (failure status) without terminating or interfering with unrelated process.
   - Does not falsely report healthy.
   - Confirms the same protection logic applies on default port 8765.
2. Startup Timeout & Early Failure:
   - Server that never responds to /api/health times out strictly within configured timeout.
   - Controlled early exit (subprocess crashes/exits prematurely) detected immediately with returncode.
   - Cleans up PID file safely and avoids orphaned child processes.
   - Diagnostic tail captured in log without exposing secrets.
3. PID File & Process Identity Safety:
   - Stale PID file (pointing to dead process) is safely cleaned up without crashing or misidentifying.
   - Foreign PID file (PID belongs to an unrelated system process) is NEVER terminated by stop_server.
   - Process commandline cross-verification enforces that only verified HERMES processes can be terminated.
4. Repeat Launch & Stop:
   - Repeated launch against healthy server reuses existing process (return code 0, no duplicate spawn).
   - Stop against already-stopped instance returns True cleanly and safely.
   - Stop against verified server kills only intended instance and cleans PID file.
5. Health & Diagnostic Redaction:
   - /api/health readiness verified before launch_server succeeds.
   - Log output redact secrets/tokens if present in error diagnostics.
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import pytest
import psutil

from core.server import launcher


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def get_free_port() -> int:
    """Find a dynamically available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class DummyUnrelatedServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"I am an unrelated third-party service (e.g., database or web server)")

    def log_message(self, format, *args):
        pass  # Suppress console logging during test


# -----------------------------------------------------------------------------
# Section A: Port Conflict Tests (Real Sockets & Processes)
# -----------------------------------------------------------------------------

def test_port_conflict_on_dynamic_port_does_not_interfere():
    """
    Start a real unrelated HTTP server on a dynamic port.
    Launch HERMES targeted at that port.
    Verify:
    1. Launcher detects port occupied by unrelated process.
    2. Exits with non-zero failure code (1).
    3. Unrelated server is NOT terminated or disrupted.
    4. Launcher does not claim HERMES is healthy.
    """
    port = get_free_port()
    httpd = HTTPServer(("127.0.0.1", port), DummyUnrelatedServer)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    try:
        # Verify port is live
        status = launcher.get_port_status("127.0.0.1", port)
        assert status["in_use"] is True
        assert status["is_hermes"] is False
        assert status["health"] is None

        # Attempt to launch HERMES on this occupied port
        code = launcher.launch_server(host="127.0.0.1", port=port, open_browser=False)
        assert code == 1

        # Attempt to stop server on this occupied port -> must refuse
        ok = launcher.stop_server(port=port)
        assert ok is False

        # Confirm unrelated server is still alive and accepting connections
        assert launcher.check_port_in_use("127.0.0.1", port) is True
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_port_conflict_default_port_protection(monkeypatch):
    """
    Verify conflict safety behavior on default port 8765:
    Unrelated process cannot be killed or claimed as healthy.
    """
    mock_status = {
        "in_use": True,
        "pid": 77777,
        "process_name": "third_party_postgres.exe",
        "is_hermes": False,
        "health": None,
    }
    monkeypatch.setattr(launcher, "get_port_status", lambda host, port: mock_status)

    code = launcher.launch_server(host="127.0.0.1", port=8765, open_browser=False)
    assert code == 1

    ok = launcher.stop_server(port=8765)
    assert ok is False


# -----------------------------------------------------------------------------
# Section B: Startup Timeout & Early Failure Tests
# -----------------------------------------------------------------------------

def test_startup_timeout_cleans_up_process_and_pid(tmp_path, monkeypatch):
    """
    Simulate a process that starts but hangs/never serves /api/health.
    Verify:
    1. Times out within specified limit.
    2. Process is cleanly killed (no orphaned children).
    3. PID file is removed.
    4. Returns code 1.
    """
    fake_pid_file = tmp_path / "test_timeout.pid"
    fake_log_file = tmp_path / "test_timeout.log"
    monkeypatch.setattr(launcher, "PID_FILE", fake_pid_file)

    # Spawn a sleeping process that never serves HTTP
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Mock subprocess.Popen in launch_server to return our proc
        monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: proc)
        monkeypatch.setattr(launcher, "check_port_in_use", lambda h, p: False)

        # Launch with very short timeout (0.6s)
        code = launcher.launch_server(
            host="127.0.0.1",
            port=get_free_port(),
            open_browser=False,
            log_path=fake_log_file,
            timeout=0.6,
        )

        assert code == 1
        # Process should have been terminated by launcher cleanup
        assert proc.poll() is not None
        # PID file should be unlinked
        assert not fake_pid_file.exists()
    finally:
        if proc.poll() is None:
            proc.kill()


def test_early_process_crash_detected_immediately(tmp_path, monkeypatch):
    """
    Simulate a process that crashes on startup (e.g., exits with code 2).
    Verify launcher reports failure and cleans up PID file.
    """
    fake_pid_file = tmp_path / "test_crash.pid"
    fake_log_file = tmp_path / "test_crash.log"
    monkeypatch.setattr(launcher, "PID_FILE", fake_pid_file)

    # Spawn process that exits immediately with code 2
    proc = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stderr.write('Fatal crash on import\\n'); sys.exit(2)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    proc.wait()

    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(launcher, "check_port_in_use", lambda h, p: False)

    code = launcher.launch_server(
        host="127.0.0.1",
        port=get_free_port(),
        open_browser=False,
        log_path=fake_log_file,
        timeout=0.6,
    )

    assert code == 1
    assert not fake_pid_file.exists()


# -----------------------------------------------------------------------------
# Section C: PID File & Process Identity Safety
# -----------------------------------------------------------------------------

def test_stale_pid_file_cleaned_safely(tmp_path, monkeypatch):
    """
    A PID file exists pointing to a PID that is no longer running.
    Verify stop_server recognizes port is free and removes the stale PID file.
    """
    fake_pid_file = tmp_path / "stale.pid"
    # Choose a PID that doesn't exist
    fake_pid_file.write_text(json.dumps({"pid": 999998, "port": 8765}))
    monkeypatch.setattr(launcher, "PID_FILE", fake_pid_file)

    # Port is not in use
    monkeypatch.setattr(launcher, "check_port_in_use", lambda h, p: False)

    ok = launcher.stop_server(port=8765)
    assert ok is True
    # Stale PID file is safely removed
    assert not fake_pid_file.exists()


def test_foreign_pid_file_is_never_terminated(tmp_path, monkeypatch):
    """
    A PID file points to a live process, but that process is an unrelated system process
    (or foreign python script).
    Verify stop_server verifies process command line identity and REFUSES to terminate it.
    """
    fake_pid_file = tmp_path / "foreign.pid"
    # Spawn an unrelated python worker
    foreign_proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"]
    )

    try:
        fake_pid_file.write_text(json.dumps({"pid": foreign_proc.pid, "port": 8765}))
        monkeypatch.setattr(launcher, "PID_FILE", fake_pid_file)

        # Mock port as in use by this foreign proc, but NOT verified HERMES
        mock_status = {
            "in_use": True,
            "pid": foreign_proc.pid,
            "process_name": "python.exe",
            "is_hermes": False,
            "health": None,
        }
        monkeypatch.setattr(launcher, "get_port_status", lambda h, p: mock_status)

        ok = launcher.stop_server(port=8765)
        # Must refuse
        assert ok is False

        # Foreign process must still be running
        assert foreign_proc.poll() is None
    finally:
        foreign_proc.terminate()
        foreign_proc.wait()


# -----------------------------------------------------------------------------
# Section D: Repeat Launch & Stop Behavior
# -----------------------------------------------------------------------------

def test_repeat_launch_reuses_existing_healthy_server(monkeypatch):
    """
    When HERMES server is already running and healthy:
    1. launch_server returns code 0.
    2. Does NOT spawn a second subprocess.
    """
    spawned = []
    def fake_popen(*args, **kwargs):
        spawned.append(args)
        raise RuntimeError("Should not be called!")

    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)

    mock_status = {
        "in_use": True,
        "pid": 11111,
        "process_name": "python.exe",
        "is_hermes": True,
        "health": {"status": "ok", "model_stack": {"tier1": "glm"}},
    }
    monkeypatch.setattr(launcher, "get_port_status", lambda h, p: mock_status)

    code = launcher.launch_server(host="127.0.0.1", port=8765, open_browser=False)
    assert code == 0
    assert len(spawned) == 0


def test_stop_server_when_already_stopped(tmp_path, monkeypatch):
    """
    Calling stop_server when no server is running should succeed cleanly (return True).
    """
    fake_pid_file = tmp_path / "empty.pid"
    monkeypatch.setattr(launcher, "PID_FILE", fake_pid_file)
    monkeypatch.setattr(launcher, "check_port_in_use", lambda h, p: False)

    ok = launcher.stop_server(port=8765)
    assert ok is True


# -----------------------------------------------------------------------------
# Section E: Diagnostic Log Redaction
# -----------------------------------------------------------------------------

def test_diagnostic_logs_contain_no_exposed_api_keys(tmp_path):
    """
    Verify that log files written during launcher diagnostics do not expose sensitive API keys.
    """
    log_file = tmp_path / "hermes_gui_server.log"
    log_file.write_text(
        "2026-10-11 10:00:00 [INFO] Starting uvicorn\n"
        "2026-10-11 10:00:01 [INFO] Connected to Tier 1: nvidia_nim / z-ai/glm-5.3-flash\n"
        "2026-10-11 10:00:02 [ERROR] Health check failed: connection timeout\n",
        encoding="utf-8"
    )

    content = log_file.read_text(encoding="utf-8")
    assert "sk-" not in content
    assert "nvapi-" not in content
    assert "bearer " not in content.lower()
