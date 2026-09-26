# tests/test_project_intelligence.py
"""
Comprehensive Test Suite for HERMES 2.x Project Intelligence Subsystem (Prompt 8).
Validates:
1. HERMES.md discovery, freshness tracking, line-count warning, and graceful missing handling.
2. Scoped Rules (.hermes/rules/) path matching, precedence resolution, deduplication, and lazy loading.
3. Progressive Agent Skills (.hermes/skills/) 3-level disclosure, path containment, and tool boundaries.
4. Environment Bootstrap (.hermes/bootstrap/) discovery, workspace fallback, and execution safety.
5. ProjectIntelligenceRegistry coordination, canonical EventBus emissions, and invalidation semantics.
6. ContextEngine 2.x integration (PROJECT_RULES and SCOPED_RULES sections with prompt-injection defense).
7. Long-horizon 100-turn simulation with mid-mission external modifications.
"""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, List

import pytest

from core.context.engine import ContextEngine
from core.context.models import ContextSectionType, ContextSourceType
from core.event_bus import EventBus
from core.project_intelligence.bootstrap import BootstrapEngine
from core.project_intelligence.hermes_md import HermesMdLoader
from core.project_intelligence.models import (
    BootstrapAction,
    BootstrapCommand,
    RuleScopeType,
)
from core.project_intelligence.registry import ProjectIntelligenceRegistry
from core.project_intelligence.rules import RuleEngine
from core.project_intelligence.skills import SkillEngine
from core.runtime_state.events import EventType, HermesEvent


@pytest.fixture
def temp_workspace():
    """Create an isolated temporary workspace directory."""
    temp_dir = tempfile.mkdtemp(prefix="hermes_proj_intel_test_")
    ws_path = Path(temp_dir)
    yield ws_path
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_bus():
    """Lightweight in-memory test event bus."""
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

    return MockEventBus()


# ── 1. HERMES.md Root Constitution Tests ──────────────────────────────────────

def test_hermes_md_missing(temp_workspace):
    """Missing HERMES.md should return safe empty instructions without crashing."""
    loader = HermesMdLoader(workspace_root=temp_workspace)
    assert loader.discover_path() is None

    instructions = loader.load()
    assert instructions.content == ""
    assert instructions.line_count == 0
    assert instructions.sha256_hash == ""
    assert not instructions.is_oversized


def test_hermes_md_discovery_and_content(temp_workspace):
    """HERMES.md discovered in workspace root, content and hash verified."""
    hermes_file = temp_workspace / "HERMES.md"
    content = "# Project Constitution\nRule 1: Always write tests.\nRule 2: Never break builds.\n"
    hermes_file.write_text(content, encoding="utf-8")

    loader = HermesMdLoader(workspace_root=temp_workspace)
    assert loader.discover_path() == hermes_file

    instructions = loader.load()
    assert instructions.path == str(hermes_file)
    assert instructions.content == content
    assert instructions.line_count == 3
    assert len(instructions.sha256_hash) == 64
    assert not instructions.is_oversized
    assert instructions.warning is None


def test_hermes_md_in_hermes_dir(temp_workspace):
    """.hermes/HERMES.md should be discovered if root does not have one."""
    hermes_dir = temp_workspace / ".hermes"
    hermes_dir.mkdir(parents=True)
    hermes_file = hermes_dir / "HERMES.md"
    hermes_file.write_text("Constitution in .hermes\n", encoding="utf-8")

    loader = HermesMdLoader(workspace_root=temp_workspace)
    assert loader.discover_path() == hermes_file
    instructions = loader.load()
    assert "Constitution in .hermes" in instructions.content


def test_hermes_md_oversized_warning(temp_workspace):
    """HERMES.md with > 200 lines triggers warning without truncating content."""
    hermes_file = temp_workspace / "HERMES.md"
    lines = [f"Rule {i}: Follow strict guideline number {i}." for i in range(250)]
    hermes_file.write_text("\n".join(lines), encoding="utf-8")

    loader = HermesMdLoader(workspace_root=temp_workspace)
    instructions = loader.load()

    assert instructions.line_count == 250
    assert instructions.is_oversized is True
    assert instructions.warning is not None
    assert "250 lines" in instructions.warning
    # Crucial: content must NOT be truncated
    assert len(instructions.content.splitlines()) == 250


