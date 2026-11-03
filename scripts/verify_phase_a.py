import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile
import os
from core.js_syntax_validator import (
    validate_javascript_detailed,
    promote_staged_javascript,
    get_staging_path,
    CLASS_SYNTAX_ERROR,
    CLASS_VALIDATION_SUCCESS,
    CLASS_UNSUPPORTED_EXTENSION,
)

with tempfile.TemporaryDirectory() as td:
    ws = Path(td)
    
    # 1. Standard pending.js
    staged_standard = ws / "app.pending.js"
    staged_standard.write_text("const a = 10;\nconsole.log(a);\n", encoding="utf-8")
    res1 = validate_javascript_detailed(staged_standard, workspace_root=ws)
    assert res1.is_valid, f"Expected valid, got: {res1}"
    assert res1.error_class == CLASS_VALIDATION_SUCCESS
    print("Test 1 (Standard app.pending.js): PASSED")
    
    # 2. Legacy app.js.pending
    staged_legacy = ws / "app.js.pending"
    staged_legacy.write_text("const b = 20;\nconsole.log(b);\n", encoding="utf-8")
    res2 = validate_javascript_detailed(staged_legacy, workspace_root=ws)
    assert res2.is_valid, f"Expected valid for legacy staging, got: {res2}"
    assert res2.error_class == CLASS_VALIDATION_SUCCESS
    # Ensure temporary copy was deleted
    files = list(ws.glob(".__hermes_val_*"))
    assert len(files) == 0, f"Temporary file leak: {files}"
    assert staged_legacy.exists(), "Original legacy file should be preserved"
    print("Test 2 (Legacy app.js.pending): PASSED")
    
    # 3. Invalid syntax
    staged_invalid = ws / "bad.pending.js"
    staged_invalid.write_text("const x = ;\n", encoding="utf-8")
    res3 = validate_javascript_detailed(staged_invalid, workspace_root=ws)
    assert not res3.is_valid
    assert res3.error_class == CLASS_SYNTAX_ERROR
    assert res3.line == 1
    print("Test 3 (Invalid syntax): PASSED")
    
    # 4. Atomic promotion
    target = ws / "app.js"
    ok, msg = promote_staged_javascript(staged_standard, target, workspace_root=ws, expected_sha256=res1.input_sha256)
    assert ok, f"Promotion failed: {msg}"
    assert target.exists()
    assert not staged_standard.exists()
    print("Test 4 (Atomic promotion): PASSED")
    
    # 5. Out-of-workspace escape rejected
    bad_target = ws.parent / "escape.js"
    staged_test = ws / "test.pending.js"
    staged_test.write_text("const z = 1;", encoding="utf-8")
    ok2, msg2 = promote_staged_javascript(staged_test, bad_target, workspace_root=ws)
    assert not ok2, "Escape should be rejected"
    assert "escapes workspace" in msg2
    print("Test 5 (Escape rejection): PASSED")

print("ALL PHASE A PRELIMINARY CHECKS PASSED!")
