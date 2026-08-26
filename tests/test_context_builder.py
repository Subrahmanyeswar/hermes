import pytest
import tempfile
from pathlib import Path
from core.context_builder import ContextBuilder, estimate_tokens, TOKEN_BUDGET_TOTAL
from core.workspace import WorkspaceManager
from core.mission_planner import MissionPlanner, MissionTask


@pytest.fixture
def ws_with_files(tmp_path):
    (tmp_path / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n\n"
        "class UserModel:\n    def __init__(self, name): self.name = name\n"
        "def create_app(): return app\n"
    )
    (tmp_path / "models.py").write_text(
        "class Post:\n    def __init__(self, title, content): pass\n"
    )
    (tmp_path / "requirements.txt").write_text("flask==3.0.0\nsqlalchemy\n")
    wm = WorkspaceManager()
    wm.lock(str(tmp_path))
    return wm


def test_context_builds_without_crash(ws_with_files):
    builder = ContextBuilder(ws_with_files)
    planner = MissionPlanner()
    mission = planner.plan("Create Flask API")
    task = mission.tasks[0]
    ctx = builder.build(task, mission)
    assert ctx is not None
    assert ctx.total_tokens > 0


def test_context_within_budget(ws_with_files):
    builder = ContextBuilder(ws_with_files)
    planner = MissionPlanner()
    mission = planner.plan("Create Flask API")
    task = mission.tasks[0]
    ctx = builder.build(task, mission)
    assert ctx.total_tokens <= TOKEN_BUDGET_TOTAL + 200  # 200 token slack


def test_context_contains_task_description(ws_with_files):
    builder = ContextBuilder(ws_with_files)
    planner = MissionPlanner()
    mission = planner.plan("Create a user authentication module")
    task = mission.tasks[0]
    ctx = builder.build(task, mission)
    rendered = ctx.to_string()
    assert "CURRENT TASK" in rendered
    assert "authentication" in rendered.lower()


def test_context_contains_workspace_skeleton(ws_with_files):
    builder = ContextBuilder(ws_with_files)
    planner = MissionPlanner()
    mission = planner.plan("Read and update models.py")
    task = mission.tasks[0]
    ctx = builder.build(task, mission)
    rendered = ctx.to_string()
    assert "WORKSPACE" in rendered
    assert "app.py" in rendered or "models.py" in rendered


def test_memory_context_compressed(ws_with_files):
    builder = ContextBuilder(ws_with_files)
    planner = MissionPlanner()
    mission = planner.plan("Write tests")
    task = mission.tasks[0]

    # Large memory with many facts
    large_memory = "\n".join([f"[FACT]: fact number {i}" for i in range(50)])
    ctx = builder.build(task, mission, memory_context=large_memory)
    rendered = ctx.to_string()
    # Should be compressed to last 8 facts only
    fact_lines = [l for l in rendered.split("\n") if "[FACT]" in l]
    assert len(fact_lines) <= 8


def test_error_context_injected_on_retry(ws_with_files):
    builder = ContextBuilder(ws_with_files)
    planner = MissionPlanner()
    mission = planner.plan("Fix the broken route")
    task = mission.tasks[0]
    task.retry_count = 1
    task.error_message = "NameError: name 'db' is not defined"

    ctx = builder.build(task, mission, error_context="NameError: name 'db' is not defined")
    rendered = ctx.to_string()
    assert "PREVIOUS FAILURE" in rendered
    assert "NameError" in rendered


def test_estimate_tokens_reasonable():
    # 380 chars should estimate ~100 tokens
    text = "a" * 380
    tokens = estimate_tokens(text)
    assert 90 <= tokens <= 110


def test_trim_to_budget_truncates_correctly(ws_with_files):
    builder = ContextBuilder(ws_with_files)
    long_content = "line\n" * 1000
    trimmed = builder._trim_to_budget(long_content, 50)
    assert estimate_tokens(trimmed) <= 60  # slight slack
    assert "TRIMMED" in trimmed


def test_context_summary_string(ws_with_files):
    builder = ContextBuilder(ws_with_files)
    planner = MissionPlanner()
    mission = planner.plan("Create hello.py")
    ctx = builder.build(mission.tasks[0], mission)
    summary = ctx.summary()
    assert "tokens" in summary
    assert "sections" in summary
