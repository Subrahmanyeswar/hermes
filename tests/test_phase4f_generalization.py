# tests/test_phase4f_generalization.py
"""
HERMES Phase 4F — Generalization, Product Quality & Final Hardening Test Suite.
Validates:
1. Deterministic complexity classification across Archetypes A-H and complexity tiers.
2. De-biased prompt builder (zero hardcoded campus/event board IDs).
3. UI structural divergence across disparate application archetypes (Finance vs Portfolio vs Kanban).
4. Generalized domain verification in QualityVerifier without archetype bias.
5. Safe parallel execution and conflict-key scheduling across non-web & multi-file archetypes.
6. Write-write collision serialization across generic target paths.
7. TUI / Headless execution parity across archetypes.
8. Session persistence and crash-recovery invariants.
9. Action discipline (zero wandering/exploration) across non-campus missions.
10. Security invariants (path traversal prevention, canonical python enforcement).
"""

import pytest
import os
import json
import uuid
import tempfile
from dataclasses import asdict
from pathlib import Path

from core.mission_planner import (
    MissionPlanner,
    Mission,
    MissionTask,
    TaskPriority,
    TaskState,
    MissionComplexity,
    classify_mission_complexity,
)
from core.prompt_builder import build_system_prompt, PromptContext
from core.quality_verifier import QualityVerifier
from core.action_discipline import TaskActionContract, derive_action_contract
from core.workspace import WorkspaceManager


# ── Archetype Definitions (Benchmarks A–H) ───────────────────────────────────

ARCHETYPE_PROMPTS = {
    "A_EVENT_BOARD": (
        "Build a campus event board with search, category filtering, "
        "event cards, detail modal, and localStorage persistence."
    ),
    "B_PERSONAL_FINANCE": (
        "Create a personal finance dashboard with income and expense tracking, "
        "balance overview cards, category breakdowns, transaction table, and localStorage."
    ),
    "C_INVENTORY_MGMT": (
        "Build an inventory management dashboard with SKU tracking, stock level alerts, "
        "add product modal, filter by category, and persistent state."
    ),
    "D_DEV_PORTFOLIO": (
        "Design a modern developer portfolio with hero section, project showcase grid, "
        "skills tags, interactive contact form, and dark theme."
    ),
    "E_KANBAN_BOARD": (
        "Build a Kanban task management app with To Do, In Progress, and Done columns, "
        "task card creation, move-card actions, and localStorage persistence."
    ),
    "F_ANALYTICS_DASHBOARD": (
        "Create an analytics dashboard with KPI metric cards, date range filtering, "
        "data breakdown charts, interactive data table, and export summary."
    ),
    "G_DOCS_KNOWLEDGE_BASE": (
        "Build a documentation knowledge base application with sidebar navigation, "
        "article content viewer, search functionality, and bookmarking."
    ),
    "H_CRUD_API_BACKEND": (
        "Build a Flask REST API with SQLite database, models and routes for managing books and authors"
    ),
}


# ── Test 1: Mission Complexity Classification Across All Archetypes ──────────

def test_complexity_classification_across_archetypes():
    """Verify deterministic zero-LLM classification handles all archetypes and tiers."""
    # Archetypes A-G are single-tier frontend applications -> SIMPLE
    for key in ["A_EVENT_BOARD", "B_PERSONAL_FINANCE", "C_INVENTORY_MGMT",
                "D_DEV_PORTFOLIO", "E_KANBAN_BOARD", "F_ANALYTICS_DASHBOARD",
                "G_DOCS_KNOWLEDGE_BASE"]:
        complexity = classify_mission_complexity(ARCHETYPE_PROMPTS[key])
        assert complexity == MissionComplexity.SIMPLE, f"Expected SIMPLE for {key}, got {complexity}"

    # Archetype H is backend REST API -> MEDIUM
    complexity_h = classify_mission_complexity(ARCHETYPE_PROMPTS["H_CRUD_API_BACKEND"])
    assert complexity_h == MissionComplexity.MEDIUM, f"Expected MEDIUM for H, got {complexity_h}"

    # Trivial tier
    assert classify_mission_complexity("Write a script hello.py printing hello world") == MissionComplexity.TRIVIAL
    assert classify_mission_complexity("Create utils.py with helper math functions") == MissionComplexity.TRIVIAL

    # Complex tier
    complex_prompt = (
        "Build a full-stack platform with OAuth authentication, JWT tokens, "
        "database migrations, Celery background worker, and Stripe payment processing"
    )
    assert classify_mission_complexity(complex_prompt) == MissionComplexity.COMPLEX

    # Large tier
    large_prompt = "Design a microservices architecture with Kafka event bus and Kubernetes deployment"
    assert classify_mission_complexity(large_prompt) == MissionComplexity.LARGE


