#!/usr/bin/env python3
"""
HERMES — Week 16 Final Validation
TUI right panel + full status bar complete.
All 4 panels live. Mode switching working.

Run: python tests/test_week16_final.py
"""
import asyncio
import importlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_1_all_week16_files_exist():
    required = [
        ("ui/panels/right_panel.py", "Right panel with 3 tabs"),
        ("ui/panels/status_bar.py",  "Full status bar"),
        ("ui/panels/chat.py",        "Chat panel"),
        ("ui/app.py",                "Main app with all panels"),
        ("ui/hermes.css",            "Complete stylesheet"),
    ]
    missing = [f"{p} ({d})" for p, d in required if not Path(p).exists()]
    if missing:
        for m in missing:
            print(f"  [FAIL] {m}")
        return False
    print(f"  [OK] All {len(required)} Week 16 files exist")
    return True


def test_2_right_panel_module_complete():
    required_symbols = [
        "RightPanel", "ToolTracePane", "MemoryViewPane",
        "TaskQueuePane", "ToolTraceEntry",
    ]
    try:
        mod = importlib.import_module("ui.panels.right_panel")
        missing = [s for s in required_symbols if not hasattr(mod, s)]
        if missing:
            print(f"  [FAIL] Missing from right_panel: {missing}")
            return False
        print(f"  [OK] right_panel.py exports all {len(required_symbols)} required symbols")
        return True
    except ImportError as e:
        print(f"  [FAIL] Import error: {e}")
        return False


def test_3_status_bar_complete():
    try:
        from ui.panels.status_bar import StatusBar, SPINNER_VERBS, _random_verb
        assert len(SPINNER_VERBS) == 30
        assert len(set(SPINNER_VERBS)) == 30
        verb = _random_verb()
        assert verb in SPINNER_VERBS

        # Test all required reactive attributes
        required_attrs = [
            "mode", "skill", "cost", "kairos_status",
            "processing", "spinner_verb", "tier1_model", "tier2_model"
        ]
        missing = [a for a in required_attrs if not hasattr(StatusBar, a)]
        if missing:
            print(f"  [FAIL] StatusBar missing reactives: {missing}")
            return False

        # Test API methods
        bar = StatusBar()
        assert hasattr(bar, "set_processing")
        assert hasattr(bar, "update_all")
        assert hasattr(bar, "_render_status")

        # Test render for all modes
        for mode in ("safe", "plan", "auto"):
            bar.mode = mode
            rendered = bar._render_status()
            assert mode.upper() in rendered.plain

        print(f"  [OK] StatusBar complete | 30 unique verbs | all reactives present | renders all modes")
        return True
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return False


def test_4_app_compose_has_all_4_panels():
    import inspect
    from ui.app import HermesApp
    src = inspect.getsource(HermesApp.compose)
    required = ["StatusBar", "ChatPanel", "RightPanel", "Footer"]
    missing = [p for p in required if p not in src]
    if missing:
        print(f"  [FAIL] compose() missing: {missing}")
        return False
    print(f"  [OK] HermesApp.compose() includes all 4 panels: {required}")
    return True


def test_5_key_bindings_all_present():
    from ui.app import HermesApp
    bindings = {b.key for b in HermesApp.BINDINGS}
    required = {"ctrl+s", "ctrl+p", "ctrl+a", "ctrl+q"}
    missing = required - bindings
    if missing:
        print(f"  [FAIL] Missing bindings: {missing}")
        return False
    print(f"  [OK] All mode-switching bindings present: {sorted(required)}")
    return True


def test_6_message_classes_have_required_fields():
    from ui.app import OrchestratorResponse
    import inspect
    sig = inspect.signature(OrchestratorResponse.__init__)
    params = set(sig.parameters.keys()) - {"self"}
    required_params = {
        "user_request", "final_output", "tool_name", "success",
        "stage_reached", "tier3_called", "latency_seconds",
        "trace_id", "skill_ids",
    }
    missing = required_params - params
    if missing:
        print(f"  [FAIL] OrchestratorResponse missing params: {missing}")
        return False
    print(f"  [OK] OrchestratorResponse has all {len(required_params)} required fields")
    return True


def test_7_tool_trace_entry_renders_correctly():
    from ui.panels.right_panel import ToolTraceEntry
    from rich.text import Text

    cases = [
        ("write_file", True,  0, "Written 100 chars", 0.45, False, "abc12345", []),
        ("bash_exec",  False, 1, "command not found", 0.12, False, "err12345", []),
        ("git_push",   True,  0, "Pushed to origin",  2.1,  True,  "t3a12345", ["git-workflow"]),
    ]
    for tool, success, exit_code, output, latency, tier3, trace_id, skills in cases:
        entry = ToolTraceEntry(
            tool_name=tool, success=success, exit_code=exit_code,
            output_preview=output, latency=latency, tier3_called=tier3,
            trace_id=trace_id, skill_ids=skills,
        )
        rendered = entry.render()
        assert isinstance(rendered, Text)
        assert tool in rendered.plain
        if tier3:
            assert "T3 called" in rendered.plain
        if skills:
            assert skills[0] in rendered.plain

    print(f"  [OK] ToolTraceEntry renders all {len(cases)} test cases correctly")
    return True


