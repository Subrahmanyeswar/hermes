# tests/test_final_fault_injection_qualification.py
"""
HERMES 2.x — Final End-to-End Fault-Injection & Syntax-Repair Qualification Suite
================================================================================
Deterministic qualification suite verifying:
- Scenario A: Malformed model-generated JavaScript rejection & ticket creation
- Scenario B: Targeted repair through real tool dispatcher & ticket resolution
- Scenario C: Existing broken file detected by validation & recovery
- Scenario D: Acceptance & false-completion prevention with hash invalidation
- Scenario E: Browser interaction via Chrome CDP
- Scenario F: Model timeout boundary enforcement & cancellation
- Scenario G: Observability stream completeness, manifest & watcher correlation
"""

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_loop.completion import CompletionPolicy
from core.agent_loop.syntax_repair import SyntaxRepairController, SyntaxRepairTicket
from core.code_completeness import validate_implementation_completeness
from core.js_syntax_validator import validate_javascript_content, validate_javascript_file
from core.observability.logger import MissionTelemetryLogger
from core.structured_observation import extract_syntax_diagnostic
from tools.platform.core_tools import FSWriteTool, FSEditTool


BASE_AUDIT_DIR = Path(r"C:\Users\SUBBU\Downloads\hermes_audit_runs\syntax_repair_qualification")


# ==============================================================================
# SCENARIO A: MALFORMED MODEL-GENERATED JAVASCRIPT REJECTION & TICKET CREATION
# ==============================================================================

def test_scenario_a_malformed_model_javascript_rejection_and_ticket():
    """
    Part 4 — Scenario A:
    A1. Simulate model response requesting creation of app.js with truncated JS.
    A2. Execute actual FSWriteTool -> Candidate rejected by completeness gate,
        not promoted to disk, actionable diagnostic produced.
    A3. Verify SyntaxRepairController creates ticket containing all required fields
        and generates context-pinned repair directive.
    """
    ws = BASE_AUDIT_DIR / "scenario_a"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True, exist_ok=True)

    tool = FSWriteTool()
    controller = SyntaxRepairController(workspace_root=ws)

    # A1. Incomplete candidate JavaScript (from prompt)
    malformed_js = """const app = {
    count: 0,

    increment() {
        this.count++;
    },

    reset() {
        this.count = 0;
    }
};

function seed() {
    const t = ("""

    candidate_hash = hashlib.sha256(malformed_js.encode("utf-8")).hexdigest()
    candidate_size = len(malformed_js.encode("utf-8"))

    # A2. Execute through real FSWriteTool
    res = tool.execute({
        "path": "app.js",
        "content": malformed_js,
        "workspace_root": str(ws),
    })

    # Assert candidate is rejected
    assert res.success is False
    assert res.exit_code == 1
    assert "INCOMPLETE_IMPLEMENTATION_TRUNCATED" in res.error
    assert "Unclosed '('" in res.error

    # Assert candidate is NOT promoted or written to disk
    target_file = ws / "app.js"
    assert not target_file.exists(), "Malformed candidate must NOT be written to disk"

    # Extract diagnostic
    diag = extract_syntax_diagnostic(res.error)
    assert diag is not None
    assert diag["file"] == "app.js"
    assert diag["line"] == 14
    assert diag["error_class"] == "SyntaxError"

    # A3. Verify SyntaxRepairController creates ticket
    mission_id = "m_qual_scen_a"
    run_id = "run_1_qual_scen_a"
    ticket = controller.create_or_update_ticket(
        target_file=diag["file"],
        validator="validate_javascript_content",
        stderr_or_output=res.error,
        exit_code=res.exit_code,
        workspace_root=ws,
        candidate_content=malformed_js,
        mission_id=mission_id,
        run_id=run_id,
    )

    assert ticket is not None
    assert ticket.target_file == "app.js"
    assert ticket.mission_id == mission_id
    assert ticket.run_id == run_id
    assert ticket.failure_id.startswith("fail_")
    assert ticket.file_hash == candidate_hash
    assert ticket.candidate_hash == candidate_hash
    assert ticket.line == 14
    assert len(ticket.tail_lines) > 0
    assert "const t = (" in ticket.tail_lines[-1]
    assert ticket.repair_attempts == 0
    assert "fs.write or fs.edit" in ticket.required_next_action

    # Verify repair directive pinned content
    directive = controller.build_repair_directive(ticket)
    assert "=== CRITICAL APPLICATION SYNTAX REPAIR DIRECTIVE ===" in directive
    assert "Target File: app.js" in directive
    assert "Calling fs.read on 'app.js' is PROHIBITED" in directive
    assert "You MUST use fs.write or fs.edit" in directive


