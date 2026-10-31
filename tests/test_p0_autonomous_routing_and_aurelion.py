# tests/test_p0_autonomous_routing_and_aurelion.py
"""
P0 Comprehensive Acceptance & Qualification Suite:
- Autonomous Execution & Planning Granularity
- Three-Tier Model Routing Observability & Failover Events
- UI Observability & Task State Transitions
- Cancellation Safety Lifecycle
- AURELION Automotive Landing Page Contracts, Art Direction, & Photographic Assets
"""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image
import pytest

from core.planning.decomposer import GoalDecomposer, DependencyCycleError
from core.runtime_state.events import EventType, HermesEvent, EventSeverity
from core.runtime_state.models import TaskStatus, RequirementStatus
from core.orchestrator import Orchestrator
from config.model_config import TIER1_MODEL, TIER1_PROVIDER, TIER2_MODEL, TIER2_PROVIDER, TIER3_MODEL, TIER3_PROVIDER

AURELION_WORKSPACE = Path(r"C:\Users\SUBBU\Downloads\car 2 hermes test")


# ── Group 1: Planning Granularity & Task Decomposition ─────────────────────────

def test_goal_decomposer_automotive_website_discrete_tasks():
    """Verify website prompts decompose into multiple discrete domain tasks rather than broad monolithic fallback."""
    prompt = (
        "Build a futuristic luxury automotive landing page for AURELION with concept vehicles, "
        "interactive specifications dialog, showcase form validation, and responsive styling."
    )
    reqs, checks = GoalDecomposer.decompose("goal_test_aurelion", prompt)

    # Must produce multiple granular requirements
    assert len(reqs) >= 4, f"Expected at least 4 requirements, got {len(reqs)}"
    assert "req.website" in reqs or "req.landing" in reqs or "req.car" in reqs
    assert "req.verification" in reqs

    # Requirement titles should be descriptive
    titles = [r.title for r in reqs.values()]
    assert any("Vehicle" in t or "Car" in t for t in titles)
    assert any("Verification" in t for t in titles)


def test_goal_decomposer_dag_validity():
    """Verify synthesized dependencies form a valid DAG with no cycles."""
    prompt = "Create a responsive website with dialog modal, form validation, and automated test suite."
    reqs, checks = GoalDecomposer.decompose("goal_test_dag", prompt)

    # Dependency check passes without DependencyCycleError
    GoalDecomposer.validate_dependencies(reqs)

    # Verification must depend on all other requirements
    verif = reqs.get("req.verification")
    assert verif is not None
    non_verif_keys = [k for k in reqs if k != "req.verification"]
    for k in non_verif_keys:
        assert k in verif.dependencies


def test_goal_decomposer_cycle_detection():
    """Verify that intentional cycles raise DependencyCycleError."""
    prompt = "Build simple app"
    reqs, _ = GoalDecomposer.decompose("goal_cycle_test", prompt)
    
    # Introduce an intentional cycle: A -> B -> A
    if len(reqs) >= 2:
        keys = list(reqs.keys())
        reqs[keys[0]].dependencies.append(keys[1])
        reqs[keys[1]].dependencies.append(keys[0])
        with pytest.raises(DependencyCycleError):
            GoalDecomposer.validate_dependencies(reqs)


# ── Group 2: Three-Tier Model Routing & Observability ──────────────────────────

def test_event_taxonomy_tier_events():
    """Verify canonical tier routing events exist in EventType."""
    assert hasattr(EventType, "TIER_SELECTED")
    assert hasattr(EventType, "TIER_FAILOVER_STARTED")
    assert EventType.TIER_SELECTED.value == "TIER_SELECTED"
    assert EventType.TIER_FAILOVER_STARTED.value == "TIER_FAILOVER_STARTED"


@pytest.mark.asyncio
async def test_orchestrator_emit_progress_publishes_to_event_bus():
    """Verify Orchestrator._emit_progress emits canonical HermesEvents to EventBus."""
    mock_bus = MagicMock()
    mock_bus.publish = MagicMock()

    orch = Orchestrator()
    orch.event_bus = mock_bus
    orch.mission_id = "m_test_orch_events"

    # Emit failover event
    await orch._emit_progress("model_failover", {
        "from_tier": 1,
        "to_tier": 2,
        "provider": "ollama",
        "model": TIER2_MODEL,
        "reason": "NVIDIA timeout",
    })

    assert mock_bus.publish.called
    emitted_event: HermesEvent = mock_bus.publish.call_args[0][0]
    assert emitted_event.event_type == EventType.TIER_FAILOVER_STARTED
    assert emitted_event.payload["to_tier"] == 2
    assert emitted_event.payload["model"] == TIER2_MODEL


