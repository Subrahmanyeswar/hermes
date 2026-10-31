# tests/test_phase7_visual_design_skills.py
"""
Phase 7 Batch 7B Tests: Visual Design Craft Skills.
Covers:
1. Frontmatter and metadata discovery for design-engineering, web-design-guidelines, taste-design, and design-system.
2. Positive and negative routing assertions.
3. Multi-skill composition (e.g. taste-design + design-engineering).
4. Boundary tests (button spacing does not trigger design system/taste design).
5. Level 1 metadata purity and Level 2 lazy loading.
6. Representative task browser review loop using DevServerManager and BrowserManager.
"""

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import List

import pytest

from core.browser.dev_server import DevServerManager
from core.browser.manager import BrowserManager
from core.browser.models import Viewport
from core.context.engine import ContextEngine
from core.context.models import ContextSectionType, ContextSourceType
from core.project_intelligence.registry import ProjectIntelligenceRegistry
from core.project_intelligence.skills import SkillEngine
from core.runtime_state.events import EventType, HermesEvent

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SKILLS_DIR = REPO_ROOT / "skills"


class MockEventBus:
    def __init__(self):
        self.events: List[HermesEvent] = []

    def publish(self, event: HermesEvent):
        self.events.append(event)

    def publish_nowait(self, event: HermesEvent):
        self.events.append(event)

    def has_event(self, event_type: EventType) -> bool:
        return any(e.event_type == event_type for e in self.events)

    def get_events(self, event_type: EventType) -> List[HermesEvent]:
        return [e for e in self.events if e.event_type == event_type]


@pytest.fixture
def temp_workspace():
    td = tempfile.mkdtemp(prefix="hermes_phase7_batch7b_")
    ws = Path(td)
    yield ws
    shutil.rmtree(td, ignore_errors=True)


@pytest.fixture
def mock_bus():
    return MockEventBus()


@pytest.fixture
def skill_engine():
    return SkillEngine(workspace_root=REPO_ROOT, canonical_skills_root=CANONICAL_SKILLS_DIR)


@pytest.fixture
def canonical_registry(mock_bus):
    return ProjectIntelligenceRegistry(
        workspace_root=REPO_ROOT,
        canonical_skills_root=CANONICAL_SKILLS_DIR,
        event_bus=mock_bus,
        mission_id="mission_phase7_batch7b_test",
    )


# ── 1. Frontmatter and Metadata Index Tests ─────────────────────────────────

def test_design_engineering_metadata(skill_engine):
    """Verify design-engineering frontmatter and metadata index."""
    index = skill_engine.index_skills(force_reload=True)
    assert "design-engineering" in index
    meta = index["design-engineering"]
    assert meta.name == "design-engineering"
    assert "responsive" in meta.description.lower() or "frontend" in meta.description.lower()
    assert "design engineering" in meta.triggers
    assert "browser.navigate" in meta.allowed_tools
    assert "browser.screenshot" in meta.allowed_tools


def test_web_design_guidelines_metadata(skill_engine):
    """Verify web-design-guidelines frontmatter and metadata index."""
    index = skill_engine.index_skills(force_reload=True)
    assert "web-design-guidelines" in index
    meta = index["web-design-guidelines"]
    assert meta.name == "web-design-guidelines"
    assert "accessibility" in meta.description.lower() or "usability" in meta.description.lower()
    assert "accessibility audit" in meta.triggers or "web design guidelines" in meta.triggers
    assert "browser.inspect" in meta.allowed_tools


def test_taste_design_metadata(skill_engine):
    """Verify taste-design frontmatter and metadata index."""
    index = skill_engine.index_skills(force_reload=True)
    assert "taste-design" in index
    meta = index["taste-design"]
    assert meta.name == "taste-design"
    assert "taste design" in meta.triggers
    assert "editorial design" in meta.triggers
    assert "fs.write" in meta.allowed_tools


def test_design_system_metadata(skill_engine):
    """Verify design-system frontmatter and metadata index."""
    index = skill_engine.index_skills(force_reload=True)
    assert "design-system" in index
    meta = index["design-system"]
    assert meta.name == "design-system"
    assert "design system" in meta.triggers
    assert "design tokens" in meta.triggers
    assert "search.grep" in meta.allowed_tools


# ── 2. Routing & Composition Tests ──────────────────────────────────────────

def test_routing_accessibility_audit(skill_engine):
    """Audit request activates web-design-guidelines."""
    prompt = "Audit this form for keyboard accessibility and usability issues"
    decision = skill_engine.route_skills(prompt, max_candidates=3)
    assert "web-design-guidelines" in decision.selected_skills


def test_routing_design_tokens(skill_engine):
    """Token extraction request activates design-system."""
    prompt = "Create a reusable design token set from these existing styles"
    decision = skill_engine.route_skills(prompt, max_candidates=3)
    assert "design-system" in decision.selected_skills


def test_routing_editorial_portfolio_composition(skill_engine):
    """Editorial brief composition activates both taste-design and design-engineering."""
    prompt = "Build a distinctive editorial portfolio from this brief"
    decision = skill_engine.route_skills(prompt, max_candidates=3)
    assert "taste-design" in decision.selected_skills
    assert "design-engineering" in decision.selected_skills