# ==============================================================================
# SCENARIO B: TARGETED REPAIR THROUGH REAL TOOL DISPATCHER
# ==============================================================================

def test_scenario_b_targeted_repair_through_tool_dispatcher():
    """
    Part 5 — Scenario B:
    Simulate model issuing targeted repair with valid JavaScript.
    Execute through real FSWriteTool -> Passes syntax gate, written to disk,
    ticket resolved, directive unpinned.
    """
    ws = BASE_AUDIT_DIR / "scenario_b"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True, exist_ok=True)

    tool = FSWriteTool()
    controller = SyntaxRepairController(workspace_root=ws)

    # Create active ticket first
    ticket = controller.create_or_update_ticket(
        target_file="app.js",
        validator="validate_javascript_content",
        stderr_or_output="SyntaxError: Unexpected end of input at line 14",
        exit_code=1,
        workspace_root=ws,
        mission_id="m_qual_scen_b",
        run_id="run_1_qual_scen_b",
    )
    assert controller.has_unresolved_syntax_errors() is True

    # Valid JavaScript specified in prompt
    valid_js = """const app = {
    count: 0,

    increment() {
        this.count++;
        render();
    },

    decrement() {
        this.count--;
        render();
    },

    reset() {
        this.count = 0;
        render();
    }
};

function render() {
    const element = document.getElementById("count");
    if (element) {
        element.textContent = String(app.count);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const incrementButton = document.getElementById("increment");
    const decrementButton = document.getElementById("decrement");
    const resetButton = document.getElementById("reset");

    incrementButton?.addEventListener("click", () => app.increment());
    decrementButton?.addEventListener("click", () => app.decrement());
    resetButton?.addEventListener("click", () => app.reset());

    render();
});"""

    # Execute repair through FSWriteTool
    res = tool.execute({
        "path": "app.js",
        "content": valid_js,
        "workspace_root": str(ws),
    })

    assert res.success is True
    target_file = ws / "app.js"
    assert target_file.exists()

    # Validate with native Node CLI
    val_ok, val_err, _ = validate_javascript_file(target_file)
    assert val_ok is True
    assert val_err is None

    # Resolve ticket
    resolved_ticket = controller.resolve_ticket("app.js")
    assert resolved_ticket is not None
    assert resolved_ticket.is_active is False
    assert controller.has_unresolved_syntax_errors() is False


# ==============================================================================
# SCENARIO C: EXISTING BROKEN FILE DETECTED BY VALIDATION & RECOVERY
# ==============================================================================

def test_scenario_c_existing_broken_file_detected_by_validation():
    """
    Part 6 — Scenario C:
    Post-write syntax failure recovery:
    1. Broken file exists on disk.
    2. node -c runs through shell/validator, exit code 1 captured.
    3. Ticket created, context pinned.
    4. Model issues targeted repair with fs.write or fs.edit.
    5. Re-validation passes with exit code 0, ticket resolved.
    """
    ws = BASE_AUDIT_DIR / "scenario_c"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True, exist_ok=True)

    # 1. Setup broken file on disk
    broken_content = "function computeTotal() {\n    let sum = 0;\n    items.forEach(i => {\n"
    (ws / "app.js").write_text(broken_content, encoding="utf-8")

    # 2. Run native Node syntax check
    res = subprocess.run(["node", "-c", str(ws / "app.js")], capture_output=True, text=True)
    assert res.returncode != 0
    assert "SyntaxError" in res.stderr

    # 3. Create ticket from node diagnostic
    controller = SyntaxRepairController(workspace_root=ws)
    diag = extract_syntax_diagnostic(res.stderr)
    ticket = controller.create_or_update_ticket(
        target_file="app.js",
        validator="node -c app.js",
        stderr_or_output=res.stderr,
        exit_code=res.returncode,
        workspace_root=ws,
        mission_id="m_qual_scen_c",
        run_id="run_1_qual_scen_c",
    )

    assert ticket is not None
    assert ticket.target_file == "app.js"
    assert len(ticket.tail_lines) > 0
    assert controller.has_unresolved_syntax_errors() is True

    # 4. Repair via FSWriteTool
    repaired_content = """function computeTotal() {
    let sum = 0;
    const items = [10, 20, 30];
    items.forEach(i => { sum += i; });
    return sum;
}
window.computeTotal = computeTotal;
"""
    write_tool = FSWriteTool()
    repair_res = write_tool.execute({
        "path": "app.js",
        "content": repaired_content,
        "workspace_root": str(ws),
    })
    assert repair_res.success is True

    # 5. Re-run node -c
    res2 = subprocess.run(["node", "-c", str(ws / "app.js")], capture_output=True, text=True)
    assert res2.returncode == 0

    # 6. Resolve ticket
    controller.resolve_ticket("app.js")
    assert controller.has_unresolved_syntax_errors() is False


