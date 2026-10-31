"""
Golden Scenarios Validation Suite for HERMES Phase 2 Core Runtime Repair.
Validates Scenarios A, B, C, and D as mandated by PART W.
"""

import os
import shutil
import tempfile
from pathlib import Path
import pytest
from unittest.mock import MagicMock, AsyncMock

from core.mission_planner import MissionPlanner, MissionTask, TaskState, TaskPriority, Mission
from core.mission_runner import MissionRunner
from core.workspace import WorkspaceManager, workspace_manager
from core.architecture_lock import ArchitectureLock, ArchitectureType, ArchitectureDecision
from core.agent_loop.behavioral_verifier import TechnologyAwareBehavioralVerifier
from core.verifier import VerificationResult
from core.disagreement_router import DisagreementRouter
from tools.platform.core_tools import FSWriteTool, FSReadTool, FSEditTool, ToolErrorCode
from tools.file_tools import WriteFileTool, ReadFileTool


@pytest.fixture
def clean_workspace():
    tmp_dir = tempfile.mkdtemp(prefix="hermes_golden_")
    ws_path = Path(tmp_dir)
    workspace_manager.lock(str(ws_path))
    yield ws_path
    workspace_manager.unlock()
    shutil.rmtree(tmp_dir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario A: Clean Disposable Workspace - Small Website Generation
# ─────────────────────────────────────────────────────────────────────────────
def test_scenario_a_clean_workspace_small_website(clean_workspace: Path):
    """
    Scenario A:
    1. Plan contains <= 6 tasks with strict semantic roles and topological ordering.
    2. Verification task has LOW priority and depends on implementation tasks.
    3. Files created in root without path drift.
    4. Verification barrier prevents premature execution.
    5. Full behavioral verification passes.
    """
    planner = MissionPlanner()
    mission = planner.plan(
        "Create a campus lost-and-found application:\n"
        "1. Scaffold project index.html\n"
        "2. Add styles in styles.css\n"
        "3. Implement search in app.js\n"
        "4. Behavioral test and verification"
    )

    # 1. Bounded task count
    assert len(mission.tasks) <= 6

    # 2. Semantic role assignment & verification barrier
    verification_tasks = [t for t in mission.tasks if t.is_verification_task]
    assert len(verification_tasks) >= 1
    v_task = verification_tasks[0]
    assert len(v_task.depends_on) > 0

    # Verification must NOT be executable while implementation tasks are pending
    next_task = mission.next_executable_task
    assert next_task is not None
    assert not next_task.is_verification_task

    # 3. Write files directly to root (no generated_projects prefix drift)
    write_tool = WriteFileTool()
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Campus Lost & Found</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <h1>Campus Lost & Found</h1>
  <form id="item-form">
    <input type="text" id="item-title" placeholder="Item name" required>
    <button type="submit">Submit</button>
  </form>
  <input type="text" id="search-bar" placeholder="Search...">
  <ul id="items-list"></ul>
  <script src="app.js"></script>
</body>
</html>"""

    css_content = """body { font-family: sans-serif; margin: 20px; }
#items-list { list-style: none; padding: 0; }
.item-card { padding: 10px; border: 1px solid #ccc; margin-bottom: 8px; }"""

    js_content = """document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('item-form');
  const list = document.getElementById('items-list');
  const search = document.getElementById('search-bar');
  let items = JSON.parse(localStorage.getItem('lost_items') || '[]');

  function render(query = '') {
    list.innerHTML = '';
    items.filter(i => i.title.toLowerCase().includes(query.toLowerCase())).forEach(item => {
      const li = document.createElement('li');
      li.className = 'item-card';
      li.textContent = item.title;
      list.appendChild(li);
    });
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const title = document.getElementById('item-title').value;
    items.push({ title });
    localStorage.setItem('lost_items', JSON.stringify(items));
    render();
    form.reset();
  });

  search.addEventListener('input', (e) => render(e.target.value));
  render();
});"""

    r_html = write_tool.execute(WriteFileTool.Input(path="index.html", content=html_content, mode="create"))
    assert r_html.success
    r_css = write_tool.execute(WriteFileTool.Input(path="styles.css", content=css_content, mode="create"))
    assert r_css.success
    r_js = write_tool.execute(WriteFileTool.Input(path="app.js", content=js_content, mode="create"))
    assert r_js.success

    # Verify no generated_projects folder created
    assert not (clean_workspace / "generated_projects").exists()
    assert (clean_workspace / "index.html").exists()

    # 4. Behavioral verification passes on the completed application
    v_res = TechnologyAwareBehavioralVerifier.verify_vanilla_web(
        ws_root=clean_workspace,
        mission_prompt="Create a campus lost-and-found website with search, filter, and persistence",
    )
    assert v_res.passed, f"Behavioral verification failed: {v_res.issues}"


# ─────────────────────────────────────────────────────────────────────────────
# Scenario B: Existing Workspace Feature Addition
# ─────────────────────────────────────────────────────────────────────────────
def test_scenario_b_existing_workspace_feature_addition(clean_workspace: Path):
    """
    Scenario B:
    1. Pre-existing files in workspace.
    2. Overwrite protection prevents blind overwriting.
    3. Read-before-edit requirement is enforced.
    4. Freshness cache ensures edits succeed only after reading.
    5. Targeted feature added safely.
    """
    # Setup pre-existing project
    cfg_file = clean_workspace / "config.json"
    cfg_file.write_text('{\n  "theme": "light",\n  "version": "1.0.0"\n}\n', encoding="utf-8")

    # 1. Blind overwrite rejected
    fs_write = FSWriteTool()
    blind_res = fs_write.execute({
        "_workspace": None,
        "path": "config.json",
        "content": '{\n  "theme": "dark"\n}\n',
        "allow_overwrite": False,
    })
    assert not blind_res.success
    assert "ALREADY_EXISTS" in blind_res.error or "FILE_EXISTS_OVERWRITE_REQUIRED" in blind_res.error

    # 2. Blind edit rejected without prior read
    fs_edit = FSEditTool()
    blind_edit = fs_edit.execute({
        "_workspace": None,
        "path": "config.json",
        "old_string": '"theme": "light"',
        "new_string": '"theme": "dark"',
        "require_read": True,
    })
    assert not blind_edit.success
    assert "READ_BEFORE_EDIT_REQUIRED" in blind_edit.error

    # 3. Read then edit succeeds
    fs_read = FSReadTool()
    read_res = fs_read.execute({"_workspace": None, "path": "config.json"})
    assert read_res.success

    edit_res = fs_edit.execute({
        "_workspace": None,
        "path": "config.json",
        "old_string": '"theme": "light"',
        "new_string": '"theme": "dark"',
        "require_read": True,
    })
    assert edit_res.success
    assert '"theme": "dark"' in cfg_file.read_text(encoding="utf-8")
    assert '"version": "1.0.0"' in cfg_file.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Scenario C: Interrupt and Resume Reconciliation
# ─────────────────────────────────────────────────────────────────────────────
def test_scenario_c_interrupt_and_resume_reconciliation(clean_workspace: Path):
    """
    Scenario C:
    1. Interrupted mission where 2 out of 3 tasks were completed on disk.
    2. Resume reconciles state without re-running completed tasks or clobbering files.
    3. Missing file is identified and completed.
    """
    # Create partial work
    (clean_workspace / "index.html").write_text("<!DOCTYPE html><html><body><h1>Header</h1></body></html>", encoding="utf-8")
    (clean_workspace / "styles.css").write_text("body { background: #eee; }", encoding="utf-8")

    task1 = MissionTask(title="Create index.html", description="Create index.html", state=TaskState.PENDING)
    task2 = MissionTask(title="Create styles.css", description="Create styles.css", state=TaskState.PENDING)
    task3 = MissionTask(title="Create app.js", description="Create app.js", state=TaskState.PENDING)

    mission = Mission(
        mission_id="mission_resume_scen_c",
        user_prompt="Build site",
        tasks=[task1, task2, task3],
    )

    runner = MissionRunner(
        orchestrator=MagicMock(),
        workspace_manager=workspace_manager,
    )

    # Reconcile on resume
    runner.reconcile_mission_state(mission)

    # Completed tasks recognized from disk
    assert task1.state == TaskState.COMPLETED
    assert task2.state == TaskState.COMPLETED
    # Missing task remains pending
    assert task3.state == TaskState.PENDING

    # Only task 3 needs execution
    next_task = mission.next_executable_task
    assert next_task is not None
    assert next_task.title == "Create app.js"


# ─────────────────────────────────────────────────────────────────────────────
# Scenario D: Controlled Tool Failure Error Classification
# ─────────────────────────────────────────────────────────────────────────────
def test_scenario_d_controlled_tool_failure_classification():
    """
    Scenario D:
    1. Simulated infrastructure/IO tool failure.
    2. DisagreementRouter isolates failure from T3 escalation.
    3. Escalation limits (MAX_T3_PER_MISSION, MAX_T3_PER_TASK) strictly enforced.
    """
    from core.disagreement_router import RoutingDecision
    router = DisagreementRouter()

    # Case 1: Infrastructure error quarantined to T1/T2
    infra_verification = VerificationResult(
        agree=False,
        confidence=0.2,
        critical_issues=["TOOL_INFRASTRUCTURE_FAILURE: disk I/O error writing file"],
        risk_score=0.4,
    )

    decision = router.route(
        verification=infra_verification,
        tool_name="fs.write",
        error_message="disk I/O error",
        mission_id="m_scen_d",
        task_id="t_scen_d_1",
    )
    assert decision.decision == RoutingDecision.ACCEPT, "Infrastructure error must NOT escalate to T3"
    assert "quarantined" in decision.reason.lower() or "infrastructure" in decision.reason.lower()

    # Case 2: Even semantic disagreement is bounded by T3 quotas
    semantic_verification = VerificationResult(
        agree=False,
        confidence=0.1,
        critical_issues=["Major architectural disagreement"],
        risk_score=0.4,
    )

    # First call: Allowed to escalate up to quota
    d1 = router.route(
        verification=semantic_verification,
        tool_name="fs.write",
        mission_id="m_scen_d",
        task_id="t_scen_d_2",
    )
    assert d1.decision == RoutingDecision.ESCALATE

    # Subsequent call on same task: Bounded (MAX_T3_PER_TASK = 1)
    d2 = router.route(
        verification=semantic_verification,
        tool_name="fs.write",
        mission_id="m_scen_d",
        task_id="t_scen_d_2",
    )
    assert d2.decision == RoutingDecision.ACCEPT, "Exceeded per-task T3 budget must be rejected"
    assert "suppressed" in d2.reason.lower() or "budget" in d2.reason.lower()