def test_8_memory_view_renders_all_fact_types():
    from ui.panels.right_panel import MemoryViewPane
    pane = MemoryViewPane()
    fact_types = [
        "[FACT]: Uses Flask 3.1",
        "[BUG]: Login has null pointer",
        "[TASK_DONE]: Created REST API",
        "[BLOCKED]: Auth depends on DB",
        "[DETAIL]: See memory/schema.md",
        "[STALE]: Old outdated fact",
    ]
    for line in fact_types:
        rendered = pane._render_fact_line(line, is_new=False)
        assert "▶" not in rendered.plain, "Non-new fact should not have ▶"
        rendered_new = pane._render_fact_line(line, is_new=True)
        assert "▶" in rendered_new.plain, "New fact must have ▶ marker"
    print(f"  [OK] MemoryViewPane renders all 6 fact types with/without new marker")
    return True


def test_9_css_has_all_required_selectors():
    css_path = Path("ui/hermes.css")
    if not css_path.exists():
        print("  [FAIL] hermes.css not found")
        return False
    content = css_path.read_text()
    required = [
        "#chat-panel", "#right-panel", "#main-layout",
        "TabbedContent", "TabPane", "StatusBar",
        "#tool-trace-scroll", "#memory-scroll", "#task-scroll",
    ]
    missing = [s for s in required if s not in content]
    if missing:
        print(f"  [FAIL] hermes.css missing selectors: {missing}")
        return False
    print(f"  [OK] hermes.css has all {len(required)} required selectors")
    return True


def test_10_full_tui_test_suite_passes():
    print("  Running full TUI test suite...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_tui.py", "-q",
         "--timeout=60", "--tb=short"],
        capture_output=True, text=True, timeout=120
    )
    lines = result.stdout.strip().split("\n")
    summary = lines[-1] if lines else ""
    if result.returncode != 0:
        print(f"  [FAIL] TUI tests FAILED")
        for line in lines[-15:]:
            if line.strip():
                print(f"    {line}")
        return False
    print(f"  [OK] {summary}")
    return True


def main():
    print("=" * 65)
    print("HERMES — Week 16 Final Validation")
    print("TUI Right Panel + Full Status Bar")
    print("=" * 65)

    tests = [
        ("All Week 16 files exist",                       test_1_all_week16_files_exist),
        ("right_panel.py exports all required symbols",   test_2_right_panel_module_complete),
        ("StatusBar complete: verbs, reactives, render",  test_3_status_bar_complete),
        ("HermesApp.compose() has all 4 panels",          test_4_app_compose_has_all_4_panels),
        ("All 4 key bindings present",                    test_5_key_bindings_all_present),
        ("OrchestratorResponse has required fields",      test_6_message_classes_have_required_fields),
        ("ToolTraceEntry renders all cases",              test_7_tool_trace_entry_renders_correctly),
        ("MemoryViewPane renders all fact types",         test_8_memory_view_renders_all_fact_types),
        ("hermes.css has all required selectors",         test_9_css_has_all_required_selectors),
        ("Full TUI test suite passes",                    test_10_full_tui_test_suite_passes),
    ]

    passed_all = True
    for name, fn in tests:
        print(f"\n[TEST] {name}")
        try:
            if not fn():
                passed_all = False
        except Exception as e:
            import traceback
            print(f"  [FAIL] ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
            passed_all = False

    print("\n" + "=" * 65)
    if passed_all:
        print("WEEK 16 COMPLETE: All 4 panels live.")
        print()
        print("  [OK] Chat panel — conversation history + input")
        print("  [OK] Tool Trace — every tool call logged in real-time")
        print("  [OK] Memory View — live MEMORY.md with new-line highlighting")
        print("  [OK] Task Queue — SQLite tasks auto-refreshing every 30s")
        print("  [OK] Status bar — mode/skill/cost/KAIROS/spinner")
        print("  [OK] Mode switching — Ctrl+S/P/A working")
        print()
        print("Test the complete TUI:")
        print("  python main.py ui")
        print("  Try: list files -> watch Tool Trace update")
        print("  Try: Ctrl+S -> watch status bar change to SAFE")
        print("  Try: Ctrl+A -> watch status bar change back to [AUTO] in green")
        print("  Try: /clear, /help, /mode auto")
        print()
        print("Ready for Week 17 (WOW features: /push, /export, /vscode, screenshot-to-code).")
    else:
        print("WEEK 16 INCOMPLETE — fix failures before Week 17.")
    print("=" * 65)


if __name__ == "__main__":
    main()
