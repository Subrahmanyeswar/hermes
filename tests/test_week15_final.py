#!/usr/bin/env python3
"""
HERMES — Week 15 Final Validation
Textual TUI structure + chat panel complete.

Run: python tests/test_week15_final.py
"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_1_all_tui_files_exist():
    """All Week 15 TUI files must exist."""
    required = [
        ("ui/__init__.py",              "UI package init"),
        ("ui/app.py",                   "Main Textual app class"),
        ("ui/hermes.css",               "TUI stylesheet"),
        ("ui/panels/__init__.py",       "Panels package init"),
        ("ui/panels/chat.py",           "Chat panel"),
        ("ui/panels/status_bar.py",     "Status bar"),
    ]
    missing = []
    for path_str, desc in required:
        if not Path(path_str).exists():
            missing.append(f"{path_str} ({desc})")
    if missing:
        print(f"  [FAIL] Missing files:")
        for m in missing:
            print(f"    - {m}")
        return False
    print(f"  [OK] All {len(required)} TUI files exist")
    return True


def test_2_tui_modules_import_cleanly():
    """All TUI modules must import without error."""
    modules = [
        ("ui.app",           ["HermesApp", "UserMessageSent", "OrchestratorResponse", "ModeChanged"]),
        ("ui.panels.chat",   ["ChatPanel", "UserMessageWidget", "HermesMessageWidget", "ProcessingIndicator", "SPINNER_VERBS"]),
        ("ui.panels.status_bar", ["StatusBar"]),
    ]
    failures = []
    for module_path, symbols in modules:
        try:
            mod = importlib.import_module(module_path)
            for sym in symbols:
                if not hasattr(mod, sym):
                    failures.append(f"{module_path}.{sym} not found")
        except ImportError as e:
            failures.append(f"{module_path}: ImportError: {e}")
        except Exception as e:
            failures.append(f"{module_path}: {type(e).__name__}: {str(e)[:80]}")
    if failures:
        print(f"  [FAIL] Import failures:")
        for f in failures:
            print(f"    - {f}")
        return False
    print(f"  [OK] All TUI modules import cleanly")
    return True


def test_3_spinner_verbs_count_correct():
    """Must have exactly 30 spinner verbs."""
    from ui.panels.chat import SPINNER_VERBS
    count = len(SPINNER_VERBS)
    if count != 30:
        print(f"  [FAIL] Expected 30 spinner verbs, got {count}")
        return False
    # Verify no duplicates
    unique = set(SPINNER_VERBS)
    if len(unique) != count:
        print(f"  [FAIL] {count - len(unique)} duplicate spinner verbs found")
        return False
    print(f"  [OK] {count} unique spinner verbs loaded")
    return True


def test_4_app_class_has_required_bindings():
    """HermesApp must have Ctrl+S/P/A/Q bindings."""
    from ui.app import HermesApp
    bindings = {b.key: b.action for b in HermesApp.BINDINGS}
    required_keys = ["ctrl+s", "ctrl+p", "ctrl+a", "ctrl+q"]
    missing = [k for k in required_keys if k not in bindings]
    if missing:
        print(f"  [FAIL] Missing bindings: {missing}")
        return False
    print(f"  [OK] All 4 required key bindings present: {required_keys}")
    return True


def test_5_app_has_required_reactives():
    """HermesApp must have all required reactive attributes."""
    from ui.app import HermesApp
    import inspect
    # Check class annotations for reactive attributes
    annotations = {}
    for cls in HermesApp.__mro__:
        annotations.update(getattr(cls, "__annotations__", {}))

    required_reactives = [
        "current_mode", "current_skill", "is_processing",
        "session_cost", "kairos_status"
    ]
    # Also check as class attributes directly
    missing = []
    for attr in required_reactives:
        if not hasattr(HermesApp, attr):
            missing.append(attr)

    if missing:
        print(f"  [FAIL] Missing reactive attributes: {missing}")
        return False
    print(f"  [OK] All {len(required_reactives)} reactive attributes present")
    return True


def test_6_message_classes_exist():
    """All 4 Textual message classes must be defined."""
    from ui.app import (
        UserMessageSent, OrchestratorResponse,
        ModeChanged, KairosStatusUpdate
    )
    from textual.message import Message
    for cls in [UserMessageSent, OrchestratorResponse, ModeChanged, KairosStatusUpdate]:
        assert issubclass(cls, Message), f"{cls.__name__} must be a Textual Message subclass"
    print(f"  [OK] All 4 message classes are valid Textual Message subclasses")
    return True


def test_7_css_file_has_required_selectors():
    """hermes.css must define the required layout selectors."""
    css_path = Path("ui/hermes.css")
    if not css_path.exists():
        print("  [FAIL] ui/hermes.css not found")
        return False
    content = css_path.read_text()
    required = [
        "#chat-panel",
        "#main-layout",
        "#chat-history",
        "#chat-input",
        ".user-message",
        ".hermes-message",
    ]
    missing = [s for s in required if s not in content]
    if missing:
        print(f"  [FAIL] CSS missing selectors: {missing}")
        return False
    print(f"  [OK] hermes.css has all {len(required)} required selectors")
    return True


def test_8_main_py_has_ui_command():
    """main.py must have the 'ui' command to launch the TUI."""
    main_path = Path("main.py")
    if not main_path.exists():
        print("  [FAIL] main.py not found")
        return False
    content = main_path.read_text()
    has_ui_command = (
        "def ui(" in content
        and "HermesApp" in content
        and "hermes_app.run()" in content
    )
    if not has_ui_command:
        print("  [FAIL] main.py missing 'ui' command or HermesApp.run() call")
        return False
    print(f"  [OK] main.py has 'ui' command that launches HermesApp")
    return True


def test_9_widget_rendering_does_not_crash():
    """UserMessageWidget and HermesMessageWidget must render without crash."""
    from ui.panels.chat import UserMessageWidget, HermesMessageWidget
    from ui.app import OrchestratorResponse
    from rich.text import Text

    # UserMessage
    w = UserMessageWidget("list all files in the directory")
    rendered = w.render()
    assert isinstance(rendered, Text)
    assert "list all files" in rendered.plain

    # HermesMessage success
    r = OrchestratorResponse(
        user_request="test", final_output="core/\ntools/\n",
        tool_name="list_directory", success=True,
        stage_reached=12, tier3_called=False,
        latency_seconds=1.5, trace_id="abc12345", skill_ids=[]
    )
    w2 = HermesMessageWidget(r)
    rendered2 = w2.render()
    assert isinstance(rendered2, Text)
    assert "list_directory" in rendered2.plain

    # HermesMessage error
    r_err = OrchestratorResponse(
        user_request="bad", final_output="Error: failed",
        tool_name=None, success=False,
        stage_reached=4, tier3_called=False,
        latency_seconds=0.5, trace_id="err12345", skill_ids=[],
        error="failed"
    )
    w3 = HermesMessageWidget(r_err)
    assert "error" in w3.classes

    print(f"  [OK] Both widget types render correctly without crash")
    return True


def test_10_status_bar_renders_all_modes():
    """StatusBar must render correctly for all 3 modes."""
    from ui.panels.status_bar import StatusBar
    from rich.text import Text

    bar = StatusBar()

    for mode in ("safe", "plan", "auto"):
        bar.mode = mode
        rendered = bar._render_status()
        assert isinstance(rendered, Text)
        assert mode.upper() in rendered.plain, f"Mode {mode.upper()} not in status bar render"

    print(f"  [OK] StatusBar renders correctly for safe/plan/auto modes")
    return True


def main():
    print("=" * 65)
    print("HERMES — Week 15 Final Validation")
    print("Textual TUI — Structure + Chat Panel")
    print("=" * 65)

    tests = [
        ("All TUI files exist",                          test_1_all_tui_files_exist),
        ("All TUI modules import cleanly",               test_2_tui_modules_import_cleanly),
        ("30 unique spinner verbs loaded",               test_3_spinner_verbs_count_correct),
        ("HermesApp has Ctrl+S/P/A/Q bindings",         test_4_app_class_has_required_bindings),
        ("HermesApp has all reactive attributes",        test_5_app_has_required_reactives),
        ("All 4 message classes are Textual Messages",   test_6_message_classes_exist),
        ("hermes.css has all required selectors",        test_7_css_file_has_required_selectors),
        ("main.py has 'ui' command",                     test_8_main_py_has_ui_command),
        ("Widget rendering does not crash",              test_9_widget_rendering_does_not_crash),
        ("StatusBar renders all 3 modes",                test_10_status_bar_renders_all_modes),
    ]

    passed_all = True
    for name, test_fn in tests:
        print(f"\n[TEST] {name}")
        try:
            passed = test_fn()
            if not passed:
                passed_all = False
        except Exception as e:
            import traceback
            print(f"  [FAIL] ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
            passed_all = False

    print("\n" + "=" * 65)
    if passed_all:
        print("WEEK 15 COMPLETE: TUI structure and chat panel operational.")
        print()
        print("What is now working:")
        print("  [OK] ui/app.py — HermesApp with Orchestrator wired")
        print("  [OK] ui/panels/chat.py — Chat panel with message history")
        print("  [OK] ui/panels/status_bar.py — Status bar with mode/skill/cost")
        print("  [OK] ui/hermes.css — Full TUI stylesheet")
        print("  [OK] main.py ui command — python main.py ui")
        print()
        print("Test the live TUI now:")
        print("  python main.py ui")
        print("  python main.py ui --mode safe --project myproject")
        print()
        print("Ready for Week 16 (right panel: Tool Trace, Memory, Task Queue tabs).")
    else:
        print("WEEK 15 INCOMPLETE: Fix failures above before Week 16.")
    print("=" * 65)


if __name__ == "__main__":
    main()