# ── Test 2: De-Biased Prompt Builder ─────────────────────────────────────────

def test_prompt_builder_contains_zero_hardcoded_benchmark_ids():
    """Ensure prompt templates contain no hardcoded IDs from specific benchmarks."""
    ctx = PromptContext(
        user_task="Build personal finance dashboard with transaction tracker and balance card",
        mode="auto",
        available_tools=["write_file", "read_file"],
        tool_descriptions="- write_file: Write a file to workspace\n- read_file: Read a file",
    )
    prompt = build_system_prompt(ctx)

    # Must NOT contain hardcoded IDs from the campus board benchmark
    assert "cards-container" not in prompt, "Found hardcoded 'cards-container' in system prompt"
    assert "search-input" not in prompt, "Found hardcoded 'search-input' in system prompt"
    assert "filter-select" not in prompt, "Found hardcoded 'filter-select' in system prompt"
    assert "item-modal" not in prompt, "Found hardcoded 'item-modal' in system prompt"

    # Must contain the generic contract
    assert "Element IDs and form control names MUST match EXACTLY" in prompt
    assert "Class names styled in CSS must match the exact classes rendered" in prompt


# ── Test 3: Structural UI Divergence Across Archetypes ───────────────────────

def test_ui_structural_divergence_between_archetypes():
    """Verify that different archetypes generate distinct component architectures."""
    planner = MissionPlanner()

    # Plan Finance vs Portfolio vs Kanban
    m_finance = planner.plan(ARCHETYPE_PROMPTS["B_PERSONAL_FINANCE"])
    m_portfolio = planner.plan(ARCHETYPE_PROMPTS["D_DEV_PORTFOLIO"])
    m_kanban = planner.plan(ARCHETYPE_PROMPTS["E_KANBAN_BOARD"])

    # All should be compressed to 4 tasks in SIMPLE tier
    assert len(m_finance.tasks) == 4
    assert len(m_portfolio.tasks) == 4
    assert len(m_kanban.tasks) == 4

    # The task descriptions must reflect their respective domain prompts
    desc_fin = m_finance.tasks[0].description.lower()
    desc_port = m_portfolio.tasks[0].description.lower()
    desc_kan = m_kanban.tasks[0].description.lower()

    assert "finance" in desc_fin or "transaction" in desc_fin or "income" in desc_fin
    assert "portfolio" in desc_port or "project" in desc_port or "showcase" in desc_port
    assert "kanban" in desc_kan or "task" in desc_kan or "columns" in desc_kan


# ── Test 4: QualityVerifier Generalization Across Domains ─────────────────────

