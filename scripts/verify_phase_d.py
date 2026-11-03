import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile
from core.project_contract import ProjectContract
from core.mission_state import MissionStateManager

with tempfile.TemporaryDirectory() as td:
    ws = Path(td)
    contract = ProjectContract.create_or_load(ws, mission_id="m_test1")
    
    # Reconcile empty workspace
    s1 = MissionStateManager.reconcile_state(ws, mission_id="m_test1", contract=contract)
    assert s1.monotonic_state_version == 1
    assert len(s1.final_artifact_paths) == 0
    assert len(s1.unmet_requirements) > 0
    assert s1.single_next_action.startswith("GENERATE_ARTIFACT_")
    assert s1.current_repair_target is not None
    
    # Check that .hermes/recovery_checkpoint.json and mission_state.json were created
    assert (ws / ".hermes" / "mission_state.json").exists()
    assert (ws / ".hermes" / "recovery_checkpoint.json").exists()
    
    # Pure reconciliation check: confirm no application files were generated
    created_app_files = [f.name for f in ws.iterdir() if f.is_file() and not f.name.startswith(".")]
    assert len(created_app_files) == 0, f"Reconciliation mutated workspace: {created_app_files}"
    print("Test 1 (Pure reconciliation on empty workspace): PASSED")
    
    # Now create one file
    (ws / contract.canonical_html).write_text("<!DOCTYPE html><html><body><h1>Hello</h1></body></html>", encoding="utf-8")
    s2 = MissionStateManager.reconcile_state(ws, mission_id="m_test1", contract=contract)
    assert s2.monotonic_state_version == 2
    assert contract.canonical_html in s2.final_artifact_paths
    print("Test 2 (File detection & monotonic state version increment): PASSED")

print("ALL PHASE D PRELIMINARY CHECKS PASSED!")