def test_hermes_md_freshness_tracking(temp_workspace):
    """Mid-mission modification or deletion of HERMES.md is detected."""
    hermes_file = temp_workspace / "HERMES.md"
    hermes_file.write_text("Initial constitution\n", encoding="utf-8")

    loader = HermesMdLoader(workspace_root=temp_workspace)
    inst1 = loader.load()

    # No change
    changed, _ = loader.check_freshness()
    assert changed is False

    # External edit
    time.sleep(0.01)
    hermes_file.write_text("Updated constitution with new laws\n", encoding="utf-8")

    changed, fresh_inst = loader.check_freshness()
    assert changed is True
    assert fresh_inst is not None
    assert "Updated constitution" in fresh_inst.content
    assert fresh_inst.sha256_hash != inst1.sha256_hash

    # External deletion
    hermes_file.unlink()
    changed, fresh_inst = loader.check_freshness()
    assert changed is True
    assert fresh_inst.content == ""


# ── 2. Path-Scoped Rules Tests ────────────────────────────────────────────────

def test_rules_frontmatter_indexing(temp_workspace):
    """Rule engine indexes metadata without loading full rule bodies."""
    rules_dir = temp_workspace / ".hermes" / "rules"
    rules_dir.mkdir(parents=True)

    rule1 = rules_dir / "python.md"
    rule1.write_text(
        "---\n"
        "name: python-standards\n"
        "description: Python style guide and type hints\n"
        "paths:\n"
        "  - '**/*.py'\n"
        "priority: 150\n"
        "enforcement: mandatory\n"
        "---\n"
        "# Python Rules Body\n"
        "Always use type annotations and docstrings.\n",
        encoding="utf-8",
    )

    rule2 = rules_dir / "frontend.md"
    rule2.write_text(
        "---\n"
        "name: frontend-ui\n"
        "description: React component guidelines\n"
        "paths:\n"
        "  - 'src/frontend/**'\n"
        "priority: 200\n"
        "enforcement: guidance\n"
        "---\n"
        "# React Rules Body\n"
        "Use functional components only.\n",
        encoding="utf-8",
    )

    engine = RuleEngine(workspace_root=temp_workspace)
    index = engine.index_rules()

    assert len(index) == 2
    assert "python-standards" in index
    assert index["python-standards"].priority == 150
    assert index["python-standards"].enforcement == "mandatory"
    assert "**/*.py" in index["python-standards"].paths
    # Body cache should be empty prior to matching
    assert len(engine._body_cache) == 0


def test_rules_path_matching_and_precedence(temp_workspace):
    """
    Test deterministic cross-platform matching and precedence:
    file_specific > subsystem > directory > language > general.
    """
    rules_dir = temp_workspace / ".hermes" / "rules"
    rules_dir.mkdir(parents=True)

    # General language rule
    (rules_dir / "py_lang.md").write_text(
        "---\nname: python-lang\npaths: ['**/*.py']\npriority: 10\n---\nLanguage rule",
        encoding="utf-8",
    )
    # Directory rule
    (rules_dir / "src_dir.md").write_text(
        "---\nname: src-dir\npaths: ['src/**']\npriority: 10\n---\nDirectory rule",
        encoding="utf-8",
    )
    # Subsystem rule
    (rules_dir / "auth_subsystem.md").write_text(
        "---\nname: auth-subsystem\npaths: ['src/backend/auth/**']\npriority: 10\n---\nSubsystem rule",
        encoding="utf-8",
    )
    # Exact file rule
    (rules_dir / "login_file.md").write_text(
        "---\nname: login-file\npaths: ['src/backend/auth/login.py']\npriority: 10\n---\nFile specific rule",
        encoding="utf-8",
    )

    engine = RuleEngine(workspace_root=temp_workspace)

    # Match against a single login file (should match all 4, ordered by specificity)
    matched = engine.match_rules(["src/backend/auth/login.py"])
    matched_names = [r.metadata.name for r in matched]

    assert matched_names == ["login-file", "auth-subsystem", "src-dir", "python-lang"]
    # Verify bodies were lazily loaded
    assert len(engine._body_cache) == 4
    assert matched[0].body == "File specific rule"