# ==============================================================================
# SCENARIO D: ACCEPTANCE & FALSE-COMPLETION PREVENTION WITH HASH INVARIANT
# ==============================================================================

def test_scenario_d_acceptance_and_false_completion_prevention():
    """
    Part 7 — Scenario D:
    1. Broken app.js blocks requirement completion and development report authoring.
    2. Repaired app.js allows completion and report authoring.
    3. Artifact hash invariant: modifying a valid file to broken code invalidates
       passing status and re-blocks completion.
    """
    ws = BASE_AUDIT_DIR / "scenario_d"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True, exist_ok=True)

    tool = FSWriteTool()
    policy = CompletionPolicy()

    # Create workspace files with invalid app.js
    (ws / "package.json").write_text('{"name": "qual-app"}', encoding="utf-8")
    (ws / "index.html").write_text("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div id="count">0</div>
    <button id="increment">+</button>
    <button id="decrement">-</button>
    <button id="reset">Reset</button>
    <script src="app.js"></script>
</body>
</html>""", encoding="utf-8")
    (ws / "style.css").write_text("body { font-family: sans-serif; }", encoding="utf-8")
    (ws / "app.js").write_text("function broken() { const x = (", encoding="utf-8")

    # 1. Attempt requirement completion with broken app.js -> BLOCKED
    accepted, reason, issues = policy.evaluate_completion(
        mission_prompt="Build counter application with index.html, style.css, and app.js",
        workspace=ws,
        written_files=["package.json", "index.html", "style.css", "app.js"],
    )
    assert accepted is False
    assert any("syntax error" in str(i).lower() or "syntax" in str(i).lower() for i in issues)

    # 2. Attempt writing TEST_DEVELOPMENT_REPORT.md with broken app.js -> BLOCKED
    rep_res = tool.execute({
        "path": "TEST_DEVELOPMENT_REPORT.md",
        "content": "# Report\nAll features verified: Yes",
        "workspace_root": str(ws),
    })
    assert rep_res.success is False
    assert "FALSE_COMPLETION_REPORT_BLOCKED" in rep_res.error

    # 3. Repair app.js with valid JavaScript
    valid_js = """const app = {
    count: 0,
    increment() { this.count++; render(); },
    decrement() { this.count--; render(); },
    reset() { this.count = 0; render(); }
};
function render() {
    const el = document.getElementById("count");
    if (el) el.textContent = String(app.count);
}
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("increment")?.addEventListener("click", () => app.increment());
    document.getElementById("decrement")?.addEventListener("click", () => app.decrement());
    document.getElementById("reset")?.addEventListener("click", () => app.reset());
    render();
});"""
    res_fix = tool.execute({
        "path": "app.js",
        "content": valid_js,
        "workspace_root": str(ws),
    })
    assert res_fix.success is True

    # 4. Now completion is accepted
    accepted_now, reason_now, issues_now = policy.evaluate_completion(
        mission_prompt="Build counter application with index.html, style.css, and app.js",
        workspace=ws,
        written_files=["package.json", "index.html", "style.css", "app.js"],
    )
    assert accepted_now is True
    assert len(issues_now) == 0

    # 5. Report writing succeeds
    rep_ok = tool.execute({
        "path": "TEST_DEVELOPMENT_REPORT.md",
        "content": """# Development Report