@pytest.mark.asyncio
async def test_orchestrator_emit_progress_tier_selected():
    """Verify model_start or circuit_bypass emits TIER_SELECTED."""
    mock_bus = MagicMock()
    mock_bus.publish = MagicMock()

    orch = Orchestrator()
    orch.event_bus = mock_bus
    orch.mission_id = "m_test_tier_selected"

    await orch._emit_progress("circuit_bypass", {
        "tier": 2,
        "provider": "ollama",
        "model": TIER2_MODEL,
        "reason": "circuit_open",
    })

    assert mock_bus.publish.called
    emitted_event: HermesEvent = mock_bus.publish.call_args[0][0]
    assert emitted_event.event_type == EventType.TIER_SELECTED
    assert emitted_event.payload["tier"] == 2


# ── Group 3: Agent Loop Task Progression & Lifecycle ───────────────────────────

@pytest.mark.asyncio
async def test_agent_loop_task_tracking_helpers():
    """Verify _ensure_active_task, _advance_active_task, and _complete_all_tasks."""
    from core.agent_loop.loop import AgentLoop

    mock_orch = MagicMock()
    mock_bus = MagicMock()
    mock_bus.publish = MagicMock()

    loop = AgentLoop(orchestrator=mock_orch, event_bus_instance=mock_bus)
    loop._mission_id = "m_test_tasks"
    loop._tasks = [
        {"task_id": "task_1", "title": "Setup Architecture", "status": "PENDING"},
        {"task_id": "task_2", "title": "Implement Interactivity", "status": "PENDING"},
        {"task_id": "task_3", "title": "Verify Qualification", "status": "PENDING"},
    ]

    # 1. Ensure active task
    await loop._ensure_active_task()
    assert loop._active_task_idx == 0
    assert loop._tasks[0]["status"] == "RUNNING"
    assert mock_bus.publish.called
    ev1: HermesEvent = mock_bus.publish.call_args[0][0]
    assert ev1.event_type == EventType.TASK_STARTED
    assert ev1.payload["task_id"] == "task_1"

    # 2. Advance task progress
    await loop._advance_active_task("Initial files written")
    assert loop._tasks[0]["status"] == "COMPLETED"
    assert loop._active_task_idx == 1
    assert loop._tasks[1]["status"] == "RUNNING"

    # 3. Complete all tasks on finish
    await loop._complete_all_tasks("All acceptance checks passed")
    assert all(t["status"] == "COMPLETED" for t in loop._tasks)


# ── Group 4: Cancellation Safety Lifecycle ─────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_loop_abort_event_cancels_cleanly():
    """Verify that setting abort_event stops execution and emits MISSION_CANCELLED."""
    from core.agent_loop.loop import AgentLoop
    from core.mission_planner import Mission

    mock_orch = MagicMock()
    mock_bus = MagicMock()
    mock_bus.publish = MagicMock()

    abort_evt = asyncio.Event()
    abort_evt.set()  # Pre-aborted

    loop = AgentLoop(
        orchestrator=mock_orch,
        event_bus_instance=mock_bus,
        abort_event=abort_evt,
    )
    mission = Mission(mission_id="m_abort_test", user_prompt="Test abort")

    res = await loop.run(mission)
    assert not res.success
    assert res.termination_reason == "Cancelled by user"

    # Must publish MISSION_CANCELLED
    cancelled_calls = [
        call[0][0] for call in mock_bus.publish.call_args_list
        if isinstance(call[0][0], HermesEvent) and call[0][0].event_type == EventType.MISSION_CANCELLED
    ]
    assert len(cancelled_calls) > 0


# ── Group 5: AURELION Workspace Contracts & Static Validation ──────────────────

def test_aurelion_files_exist():
    """Verify all four required files exist in the test workspace."""
    for fname in ["index.html", "styles.css", "app.js", "README.md"]:
        fpath = AURELION_WORKSPACE / fname
        assert fpath.exists(), f"Missing required file: {fname}"
        assert fpath.stat().st_size > 0, f"File {fname} is empty"


def test_aurelion_image_assets_decode():
    """Verify all four photographic assets exist and decode cleanly as valid JPEGs."""
    img_dir = AURELION_WORKSPACE / "assets" / "images"
    assert img_dir.exists(), "Missing assets/images directory"

    required_images = ["hero.jpg", "aurelion_one.jpg", "aurelion_gt.jpg", "aurelion_neo.jpg"]
    for img_name in required_images:
        img_path = img_dir / img_name
        assert img_path.exists(), f"Missing asset: {img_name}"
        with Image.open(img_path) as im:
            assert im.format == "JPEG"
            assert im.width > 200
            assert im.height > 150


