# tests/test_prompt17_flagship_frontend.py
"""
Flagship End-to-End Frontend Qualification Suite (Prompt 17).

Validates the full closed-loop frontend engineering pipeline:
1. Local Development Server Lifecycle.
2. Live Browser Automation & DOM Interaction.
3. Reload Persistence Verification (Outcome-First Durability).
4. Multi-Viewport Responsive Validation (Desktop, Tablet, Mobile).
5. Rubric & Backstop Visual Quality Evaluation.
6. Intentional Defect Injection & Ground-Truth Failure Attribution:
   - Defect A: In-memory only state (Fails reload durability).
   - Defect B: Fixed-width overflow (Fails mobile responsive backstop).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from core.browser.dev_server import DevServerManager
from core.browser.manager import BrowserManager
from core.evaluation.functional.evaluator import FunctionalEvaluator
from core.evaluation.functional.models import (
    CheckLayer,
    CheckStatus,
    FunctionalCheck,
    FunctionalRequirement,
)
from core.evaluation.visual.evaluator import VisualEvaluator
from core.evaluation.visual.models import VisualCategory, VisualCheckStatus


# ── Synthetic Dashboard Fixtures ──────────────────────────────────────────────

VALID_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Transaction Dashboard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #1e293b; padding: 1.5rem; max-width: 100%; overflow-x: hidden; }
    .container { max-width: 800px; margin: 0 auto; background: #ffffff; border-radius: 8px; padding: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    h1 { font-size: 1.5rem; margin-bottom: 1rem; color: #0f172a; }
    .form-group { display: flex; gap: 0.5rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
    input { padding: 0.5rem 0.75rem; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 1rem; flex: 1; min-width: 120px; }
    button { padding: 0.5rem 1rem; background: #2563eb; color: #ffffff; border: none; border-radius: 4px; font-size: 1rem; cursor: pointer; font-weight: 500; }
    button:hover { background: #1d4ed8; }
    table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
    th, td { text-align: left; padding: 0.75rem; border-bottom: 1px solid #e2e8f0; }
    th { background: #f1f5f9; font-weight: 600; }
    @media (max-width: 600px) {
      body { padding: 0.75rem; }
      .container { padding: 1rem; }
      .form-group { flex-direction: column; }
      button { width: 100%; }
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>Transaction Dashboard</h1>
    <div class="form-group">
      <input type="text" id="desc-input" placeholder="Description" aria-label="Description" />
      <input type="number" id="amount-input" placeholder="Amount" aria-label="Amount" />
      <button id="add-btn" type="button">Add Transaction</button>
    </div>
    <table>
      <thead>
        <tr><th>Description</th><th>Amount</th></tr>
      </thead>
      <tbody id="tx-body">
      </tbody>
    </table>
  </div>
  <script>
    const STORAGE_KEY = 'hermes_tx_data';
    function loadTransactions() {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : [];
    }
    function saveTransactions(items) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    }
    function render() {
      const items = loadTransactions();
      const tbody = document.getElementById('tx-body');
      tbody.innerHTML = '';
      items.forEach(it => {
        const tr = document.createElement('tr');
        tr.className = 'tx-row';
        tr.innerHTML = `<td>${it.desc}</td><td>$${it.amount}</td>`;
        tbody.appendChild(tr);
      });
    }
    document.getElementById('add-btn').addEventListener('click', () => {
      const desc = document.getElementById('desc-input').value.trim();
      const amount = document.getElementById('amount-input').value.trim();
      if (!desc || !amount) return;
      const items = loadTransactions();
      items.push({ desc, amount });
      saveTransactions(items);
      document.getElementById('desc-input').value = '';
      document.getElementById('amount-input').value = '';
      render();
    });
    // Initial render from persistent storage
    window.addEventListener('DOMContentLoaded', render);
  </script>
</body>
</html>
"""

# Defect 1: State kept ONLY in memory, lost on page reload
FLAWED_VOLATILE_HTML = VALID_DASHBOARD_HTML.replace(
    "function loadTransactions() {\n      const raw = localStorage.getItem(STORAGE_KEY);\n      return raw ? JSON.parse(raw) : [];\n    }",
    "let _inMemory = [];\n    function loadTransactions() { return _inMemory; }"
).replace(
    "function saveTransactions(items) {\n      localStorage.setItem(STORAGE_KEY, JSON.stringify(items));\n    }",
    "function saveTransactions(items) { _inMemory = items; }"
)

# Defect 2: Rigid 1400px width causing severe mobile overflow
FLAWED_OVERFLOW_HTML = VALID_DASHBOARD_HTML.replace(
    ".container { max-width: 800px; margin: 0 auto; background: #ffffff; border-radius: 8px; padding: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }",
    ".container { width: 1400px; min-width: 1400px; margin: 0 auto; background: #ffffff; padding: 1.5rem; }"
)