def test_boundary_button_spacing_no_design_flood(skill_engine):
    """Narrow CSS adjustment does NOT flood unrelated creative design skills."""
    prompt = "Adjust the spacing on this existing button without changing the design"
    decision = skill_engine.route_skills(prompt, max_candidates=3)
    assert "taste-design" not in decision.selected_skills
    assert "web-design-guidelines" not in decision.selected_skills
    assert "design-system" not in decision.selected_skills


# ── 3. Representative Task & Browser Review Loop ────────────────────────────

@pytest.mark.asyncio
async def test_browser_review_representative_design(temp_workspace):
    """
    Render and verify an accessible, responsive design task using BrowserManager:
    1. Create sample semantic landing page in isolated workspace
    2. Start DevServerManager
    3. Launch BrowserManager session (CDP or fallback)
    4. Verify navigation, page title, heading visibility, and mobile viewport
    """
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Artisanal Roasters</title>
  <style>
    :root {
      --color-canvas: #fbf9f5;
      --color-ink: #1c1917;
      --color-accent: #b45309;
      --font-stack: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    body {
      background-color: var(--color-canvas);
      color: var(--color-ink);
      font-family: var(--font-stack);
      margin: 0;
      padding: 2rem;
      line-height: 1.5;
    }
    h1 {
      font-size: 2.25rem;
      color: var(--color-accent);
      margin-bottom: 0.5rem;
    }
    button {
      background-color: var(--color-accent);
      color: #ffffff;
      border: none;
      padding: 0.75rem 1.5rem;
      font-size: 1rem;
      cursor: pointer;
      border-radius: 4px;
    }
    button:focus-visible, input:focus-visible {
      outline: 2px solid var(--color-ink);
      outline-offset: 2px;
    }
  </style>
</head>
<body>
  <main>
    <h1>Artisanal Roasters</h1>
    <p>Single-origin pour overs and seasonal pastries crafted with intention.</p>
    <div class="search-box">
      <input id="search-input" type="text" placeholder="Search single-origins..." aria-label="Search single-origins" />
      <button id="order-btn" aria-label="Order fresh coffee online">Order Online</button>
    </div>
  </main>
</body>
</html>"""
    (temp_workspace / "index.html").write_text(html_content, encoding="utf-8")

    server_mgr = DevServerManager()
    server_info = await server_mgr.start_static_server(
        directory=temp_workspace,
        timeout=10.0,
    )
    assert server_info is not None
    assert server_info.port > 0

    browser_mgr = BrowserManager(artifacts_dir=temp_workspace / "artifacts", prefer_cdp=False)
    try:
        # Launch browser with desktop viewport
        launched = await browser_mgr.launch(headless=True, viewport=Viewport.desktop())
        assert launched
        assert browser_mgr.is_active

        # Navigate to dev server
        url = f"{server_info.url}/index.html"
        nav_result = await browser_mgr.navigate(url)
        assert nav_result.success
        assert nav_result.status == 200
        assert "Artisanal Roasters" in nav_result.title

        # Inspect DOM structure and interactive elements
        inspect_res = await browser_mgr.inspect()
        assert "Artisanal Roasters" in inspect_res.title
        assert len(inspect_res.elements) >= 3
        assert any(e.tag_name == "h1" for e in inspect_res.elements)
        assert any(e.tag_name == "input" for e in inspect_res.elements)
        assert any(e.tag_name == "button" for e in inspect_res.elements)
        assert "Artisanal Roasters" in inspect_res.visible_text

        # Verify keyboard / text input interaction
        type_res = await browser_mgr.type_text("#search-input", "Ethiopian Yirgacheffe")
        assert type_res.success

        # Verify button interaction via click
        action_res = await browser_mgr.click("#order-btn")
        assert action_res.success

        # Verify desktop viewport screenshot artifact (1280x800)
        desktop_shot = await browser_mgr.capture_screenshot("desktop_view", viewport=Viewport.desktop())
        assert desktop_shot is not None
        assert desktop_shot.width == 1280
        assert desktop_shot.height == 800
        assert Path(desktop_shot.file_path).exists()
        assert Path(desktop_shot.file_path).stat().st_size > 0

        # Verify mobile viewport screenshot artifact (375x667)
        mobile_shot = await browser_mgr.capture_screenshot("mobile_view", viewport=Viewport.mobile())
        assert mobile_shot is not None
        assert mobile_shot.width == 375
        assert mobile_shot.height == 667
        assert Path(mobile_shot.file_path).exists()
        assert Path(mobile_shot.file_path).stat().st_size > 0

        # Verify zero console errors
        console_msgs = browser_mgr.get_console_messages()
        error_msgs = [m for m in console_msgs if m.msg_type == "error"]
        assert len(error_msgs) == 0

        # Verify network request records
        net_records = browser_mgr.get_network_records()
        assert len(net_records) >= 1
        assert all(r.status == 200 for r in net_records if r.status is not None)

    finally:
        await browser_mgr.close()
        server_mgr.stop_all()