def test_aurelion_html_contracts():
    """Verify HTML semantic elements, dialog modal, and form structure."""
    html_content = (AURELION_WORKSPACE / "index.html").read_text(encoding="utf-8")

    # Navbar
    assert 'class="navbar"' in html_content
    assert 'class="nav-toggle"' in html_content
    assert 'id="nav-menu"' in html_content

    # Hero
    assert 'class="hero-section"' in html_content
    assert 'assets/images/hero.jpg' in html_content

    # Vehicles & Details buttons
    assert 'class="vehicle-cards"' in html_content
    assert 'class="details-btn"' in html_content
    assert 'data-vehicle="one"' in html_content
    assert 'data-vehicle="gt"' in html_content
    assert 'data-vehicle="neo"' in html_content

    # Vehicle Dialog
    assert '<dialog id="vehicle-dialog"' in html_content
    assert 'class="dialog-close"' in html_content
    assert 'id="dialog-title"' in html_content
    assert 'id="dialog-specs"' in html_content

    # Showcase Form
    assert 'id="showcase-form"' in html_content
    assert 'id="name"' in html_content
    assert 'id="email"' in html_content
    assert 'id="vehicle-select"' in html_content
    assert 'id="form-success"' in html_content
    assert 'hidden' in html_content


def test_aurelion_css_selectors_match_html():
    """Verify CSS selectors match HTML class and ID attributes without unstyled components."""
    css_content = (AURELION_WORKSPACE / "styles.css").read_text(encoding="utf-8")

    # Match class selectors
    assert '.hero-section' in css_content
    assert '.vehicle-cards' in css_content
    assert '.vehicle-card' in css_content
    assert '.details-btn' in css_content
    assert '.vehicle-dialog' in css_content
    assert '.dialog-close' in css_content
    assert '.specs-list' in css_content
    assert '#showcase-form' in css_content
    assert '.form-success' in css_content

    # Aesthetics
    assert '--accent-blue' in css_content
    assert 'overflow-x: hidden' in css_content
    assert 'prefers-reduced-motion' in css_content


def test_aurelion_js_contracts():
    """Verify JS bindings, focus restoration, backdrop dismissal, and form unhiding."""
    js_content = (AURELION_WORKSPACE / "app.js").read_text(encoding="utf-8")

    # Details button selector
    assert '.details-btn' in js_content

    # Vehicle data keys
    assert 'one:' in js_content
    assert 'gt:' in js_content
    assert 'neo:' in js_content

    # Dialog open/close lifecycle
    assert 'showModal' in js_content
    assert 'lastFocusedElement' in js_content
    assert 'dialogCloseBtn.focus()' in js_content
    assert 'lastFocusedElement.focus()' in js_content

    # Escape key and backdrop dismissal
    assert "'Escape'" in js_content
    assert 'e.target === dialog' in js_content

    # Form success unhide
    assert 'formSuccess.hidden = false' in js_content
    assert 'formSuccess.removeAttribute' in js_content


# ── Group 5: Antigravity-Style Activity Stream Formatting ──────────────────────

def test_antigravity_format_tool_headline():
    """Verify Antigravity micro-step headlines and diff stats for commands, files, searches, and browser."""
    from core.agent_loop.actions import format_tool_headline

    # 1. Shell commands
    hl, diff = format_tool_headline("shell.bash", {"command": "git status --short\ngit branch"})
    assert hl == "Ran git status --short"
    assert diff is None

    # 2. File read / analyze with line range
    hl, diff = format_tool_headline("fs.read", {"path": "src/app.py", "start_line": 10, "end_line": 50})
    assert hl == "Analyzed app.py #L10-50"
    assert diff is None

    # 3. File write / create new
    hl, diff = format_tool_headline("fs.write", {"path": "index.html", "content": "line1\nline2\nline3\n"})
    assert hl == "Created index.html +3 -0"
    assert diff == {"added": 3, "deleted": 0, "is_new": True}

    # 4. File edit / replace
    hl, diff = format_tool_headline("fs.edit", {
        "path": "styles.css",
        "target": "old1\nold2\n",
        "replacement": "new1\nnew2\nnew3\nnew4\n"
    })
    assert hl == "Modified styles.css +4 -2"
    assert diff == {"added": 4, "deleted": 2, "is_new": False}

    # 5. File search / glob
    hl, diff = format_tool_headline("search.glob", {"pattern": "**/*.tsx"})
    assert hl == "Searched files '**/*.tsx'"
    assert diff is None

    # 6. Browser evaluation
    hl, diff = format_tool_headline("browser.navigate", {"url": "http://127.0.0.1:8765/index.html"})
    assert "Browser evaluation" in hl
    assert "8765" in hl

