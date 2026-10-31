"""
Test Phase 9: Security Invariants, Workspace Containment & Mission Acceptance Gates.

Validates:
1. Path containment & directory traversal rejection (WorkspaceBoundaryError).
2. Sibling directory prefix attack prevention.
3. Skill script lazy loading & discovery safety (no code execution during discovery).
4. Truthful acceptance gate enforcement (failing contract/alignment blocks mission completion).
5. Attempt and run fencing (stale attempt mutations rejected).
"""

from pathlib import Path
import pytest
from core.workspace import canonicalize_workspace_path, WorkspaceBoundaryError, WorkspaceManager
from core.project_intelligence.skills import SkillEngine
from core.agent_loop.completion import CompletionPolicy
from core.contracts.builder import ContractBuilder
from core.contracts.manifest import ElementContract
from core.runtime_state.models import HermesRuntimeState, MissionState, MissionStatus
from core.runtime_state.events import HermesEvent, EventType
from core.runtime_state.reducer import StateReducer

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SKILLS_DIR = REPO_ROOT / "skills"


class TestPhase9SecurityPathContainment:
    def test_traversal_outside_workspace_rejected(self, tmp_path):
        ws_root = tmp_path / "sandbox"
        ws_root.mkdir()

        # Path traversal upwards
        with pytest.raises(WorkspaceBoundaryError):
            canonicalize_workspace_path("../../etc/passwd", ws_root)

        with pytest.raises(WorkspaceBoundaryError):
            canonicalize_workspace_path("../outside.txt", ws_root)

    def test_sibling_prefix_attack_rejected(self, tmp_path):
        ws_root = tmp_path / "app"
        ws_root.mkdir()
        sibling_evil = tmp_path / "app-evil"
        sibling_evil.mkdir()

        with pytest.raises(WorkspaceBoundaryError):
            canonicalize_workspace_path(sibling_evil / "malicious.py", ws_root)

    def test_legitimate_nested_paths_allowed(self, tmp_path):
        ws_root = tmp_path / "app"
        ws_root.mkdir()

        nested = canonicalize_workspace_path("src/components/Button.tsx", ws_root)
        assert nested == (ws_root / "src" / "components" / "Button.tsx").resolve()


class TestPhase9SkillScriptSafety:
    def test_discovery_does_not_execute_helper_scripts(self, tmp_path):
        """Proves that skill indexing discovers scripts without executing or importing them."""
        test_skills_dir = tmp_path / "skills"
        sample_skill = test_skills_dir / "sample-skill"
        sample_scripts = sample_skill / "scripts"
        sample_scripts.mkdir(parents=True)

        canary_file = tmp_path / "canary.pwned"
        script_file = sample_scripts / "helper.py"
        script_file.write_text(
            f"import pathlib\npathlib.Path(r'{canary_file}').write_text('PWNED')\n",
            encoding="utf-8"
        )

        skill_md = sample_skill / "SKILL.md"
        skill_md.write_text(
            "---\nname: sample-skill\ndescription: Test sample\ntriggers: [sample]\n---\n# Sample\n",
            encoding="utf-8"
        )

        engine = SkillEngine(
            workspace_root=tmp_path,
            canonical_skills_root=test_skills_dir,
        )
        index = engine.index_skills()
        assert "sample-skill" in index

        helpers = engine.get_skill_helpers("sample-skill")
        assert len(helpers) >= 1
        assert any(h.name == "helper.py" for h in helpers)

        # The script must NOT have executed
        assert not canary_file.exists(), "Security breach: helper script was executed during discovery!"


class TestPhase9AcceptanceGateTruthfulness:
    def test_broken_application_blocks_completion(self, tmp_path):
        """Proves that CompletionPolicy rejects mission completion when verification finds errors."""
        workspace = tmp_path / "broken_site"
        workspace.mkdir()

        # Defective HTML: links to missing stylesheet
        (workspace / "index.html").write_text(
            "<!DOCTYPE html><html><head><link rel='stylesheet' href='missing.css'></head><body><h1>Broken</h1></body></html>",
            encoding="utf-8"
        )
        (workspace / "styles.css").write_text("body { color: red; }", encoding="utf-8")
        (workspace / "app.js").write_text("console.log('app running');", encoding="utf-8")

        state = HermesRuntimeState(
            mission=MissionState(
                mission_id="p9-truth-test",
                status=MissionStatus.RUNNING,
            )
        )

        builder = ContractBuilder()
        blueprint, manifest, rubric = builder.build_web_contract(
            mission_id="p9-truth-test",
            prompt="Build a complete website with styles.css and app.js",
            extra_files=["styles.css", "app.js"],
        )
        manifest.element_ids["header-title"] = ElementContract(
            dom_id="header-title",
            tag="h1",
            owning_file="index.html",
            purpose="heading",
            required=True
        )

        state.blueprint = blueprint
        state.interface_manifest = manifest
        state.quality_rubric = rubric

        wm = WorkspaceManager()
        wm.lock(workspace)

        policy = CompletionPolicy()
        is_complete, reason, unmet = policy.evaluate_completion(
            mission_prompt="Build a complete website with styles.css and app.js",
            workspace=wm,
            runtime_state=state,
            written_files=["index.html", "styles.css", "app.js"],
        )

        assert not is_complete, f"CompletionPolicy must NOT approve completion when verification fails: {reason}"
        assert len(unmet) > 0 or "verification" in reason.lower() or "missing" in reason.lower()


class TestPhase9AttemptFencing:
    def test_stale_attempt_event_does_not_corrupt_active_attempt(self):
        """Verifies that an event with a stale attempt number does not overwrite active attempt state."""
        mission_id = "p9-fence-test"
        state = HermesRuntimeState(
            mission=MissionState(
                mission_id=mission_id,
                status=MissionStatus.RUNNING,
                attempt_number=2,
                run_id="run-002",
            )
        )

        stale_event = HermesEvent(
            event_id="evt-stale-01",
            sequence=1,
            mission_id=mission_id,
            attempt_number=1,
            run_id="run-001",
            event_type=EventType.REPAIR_COMPLETED,
            payload={
                "repair_id": "rep-old-01",
                "attempt_number": 1,
                "run_id": "run-001",
                "strategy": "old_strategy",
                "changes_made": ["repaired old file"],
                "verification_passed": True,
            },
        )

        updated_state = StateReducer.reduce(state, stale_event)
        assert updated_state.mission.attempt_number == 2
        assert updated_state.mission.run_id == "run-002"
        assert "rep-old-01" not in updated_state.repairs