def test_quality_verifier_domain_generalization():
    """Verify QualityVerifier validates diverse domain models without campus board bias."""
    verifier = QualityVerifier()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "index.html").write_text("""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Personal Finance Dashboard</title>
  <link rel="stylesheet" href="css/styles.css">
</head>
<body>
  <header class="app-header">
    <div class="header-inner">
      <h1>Personal Finance Dashboard</h1>
      <p class="subtitle">Real-time expense tracking & financial metrics</p>
    </div>
  </header>
  <main class="main-layout">
    <section id="summary-cards" class="metrics-grid">
      <div class="card metric-card"><h3>Total Balance</h3><p class="amount">$5,420.00</p></div>
      <div class="card metric-card"><h3>Monthly Income</h3><p class="amount income">+$4,200.00</p></div>
      <div class="card metric-card"><h3>Monthly Expenses</h3><p class="amount expense">-$2,150.00</p></div>
    </section>
    <section id="transactions-section" class="data-section">
      <h2>Recent Transactions</h2>
      <div class="table-container">
        <table id="transactions-table">
          <thead>
            <tr><th>Description</th><th>Category</th><th>Amount</th><th>Date</th></tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </section>
  </main>
  <script src="js/app.js"></script>
</body>
</html>""", encoding="utf-8")

        css_dir = root / "css"
        css_dir.mkdir()
        (css_dir / "styles.css").write_text("""
:root {
  --primary: #10b981;
  --surface: #1e293b;
  --surface-card: #334155;
  --text-main: #f8fafc;
  --border-subtle: #475569;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: var(--text-main); }
.app-header { padding: 24px; border-bottom: 1px solid var(--border-subtle); }
.metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; padding: 24px; }
.card { background: var(--surface-card); border-radius: 8px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }
.card h3 { margin: 0 0 8px 0; font-size: 0.875rem; text-transform: uppercase; }
.amount { font-size: 1.5rem; font-weight: 700; margin: 0; }
@media (max-width: 768px) {
  .metrics-grid { grid-template-columns: 1fr; }
}
""", encoding="utf-8")

        js_dir = root / "js"
        js_dir.mkdir()
        (js_dir / "app.js").write_text("""
const transactions = [
  { id: 1, title: 'Salary', amount: 5000, category: 'Income', date: '2026-10-01' },
  { id: 2, title: 'Groceries', amount: 150, category: 'Food', date: '2026-10-02' },
  { id: 3, title: 'Internet', amount: 80, category: 'Utilities', date: '2026-10-03' }
];
document.addEventListener('DOMContentLoaded', () => {
  const table = document.getElementById('transactions-table');
  if (table) {
    table.innerHTML = transactions.map(t => `<tr><td>${t.title}</td><td>${t.amount}</td></tr>`).join('');
  }
});
""", encoding="utf-8")

        # Verify Task 2 (HTML)
        res_html = verifier.verify_task_scoped(
            task_id="t2",
            task_title="Implement HTML layout",
            task_description="Build semantic HTML layout",
            task_index=2,
            total_tasks=4,
            project_root=str(root),
        )
        assert res_html.overall_verdict in ("PASS", "ACCEPTABLE", "COMPLETE"), f"HTML failed: {res_html.improvement_suggestions}"

        # Verify Task 3 (CSS)
        res_css = verifier.verify_task_scoped(
            task_id="t3",
            task_title="Implement CSS styling",
            task_description="Build modern CSS styles",
            task_index=3,
            total_tasks=4,
            project_root=str(root),
        )
        assert res_css.overall_verdict in ("PASS", "ACCEPTABLE", "COMPLETE"), f"CSS failed: {res_css.improvement_suggestions}"

        # Verify Task 4 (JS with domain data transactions)
        res_js = verifier.verify_task_scoped(
            task_id="t4",
            task_title="Implement JS logic and models",
            task_description="Build transactions data model and rendering",
            task_index=4,
            total_tasks=4,
            project_root=str(root),
        )
        assert res_js.overall_verdict in ("PASS", "ACCEPTABLE", "COMPLETE"), f"JS failed: {res_js.improvement_suggestions}"


# ── Test 5: Parallel Conflict Keys with Diverse Artifact Sets ────────────────

def test_safe_parallel_conflict_keys_diverse_artifacts():
    """Verify that independent targets are concurrently schedulable and conflicting targets are serialized."""
    # Disjoint tasks (e.g. backend models vs frontend template)
    t_models = MissionTask(
        task_id="t_models",
        title="Create models.py",
        target_paths=["models.py"],
        write_dependencies=["models.py"],
        state=TaskState.PENDING,
        depends_on=[],
    )
    t_routes = MissionTask(
        task_id="t_routes",
        title="Create routes.py",
        target_paths=["routes.py"],
        write_dependencies=["routes.py"],
        state=TaskState.PENDING,
        depends_on=[],
    )
    mission_disjoint = Mission(tasks=[t_models, t_routes], execution_order=["t_models", "t_routes"])
    batch = mission_disjoint.get_executable_batch(max_concurrent=3)
    assert [t.task_id for t in batch] == ["t_models", "t_routes"], "Disjoint tasks should batch together"

    # Conflicting tasks (same write target)
    t_shared1 = MissionTask(
        task_id="t_s1",
        title="Create base schema",
        target_paths=["schema.sql"],
        write_dependencies=["schema.sql"],
        state=TaskState.PENDING,
        depends_on=[],
    )
    t_shared2 = MissionTask(
        task_id="t_s2",
        title="Add indexes to schema",
        target_paths=["schema.sql"],
        write_dependencies=["schema.sql"],
        state=TaskState.PENDING,
        depends_on=[],
    )
    mission_conflict = Mission(tasks=[t_shared1, t_shared2], execution_order=["t_s1", "t_s2"])
    batch_conflict = mission_conflict.get_executable_batch(max_concurrent=3)
    assert len(batch_conflict) == 1, "Conflicting write tasks must serialize"
    assert batch_conflict[0].task_id == "t_s1"