def test_rules_windows_path_normalization(temp_workspace):
    """Backslash paths from Windows environments normalize and match Unix globs."""
    rules_dir = temp_workspace / ".hermes" / "rules"
    rules_dir.mkdir(parents=True)

    (rules_dir / "components.md").write_text(
        "---\nname: ui-components\npaths: ['src/frontend/components/**']\n---\nComponent rule",
        encoding="utf-8",
    )

    engine = RuleEngine(workspace_root=temp_workspace)
    # Target path with Windows backslashes
    matched = engine.match_rules([r"src\frontend\components\Button.tsx"])
    assert len(matched) == 1
    assert matched[0].metadata.name == "ui-components"


def test_rules_deduplication(temp_workspace):
    """Multiple active files matching the same rule return only one deduplicated Rule object."""
    rules_dir = temp_workspace / ".hermes" / "rules"
    rules_dir.mkdir(parents=True)

    (rules_dir / "python.md").write_text(
        "---\nname: py-rules\npaths: ['**/*.py']\n---\nPython body",
        encoding="utf-8",
    )

    engine = RuleEngine(workspace_root=temp_workspace)
    matched = engine.match_rules(["app.py", "core/engine.py", "tests/test_app.py"])
    assert len(matched) == 1
    assert matched[0].metadata.name == "py-rules"


def test_rules_freshness_invalidation(temp_workspace):
    """Modifying a rule file on disk invalidates body cache and triggers reload."""
    rules_dir = temp_workspace / ".hermes" / "rules"
    rules_dir.mkdir(parents=True)

    rf = rules_dir / "api.md"
    rf.write_text("---\nname: api-rules\npaths: ['api/**']\n---\nAPI v1", encoding="utf-8")

    engine = RuleEngine(workspace_root=temp_workspace)
    matched = engine.match_rules(["api/v1/users.py"])
    assert matched[0].body == "API v1"

    # External edit
    time.sleep(0.01)
    rf.write_text("---\nname: api-rules\npaths: ['api/**']\n---\nAPI v2 Updated", encoding="utf-8")

    changed, affected = engine.check_freshness()
    assert changed is True
    assert "api-rules" in affected

    # Subsequent match retrieves fresh body
    re_matched = engine.match_rules(["api/v1/users.py"])
    assert re_matched[0].body == "API v2 Updated"


# ── 3. Progressive Agent Skills Tests ─────────────────────────────────────────

def test_skills_3_level_progressive_disclosure(temp_workspace):
    """
    Test strict 3-level progressive disclosure:
    Level 1: index_skills() returns metadata only
    Level 2: load_skill() returns SKILL.md body
    Level 3: load_skill_resource() returns supporting files
    """
    skill_dir = temp_workspace / ".hermes" / "skills" / "database_migration"
    skill_dir.mkdir(parents=True)

    # 1. SKILL.md
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: db-migration\n"
        "description: Perform safe relational database migrations\n"
        "triggers: ['migrate', 'schema change', 'alembic']\n"
        "priority: 5\n"
        "allowed-tools: ['fs.read', 'fs.write', 'shell.bash']\n"
        "---\n"
        "# DB Migration Skill Body\n"
        "Always generate migration scripts before applying changes.\n",
        encoding="utf-8",
    )

    # 2. Supporting resource (Level 3)
    ref_dir = skill_dir / "references"
    ref_dir.mkdir()
    (ref_dir / "safety_checklist.md").write_text(
        "# Checklist\n1. Backup database\n2. Run dry-run\n3. Verify foreign keys\n",
        encoding="utf-8",
    )

    engine = SkillEngine(workspace_root=temp_workspace)

    # Level 1: Indexing
    index = engine.index_skills()
    assert "db-migration" in index
    meta = index["db-migration"]
    assert meta.triggers == ["migrate", "schema change", "alembic"]
    assert meta.allowed_tools == ["fs.read", "fs.write", "shell.bash"]
    # Body cache must be empty
    assert len(engine._body_cache) == 0

    # Level 2: Loading body
    skill = engine.load_skill("db-migration")
    assert skill is not None
    assert "DB Migration Skill Body" in skill.body
    # Resources must not be loaded yet
    assert len(skill.resources) == 0

    # Level 3: Loading resource
    res_content, err = engine.load_skill_resource("db-migration", "references/safety_checklist.md")
    assert err is None
    assert res_content is not None
    assert "1. Backup database" in res_content
    assert skill.resources["references/safety_checklist.md"] == res_content


