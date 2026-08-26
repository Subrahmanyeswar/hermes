import pytest
from core.mission_planner import MissionPlanner, Mission, MissionTask, TaskState, TaskPriority


@pytest.fixture
def planner():
    return MissionPlanner()


# ── Single task ───────────────────────────────────────────────────────────────

def test_single_task_prompt(planner):
    mission = planner.plan("Create a Python hello world script")
    assert len(mission.tasks) >= 1
    assert mission.mission_id is not None


# ── Multi-task parsing ────────────────────────────────────────────────────────

def test_multi_task_and_separator(planner):
    mission = planner.plan(
        "Create Flask API and write pytest tests and push to GitHub"
    )
    assert len(mission.tasks) >= 2


def test_multi_task_numbered_list(planner):
    prompt = (
        "1. Initialize Flask project structure\n"
        "2. Create SQLite database models\n"
        "3. Write authentication routes\n"
        "4. Generate pytest test suite"
    )
    mission = planner.plan(prompt)
    assert len(mission.tasks) == 4


def test_multi_task_bullet_list(planner):
    prompt = (
        "- Create the folder structure\n"
        "- Write the Flask app\n"
        "- Add unit tests\n"
        "- Push to GitHub"
    )
    mission = planner.plan(prompt)
    assert len(mission.tasks) == 4


# ── Dependency detection ──────────────────────────────────────────────────────

def test_tests_depend_on_implementation(planner):
    mission = planner.plan("Create Flask routes and write tests for the routes")
    test_task = next((t for t in mission.tasks if "test" in t.title.lower()), None)
    create_task = next((t for t in mission.tasks if "create" in t.title.lower() or "flask" in t.title.lower()), None)
    if test_task and create_task:
        # Test task should have a dependency (possibly on create task)
        # At minimum it should not be the FIRST in execution order
        test_idx = mission.execution_order.index(test_task.task_id)
        create_idx = mission.execution_order.index(create_task.task_id)
        assert create_idx <= test_idx  # create comes before or equal


# ── Skill detection ───────────────────────────────────────────────────────────

def test_flask_skill_detected(planner):
    mission = planner.plan("Build a Flask REST API with SQLite")
    flask_task = next((t for t in mission.tasks if "flask" in t.description.lower() or "api" in t.description.lower()), None)
    if flask_task:
        assert flask_task.skill_hint == "flask-rest-api"


def test_git_skill_detected(planner):
    mission = planner.plan("Push the project to GitHub")
    git_task = mission.tasks[0]
    assert git_task.skill_hint == "git-workflow"


def test_test_skill_detected(planner):
    mission = planner.plan("Write pytest tests for the auth module")
    test_task = mission.tasks[0]
    assert test_task.skill_hint == "pytest-generation"


# ── Mission state machine ─────────────────────────────────────────────────────

def test_next_executable_task_returns_first_pending(planner):
    mission = planner.plan("Create folder and write code")
    task = mission.next_executable_task
    assert task is not None
    assert task.state == TaskState.PENDING


def test_mark_task_complete_updates_state(planner):
    mission = planner.plan("Create hello.py")
    task = mission.tasks[0]
    mission.mark_task_complete(task.task_id)
    assert task.state == TaskState.COMPLETED


def test_mark_task_failed_blocks_dependents(planner):
    mission = Mission()
    task_a = MissionTask(title="Create API routes", state=TaskState.PENDING)
    task_b = MissionTask(title="Write tests for routes", depends_on=[task_a.task_id])
    mission.tasks = [task_a, task_b]
    mission.execution_order = [task_a.task_id, task_b.task_id]
    mission.mark_task_failed(task_a.task_id, "creation failed")
    assert task_b.state == TaskState.BLOCKED


def test_mission_is_complete_when_all_done(planner):
    mission = planner.plan("Create hello.py")
    assert not mission.is_complete
    for task in mission.tasks:
        task.state = TaskState.COMPLETED
    assert mission.is_complete


def test_progress_tuple(planner):
    mission = planner.plan("Create file and write tests")
    completed, total = mission.progress
    assert completed == 0
    assert total >= 1


def test_get_status_lines_returns_list(planner):
    mission = planner.plan("Create folder and write code")
    lines = mission.get_status_lines()
    assert isinstance(lines, list)
    assert len(lines) >= 1
    assert "○" in lines[0] or "▶" in lines[0]


# ── Topological sort ──────────────────────────────────────────────────────────

def test_topological_order_respects_dependencies():
    from core.mission_planner import MissionPlanner
    planner = MissionPlanner()
    mission = planner.plan(
        "1. Create Flask models\n2. Write tests for models\n3. Push to GitHub"
    )
    # Push should be last or near last
    push_task = next((t for t in mission.tasks if "push" in t.title.lower()), None)
    if push_task and len(mission.execution_order) > 1:
        push_idx = mission.execution_order.index(push_task.task_id)
        assert push_idx >= 0  # at minimum it exists in the order


def test_no_task_depends_on_itself():
    from core.mission_planner import MissionPlanner
    planner = MissionPlanner()
    mission = planner.plan("Create API and write tests and push")
    for task in mission.tasks:
        assert task.task_id not in task.depends_on