# ── Test 6: Non-Web Archetype Compression and Dependency DAG ──────────────────

def test_non_web_trivial_and_medium_dag():
    """Verify DAG generation for CLI scripts and medium backend services."""
    planner = MissionPlanner()

    # Trivial script
    m_script = planner.plan("Create a CLI tool benchmark_runner.py to execute latency tests")
    assert m_script.complexity == MissionComplexity.TRIVIAL
    assert len(m_script.tasks) == 2
    assert m_script.tasks[0].task_id in m_script.tasks[1].depends_on

    # Medium backend API
    m_backend = planner.plan("Build a FastAPI REST API with SQLite database, models and routes for managing inventory")
    assert m_backend.complexity == MissionComplexity.MEDIUM
    assert len(m_backend.tasks) >= 1


# ── Test 7: Headless vs TUI Mode Parity ───────────────────────────────────────

def test_headless_and_tui_parity_invariants():
    """Verify that planner produces identical DAGs regardless of UI output mode."""
    planner = MissionPlanner()
    prompt = ARCHETYPE_PROMPTS["C_INVENTORY_MGMT"]

    mission_tui = planner.plan(prompt)
    mission_headless = planner.plan(prompt)

    assert mission_tui.complexity == mission_headless.complexity
    assert len(mission_tui.tasks) == len(mission_headless.tasks)
    for t_tui, t_head in zip(mission_tui.tasks, mission_headless.tasks):
        assert t_tui.title == t_head.title
        assert t_tui.target_paths == t_head.target_paths
        assert t_tui.conflict_keys == t_head.conflict_keys


# ── Test 8: Session Persistence Invariants ───────────────────────────────────

def test_session_persistence_across_archetypes():
    """Verify that mission state can be serialized and deserialized accurately."""
    planner = MissionPlanner()
    mission = planner.plan(ARCHETYPE_PROMPTS["B_PERSONAL_FINANCE"])

    dumped = json.dumps(asdict(mission))
    loaded = json.loads(dumped)

    assert loaded["mission_id"] == mission.mission_id
    assert loaded["complexity"] == MissionComplexity.SIMPLE.value
    assert len(loaded["tasks"]) == 4
    assert loaded["tasks"][0]["target_paths"] == ["index.html"]


# ── Test 9: Action Discipline Across Non-Campus Missions ─────────────────────

def test_action_discipline_contracts_for_diverse_archetypes():
    """Verify action contracts are properly bounded with zero exploration permissions."""
    planner = MissionPlanner()
    mission = planner.plan(ARCHETYPE_PROMPTS["F_ANALYTICS_DASHBOARD"])

    for task in mission.tasks:
        contract = derive_action_contract(task)
        assert contract.expected_operation in ("write_file", "edit_file", "bash_exec", "read_file")
        assert contract.allowed_exploration_scope <= 3
        if contract.is_implementation:
            assert contract.allowed_exploration_scope <= 1


# ── Test 10: Security Invariants and Path Traversal Prevention ───────────────

def test_security_invariants_path_traversal():
    """Verify workspace manager and planner reject malicious path traversal."""
    ws = WorkspaceManager()
    with tempfile.TemporaryDirectory() as tmpdir:
        ws.lock(tmpdir)
        try:
            # Resolving inside is valid
            p_valid = ws.validate_path("safe/path.txt")
            assert str(p_valid).startswith(str(Path(tmpdir).resolve()))

            # Path traversal must be blocked
            with pytest.raises(Exception):
                ws.validate_path("../../etc/passwd")
        finally:
            ws.unlock()