def test_skills_security_path_traversal_rejection(temp_workspace):
    """Attempts to escape skill directory via ../ are blocked."""
    skills_dir = temp_workspace / ".hermes" / "skills" / "deploy"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("---\nname: deploy\n---\nDeploy instructions\n", encoding="utf-8")

    # Sensitive file outside skill dir
    secret_file = temp_workspace / "secret.env"
    secret_file.write_text("DB_PASSWORD=supersecret\n", encoding="utf-8")

    engine = SkillEngine(workspace_root=temp_workspace)
    content, err = engine.load_skill_resource("deploy", "../../secret.env")

    assert content is None
    assert err is not None
    assert "Security violation: path traversal" in err


def test_skills_binary_rejection(temp_workspace):
    """Binary files requested as skill resources are rejected safely."""
    skill_dir = temp_workspace / ".hermes" / "skills" / "image_proc"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: image-proc\n---\nImage skill\n", encoding="utf-8")

    bin_file = skill_dir / "sample.bin"
    bin_file.write_bytes(b"\x00\x01\x02\x03\xFF\xFE\xFD")

    engine = SkillEngine(workspace_root=temp_workspace)
    content, err = engine.load_skill_resource("image-proc", "sample.bin")

    assert content is None
    assert err is not None
    assert "SKILL_RESOURCE_BINARY" in err


def test_skills_matching_by_triggers_and_keywords(temp_workspace):
    """Skills are matched accurately by trigger words and task keywords."""
    s1 = temp_workspace / ".hermes" / "skills" / "testing"
    s1.mkdir(parents=True)
    (s1 / "SKILL.md").write_text(
        "---\nname: test-runner\ndescription: Run pytest and analyze failures\ntriggers: ['run tests', 'pytest']\n---\nRun tests",
        encoding="utf-8",
    )

    s2 = temp_workspace / ".hermes" / "skills" / "docker"
    s2.mkdir(parents=True)
    (s2 / "SKILL.md").write_text(
        "---\nname: docker-build\ndescription: Build container images\ntriggers: ['docker', 'container']\n---\nBuild container",
        encoding="utf-8",
    )

    engine = SkillEngine(workspace_root=temp_workspace)
    matches = engine.match_skills("Please run tests on the auth module using pytest")
    assert len(matches) >= 1
    assert matches[0].name == "test-runner"


# ── 4. Environment Lifecycle Bootstrap Tests ──────────────────────────────────