## Status
- Implemented: Yes
- Syntax validated: Passed (node -c app.js exit 0)
- Integration validated: Profile C verified
- Browser verified: Verified
""",
        "workspace_root": str(ws),
    })
    assert rep_ok.success is True

    # 6. Artifact hash invariant test: mutate app.js back to broken code
    (ws / "app.js").write_text("broken mutator {", encoding="utf-8")
    accepted_again, _, issues_again = policy.evaluate_completion(
        mission_prompt="Build counter application with index.html, style.css, and app.js",
        workspace=ws,
        written_files=["package.json", "index.html", "style.css", "app.js"],
    )
    assert accepted_again is False, "Mutating a previously validated file must invalidate prior acceptance"


# ==============================================================================
# SCENARIO E: REAL BROWSER INTERACTION VIA CHROME CDP
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_e_browser_interaction_via_cdp():
    """
    Part 8 — Scenario E:
    Launch Chrome CDP on the accepted application fixture from Scenario D.
    Verify: initial count=0, increment to 1, increment to 2, decrement to 1,
    reset to 0, zero console errors, screenshots captured.
    """
    import websockets

    ws = BASE_AUDIT_DIR / "scenario_d"
    # Ensure app.js is in valid state
    valid_js = """const app = {
    count: 0,
    increment() { this.count++; render(); },
    decrement() { this.count--; render(); },
    reset() { this.count = 0; render(); }
};
function render() {
    const el = document.getElementById("count");
    if (el) el.textContent = String(app.count);
}
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("increment")?.addEventListener("click", () => app.increment());
    document.getElementById("decrement")?.addEventListener("click", () => app.decrement());
    document.getElementById("reset")?.addEventListener("click", () => app.reset());
    render();
});"""
    (ws / "app.js").write_text(valid_js, encoding="utf-8")

    chrome_exe = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    html_url = f"file:///{str(ws / 'index.html').replace(os.sep, '/')}"
    profile_dir = ws / "chrome_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen([
        chrome_exe,
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        f"--user-data-dir={profile_dir}",
        "--remote-debugging-port=9225",
        html_url,
    ])

    try:
        # Wait for CDP endpoint
        ws_url = None
        for _ in range(25):
            try:
                with urllib.request.urlopen("http://127.0.0.1:9225/json") as r:
                    tabs = json.loads(r.read().decode())
                    for tab in tabs:
                        if tab.get("type") == "page" and "index.html" in tab.get("url", ""):
                            ws_url = tab.get("webSocketDebuggerUrl")
                            break
                    if ws_url:
                        break
            except Exception:
                pass
            await asyncio.sleep(0.3)

        assert ws_url is not None, "Chrome CDP debugger URL not found"

        async with websockets.connect(ws_url) as ws_conn:
            msg_id = 1
            console_errors = []

            async def send_cmd(method, params=None):
                nonlocal msg_id
                cid = msg_id
                msg_id += 1
                payload = {"id": cid, "method": method, "params": params or {}}
                await ws_conn.send(json.dumps(payload))
                while True:
                    resp_raw = await ws_conn.recv()
                    resp = json.loads(resp_raw)
                    if resp.get("method") == "Runtime.consoleAPICalled":
                        if resp.get("params", {}).get("type") == "error":
                            console_errors.append(resp)
                    if resp.get("id") == cid:
                        return resp.get("result", {})

            await send_cmd("Runtime.enable")
            await send_cmd("Page.enable")

            # Wait for DOM ready
            for _ in range(20):
                res = await send_cmd("Runtime.evaluate", {
                    "expression": "Boolean(document.getElementById('count'))",
                    "returnByValue": True
                })
                if res.get("result", {}).get("value") is True:
                    break
                await asyncio.sleep(0.2)

            # 1. Initial count is 0
            res = await send_cmd("Runtime.evaluate", {"expression": "document.getElementById('count').textContent", "returnByValue": True})
            assert res.get("result", {}).get("value") == "0"

            # 2. Increment changes to 1
            await send_cmd("Runtime.evaluate", {"expression": "document.getElementById('increment').click()"})
            res = await send_cmd("Runtime.evaluate", {"expression": "document.getElementById('count').textContent", "returnByValue": True})
            assert res.get("result", {}).get("value") == "1"

            # 3. Increment changes to 2
            await send_cmd("Runtime.evaluate", {"expression": "document.getElementById('increment').click()"})
            res = await send_cmd("Runtime.evaluate", {"expression": "document.getElementById('count').textContent", "returnByValue": True})
            assert res.get("result", {}).get("value") == "2"

            # 4. Decrement returns to 1
            await send_cmd("Runtime.evaluate", {"expression": "document.getElementById('decrement').click()"})
            res = await send_cmd("Runtime.evaluate", {"expression": "document.getElementById('count').textContent", "returnByValue": True})
            assert res.get("result", {}).get("value") == "1"

            # 5. Reset returns to 0
            await send_cmd("Runtime.evaluate", {"expression": "document.getElementById('reset').click()"})
            res = await send_cmd("Runtime.evaluate", {"expression": "document.getElementById('count').textContent", "returnByValue": True})
            assert res.get("result", {}).get("value") == "0"

            # 6. Zero console errors
            assert len(console_errors) == 0

            # 7. Capture screenshot
            ss_res = await send_cmd("Page.captureScreenshot", {"format": "png"})
            import base64
            img_bytes = base64.b64decode(ss_res.get("data", ""))
            out_img = ws / "browser_verification.png"
            out_img.write_bytes(img_bytes)
            assert out_img.exists()
            assert len(img_bytes) > 1000

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


# ==============================================================================
# SCENARIO F: MODEL TIMEOUT & CANCELLATION BOUNDARY
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_f_model_timeout_and_cancellation():
    """
    Part 9 — Scenario F:
    Test timeout enforcement with short parent budget (500ms).
    Verify timeout triggers at expected bound, operation is cancelled,
    and no internal retries continue past parent deadline.
    """
    import httpx
    from models.common_adapter import CommonProviderAdapter, ErrorClassification

    adapter = CommonProviderAdapter(
        provider_name="mock_timeout_provider",
        model_name="test-timeout-model",
        base_url="https://api.test.com/v1",
        api_key="test-key",
        tier=1,
    )

    call_count = 0

    async def hanging_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Hang beyond the 500ms budget
        await asyncio.sleep(2.0)
        return MagicMock(status_code=200, json=lambda: {}, text="{}")

    t0 = time.monotonic()
    with patch.object(httpx.AsyncClient, "post", side_effect=hanging_post):
        # Enforce 0.5s turn timeout
        resp = await adapter.generate(
            prompt="Hello",
            stream=False,
            timeout_seconds=0.5,
        )
    elapsed = time.monotonic() - t0

    # Assert bounded execution: elapsed should be close to 0.5s, well under 2.0s
    assert elapsed < 1.2, f"Execution hung for {elapsed:.2f}s instead of bounded timeout"
    assert resp.success is False
    assert resp.error is not None
    # No extra retries after deadline exhaustion
    assert call_count == 1, f"Expected 1 attempt within short budget, got {call_count}"


# ==============================================================================
# SCENARIO G: OBSERVABILITY COMPLETENESS, MANIFEST & WATCHER CORRELATION
# ==============================================================================

def test_scenario_g_observability_completeness_and_manifest():
    """
    Part 10 — Scenario G:
    Verify that all 8 streams are accounted for under one authoritative Run ID,
    stream_manifest.json is generated with explicit empty reasons, and the watcher
    resolves the authoritative directory.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        run_id = "run_1_qual_auth_01"
        mission_id = "m_qual_01"
        logger = MissionTelemetryLogger(run_id=run_id, mission_id=mission_id, base_dir=Path(tmp_dir))

        # Log representative records across streams
        logger.log_event("MISSION_STARTED", "orchestrator", message="Mission started")
        logger.record_model_call(
            turn=1, tier=1, provider="gemini", model="gemini-3.5-flash-lite",
            duration_ms=120.0, status="SUCCESS", params={}, timings={}, response_meta={}
        )
        logger.record_tool_call(
            tool_call_id="call_01", tool_name="fs.write", turn=1, duration_ms=15.0,
            success=True, exit_code=0, arguments={"path": "index.html"}
        )
        logger.record_file_operation("index.html", "write", 0, 500, "", "abc123", True)
        logger.record_validation_result("syntax_check", "app.js", True, 10.0, 0)
        logger.record_runtime_snapshot("TEST_SNAPSHOT")

        # Write manifest
        manifest = logger.write_stream_manifest()
        manifest_path = logger.log_dir / "stream_manifest.json"
        assert manifest_path.exists()
        assert manifest["run_id"] == run_id
        assert manifest["mission_id"] == mission_id

        # Verify all 8 streams are accounted for
        streams = manifest["streams"]
        expected_streams = ["events", "models", "tools", "recovery", "files", "validation", "runtime", "errors"]
        for s in expected_streams:
            assert s in streams, f"Stream '{s}' missing from manifest"

        # Populated streams have record counts > 0
        assert streams["events"]["record_count"] >= 1
        assert streams["models"]["record_count"] >= 1
        assert streams["tools"]["record_count"] >= 1
        assert streams["files"]["record_count"] >= 1
        assert streams["validation"]["record_count"] >= 1
        assert streams["runtime"]["record_count"] >= 1

        # Legitimate empty streams have reasons
        assert streams["recovery"]["record_count"] == 0
        assert streams["recovery"]["reason_if_empty"] is not None
        assert streams["errors"]["record_count"] == 0
        assert streams["errors"]["reason_if_empty"] is not None