# ── Test Cases ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flagship_dashboard_happy_path():
    """
    Validate complete end-to-end frontend evaluation lifecycle:
    Server launch -> Navigation -> Interaction -> Reload Durability -> Multi-Viewport Responsive -> Rubric Evaluation.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_root = Path(tmpdir).resolve()
        index_file = ws_root / "index.html"
        index_file.write_text(VALID_DASHBOARD_HTML, encoding="utf-8")

        dev_servers = DevServerManager()
        server_info = await dev_servers.start_static_server(ws_root)
        assert server_info.is_alive

        browser = BrowserManager(prefer_cdp=False)
        await browser.launch()

        try:
            # 1. Navigation
            nav_res = await browser.navigate(server_info.url)
            assert nav_res.success is True
            assert "Transaction Dashboard" in nav_res.title

            # 2. Interaction: Add a transaction
            await browser.type_text("#desc-input", "Hosting Server")
            await browser.type_text("#amount-input", "75")
            await browser.click("#add-btn")

            # Verify row in DOM
            inspect1 = await browser.inspect()
            assert any("Hosting Server" in el.text for el in inspect1.elements)

            # 3. Reload Persistence Test (Durability)
            await browser.navigate(server_info.url)
            inspect2 = await browser.inspect()
            persisted = any("Hosting Server" in el.text for el in inspect2.elements)
            assert persisted is True, "State must survive page reload via localStorage"

            # 4. Visual Rubric & Responsive Evaluation
            vis_eval = VisualEvaluator(browser_manager=browser)
            vis_result = await vis_eval.evaluate_page("flagship_happy_path")

            assert vis_result.overall_status == VisualCheckStatus.PASS
            assert vis_result.overall_score >= 0.70
            assert len(vis_result.deterministic_issues) == 0

            # Verify all viewports passed without horizontal overflow
            for r in vis_result.responsive_results:
                assert r.has_horizontal_overflow is False, f"Overflow in {r.viewport_name}"

        finally:
            await browser.close()
            dev_servers.stop_all()
            import time
            time.sleep(0.2)


@pytest.mark.asyncio
async def test_flagship_dashboard_durability_defect_detection():
    """
    Verify FunctionalEvaluator detects lost state across reload
    and generates structured repair findings for T1.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_root = Path(tmpdir).resolve()
        index_file = ws_root / "index.html"
        index_file.write_text(FLAWED_VOLATILE_HTML, encoding="utf-8")

        dev_servers = DevServerManager()
        server_info = await dev_servers.start_static_server(ws_root)

        browser = BrowserManager(prefer_cdp=False)
        await browser.launch()

        try:
            # Navigate and add data
            await browser.navigate(server_info.url)
            await browser.type_text("#desc-input", "Salary")
            await browser.type_text("#amount-input", "5000")
            await browser.click("#add-btn")

            # Reload
            await browser.navigate(server_info.url)

            # Functional requirement check
            req = FunctionalRequirement(
                req_id="req_durability",
                title="Transaction Persistence Requirement",
                description="Transaction data must persist across reload",
                checks=[
                    FunctionalCheck(
                        check_id="chk_persisted_row",
                        name="Verify row exists after reload",
                        layer=CheckLayer.PERSISTENCE,
                        expected="Salary",
                    )
                ]
            )

            evaluator = FunctionalEvaluator(workspace_root=ws_root, browser_manager=browser)

            res = await evaluator.evaluate_suite("flagship_durability_test", [req])

            # Must FAIL because state was in-memory only
            assert res.status == CheckStatus.FAIL
            assert res.failed_checks >= 1
            assert len(res.findings) >= 1

            finding = res.findings[0]
            reason = (finding.get("failure_reason") or "").lower()
            actual = (finding.get("actual") or "").lower()
            assert "persisted" in reason or "lost" in actual or "missing" in reason

        finally:
            await browser.close()
            dev_servers.stop_all()
            import time
            time.sleep(0.2)


@pytest.mark.asyncio
async def test_flagship_dashboard_mobile_overflow_defect_detection():
    """
    Verify VisualEvaluator catches mobile horizontal overflow defect
    and records failure in responsive backstop.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_root = Path(tmpdir).resolve()
        index_file = ws_root / "index.html"
        index_file.write_text(FLAWED_OVERFLOW_HTML, encoding="utf-8")

        dev_servers = DevServerManager()
        server_info = await dev_servers.start_static_server(ws_root)

        browser = BrowserManager(prefer_cdp=False)
        await browser.launch()

        try:
            await browser.navigate(server_info.url)

            vis_eval = VisualEvaluator(browser_manager=browser)
            vis_result = await vis_eval.evaluate_page("flagship_overflow_test")

            # Must detect mobile overflow failure
            assert vis_result.overall_status == VisualCheckStatus.FAIL or any(
                r.has_horizontal_overflow for r in vis_result.responsive_results
            )

            # Mobile viewport check specifically must record overflow
            mobile_checks = [r for r in vis_result.responsive_results if r.viewport_name == "mobile"]
            assert len(mobile_checks) == 1
            assert mobile_checks[0].has_horizontal_overflow is True

        finally:
            await browser.close()
            dev_servers.stop_all()
            import time
            time.sleep(0.2)