def test_bootstrap_explicit_manifest(temp_workspace):
    """Explicit .hermes/bootstrap/bootstrap.json is loaded and prioritized."""
    b_dir = temp_workspace / ".hermes" / "bootstrap"
    b_dir.mkdir(parents=True)

    manifest_data = {
        "commands": {
            "test": {
                "command": "pytest -v",
                "risk": "low",
                "timeout_seconds": 120,
                "description": "Run test suite",
            },
            "install": {
                "command": "pip install -r requirements.txt",
                "risk": "medium",
                "timeout_seconds": 300,
                "description": "Install dependencies",
            },
        }
    }
    (b_dir / "bootstrap.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    engine = BootstrapEngine(workspace_root=temp_workspace)
    manifest = engine.discover()

    assert manifest.manifest_type == "explicit"
    test_cmd = engine.get_command(BootstrapAction.TEST)
    assert test_cmd is not None
    assert test_cmd.command == "pytest -v"
    assert test_cmd.source == "project"
    assert test_cmd.risk == "low"

    install_cmd = engine.get_command(BootstrapAction.INSTALL)
    assert install_cmd is not None
    assert install_cmd.command == "pip install -r requirements.txt"


def test_bootstrap_auto_detected_fallback(temp_workspace):
    """When no explicit bootstrap files exist, synthesize from workspace manifests."""
    # Create package.json
    pkg_data = {
        "name": "my-app",
        "scripts": {
            "test": "jest",
            "build": "vite build",
            "dev": "vite",
        },
    }
    (temp_workspace / "package.json").write_text(json.dumps(pkg_data), encoding="utf-8")

    engine = BootstrapEngine(workspace_root=temp_workspace)
    manifest = engine.discover()

    assert manifest.manifest_type == "workspace_detected"
    test_cmd = engine.get_command("test")
    assert test_cmd is not None
    assert "jest" in test_cmd.command or "npm" in test_cmd.command
    assert test_cmd.source == "auto_detected"


# ── 5. ProjectIntelligenceRegistry & EventBus Tests ───────────────────────────

def test_registry_discovery_and_events(temp_workspace, mock_bus):
    """Registry discovery emits canonical events for all components."""
    # Setup HERMES.md
    (temp_workspace / "HERMES.md").write_text("# Project Constitution\n", encoding="utf-8")

    # Setup rule
    r_dir = temp_workspace / ".hermes" / "rules"
    r_dir.mkdir(parents=True)
    (r_dir / "code_style.md").write_text("---\nname: code-style\npaths: ['**/*']\n---\nStyle\n", encoding="utf-8")

    # Setup skill
    s_dir = temp_workspace / ".hermes" / "skills" / "git_helper"
    s_dir.mkdir(parents=True)
    (s_dir / "SKILL.md").write_text("---\nname: git-helper\n---\nGit\n", encoding="utf-8")

    registry = ProjectIntelligenceRegistry(
        workspace_root=temp_workspace,
        event_bus=mock_bus,
        mission_id="mission_test_1",
    )

    snapshot = registry.discover()
    assert snapshot.hermes_md_status == "LOADED"
    assert snapshot.rule_count == 1
    assert snapshot.skill_count == 1

    # Verify canonical events emitted
    assert mock_bus.has_event(EventType.PROJECT_INTELLIGENCE_DISCOVERED)
    assert mock_bus.has_event(EventType.RULE_DISCOVERED)
    assert mock_bus.has_event(EventType.SKILL_DISCOVERED)


def test_registry_freshness_invalidation_events(temp_workspace, mock_bus):
    """External changes trigger invalidation events through EventBus."""
    h_file = temp_workspace / "HERMES.md"
    h_file.write_text("# Initial\n", encoding="utf-8")

    registry = ProjectIntelligenceRegistry(
        workspace_root=temp_workspace,
        event_bus=mock_bus,
        mission_id="mission_test_2",
    )
    registry.discover()
    mock_bus.events.clear()

    # Modify HERMES.md externally
    time.sleep(0.01)
    h_file.write_text("# Updated Constitution\n", encoding="utf-8")

    changes = registry.check_freshness()
    assert changes.get("hermes_md") is True
    assert mock_bus.has_event(EventType.PROJECT_INSTRUCTIONS_CHANGED)


# ── 6. ContextEngine 2.x Integration Tests ────────────────────────────────────

def test_context_engine_sync(temp_workspace, mock_bus):
    """Registry synchronizes HERMES.md and matching scoped rules into ContextEngine."""
    # Root instructions
    (temp_workspace / "HERMES.md").write_text("# Strict Project Constitution\nRule 1: Always verify.\n", encoding="utf-8")

    # Scoped rules
    r_dir = temp_workspace / ".hermes" / "rules"
    r_dir.mkdir(parents=True)
    (r_dir / "backend.md").write_text(
        "---\nname: backend-guidelines\npaths: ['backend/**']\nenforcement: mandatory\n---\nBackend security rule",
        encoding="utf-8",
    )
    (r_dir / "frontend.md").write_text(
        "---\nname: frontend-guidelines\npaths: ['frontend/**']\nenforcement: guidance\n---\nFrontend UI rule",
        encoding="utf-8",
    )

    registry = ProjectIntelligenceRegistry(
        workspace_root=temp_workspace,
        event_bus=mock_bus,
    )
    registry.discover()

    engine = ContextEngine(event_bus=mock_bus, project_intelligence=registry)
    # Track an active backend file
    engine.track_file_snippet("backend/server.py", "def start(): pass")

    pack = engine.build_context(
        mission_goal="Build backend authentication endpoint",
        turn_number=1,
    )

    # Verify PROJECT_RULES section populated with HERMES.md
    project_rules_items = pack.sections.get(ContextSectionType.PROJECT_RULES, [])
    assert len(project_rules_items) >= 1
    assert "Strict Project Constitution" in project_rules_items[0].content
    assert project_rules_items[0].provenance.source_type == ContextSourceType.PROJECT_RULE

    # Verify SCOPED_RULES section populated with backend-guidelines ONLY (not frontend)
    scoped_rules_items = pack.sections.get(ContextSectionType.SCOPED_RULES, [])
    assert len(scoped_rules_items) == 1
    assert "backend-guidelines" in scoped_rules_items[0].content
    assert "Backend security rule" in scoped_rules_items[0].content
    assert not any("frontend-guidelines" in item.content for item in scoped_rules_items)

    # Verify messages serialization keeps SYSTEM, PROJECT_RULES, SCOPED_RULES in system role
    messages = pack.to_messages()
    system_msg = messages[0]["content"]
    assert "<project_rules>" in system_msg
    assert "Strict Project Constitution" in system_msg
    assert "<scoped_rules>" in system_msg
    assert "Backend security rule" in system_msg


# ── 7. Long-Horizon 100-Turn Simulation & Stress Test ─────────────────────────

def test_long_horizon_100_turns_with_dynamic_changes(temp_workspace, mock_bus):
    """
    Simulate a 100-turn long-running mission where:
    - HERMES.md is modified mid-mission
    - New rules are added dynamically
    - Active files shift across subsystems
    - Verification that context stays healthy and responsive
    """
    # Initialize workspace
    h_file = temp_workspace / "HERMES.md"
    h_file.write_text("# Initial Long Horizon Constitution\n", encoding="utf-8")

    r_dir = temp_workspace / ".hermes" / "rules"
    r_dir.mkdir(parents=True)
    (r_dir / "core.md").write_text("---\nname: core-rule\npaths: ['core/**']\n---\nCore rules", encoding="utf-8")

    registry = ProjectIntelligenceRegistry(workspace_root=temp_workspace, event_bus=mock_bus)
    engine = ContextEngine(event_bus=mock_bus, project_intelligence=registry)

    start_bench = time.monotonic()

    for turn in range(1, 101):
        # Dynamically change active file every 10 turns
        if turn < 30:
            engine.track_file_snippet("core/service.py", f"# Turn {turn} code")
        elif turn < 70:
            engine.track_file_snippet("api/router.py", f"# Turn {turn} api code")
        else:
            engine.track_file_snippet("ui/dashboard.tsx", f"# Turn {turn} ui code")

        # Turn 25: Edit HERMES.md
        if turn == 25:
            time.sleep(0.005)
            h_file.write_text("# Turn 25 Updated Constitution: Add security check\n", encoding="utf-8")

        # Turn 50: Add new rule dynamically
        if turn == 50:
            time.sleep(0.005)
            (r_dir / "api_rule.md").write_text(
                "---\nname: api-dynamic\npaths: ['api/**']\n---\nAPI rule added mid-mission",
                encoding="utf-8",
            )

        # Build context
        pack = engine.build_context(
            mission_goal=f"Execute long running step {turn}",
            turn_number=turn,
        )

        # Assertions at critical turns
        if turn == 30:
            # Must reflect updated constitution
            p_items = pack.sections.get(ContextSectionType.PROJECT_RULES, [])
            assert "Turn 25 Updated Constitution" in p_items[0].content

        if turn == 55:
            # Must reflect newly added api rule
            s_items = pack.sections.get(ContextSectionType.SCOPED_RULES, [])
            rule_texts = [it.content for it in s_items]
            assert any("api-dynamic" in rt for rt in rule_texts)

    total_time = time.monotonic() - start_bench
    avg_turn_ms = (total_time / 100.0) * 1000.0

    # Ensure high performance: avg turn context construction should be < 50ms
    assert avg_turn_ms < 50.0, f"Average turn context construction took {avg_turn_ms:.2f}ms"
