# audit_test_coverage.py
"""
Audit script to map test coverage across the Hermes codebase.

Steps:
1. Walk the repository and collect all Python source files (excluding tests, venv, .git etc.).
2. Parse each source file with `ast` to extract public symbols – top‑level functions, classes and their methods.
3. Walk the `tests/` directory (including `tests/integration/`) and parse each test file to collect:
    - Imported modules/symbols (via `import` and `from ... import`).
    - Called functions/classes (via `ast.Call`).
    - `pytest.raises` usage to detect failure‑path tests.
4. Build a mapping of source symbols → test symbols.
5. Identify:
    - Modules/files with no tests at all.
    - Functions/classes that are never referenced by any test.
    - `try/except` blocks whose exception types are not covered by a `pytest.raises` test.
6. Render a markdown report `TEST_COVERAGE_GAP_REPORT.md` summarising the gaps and coverage percentages.

The script is deliberately lightweight and uses only the Python standard library, so it can run in any environment.
"""

import ast
import os
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(r"C:/Users/SUBBU/Downloads/hermes")
EXCLUDE_DIRS = {".git", "__pycache__", "venv", ".pytest_cache", "scratch", "generated_projects"}

def is_source_file(p: Path) -> bool:
    return p.suffix == ".py" and "tests" not in p.parts and not any(part in EXCLUDE_DIRS for part in p.parts)

def collect_source_symbols() -> dict:
    """Return a mapping: module_path -> set(symbol_names)."""
    symbols = defaultdict(set)
    for py_file in REPO_ROOT.rglob("*.py"):
        if not is_source_file(py_file):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] Failed to parse {py_file}: {e}")
            continue
        module_name = str(py_file.relative_to(REPO_ROOT)).replace(os.sep, ".")[:-3]  # strip .py
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef):
                symbols[module_name].add(node.name)
            elif isinstance(node, ast.ClassDef):
                symbols[module_name].add(node.name)
                for body_item in node.body:
                    if isinstance(body_item, ast.FunctionDef):
                        symbols[module_name].add(f"{node.name}.{body_item.name}")
        # also collect try/except exception types for failure‑path analysis
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    if handler.type:
                        if isinstance(handler.type, ast.Name):
                            exc_name = handler.type.id
                        elif isinstance(handler.type, ast.Attribute):
                            exc_name = handler.type.attr
                        else:
                            exc_name = ast.unparse(handler.type)
                        symbols[module_name].add(f"EXCEPTION:{exc_name}")
    return symbols

def collect_test_symbols() -> tuple[dict, set]:
    """Return a mapping: imported module -> set(symbols used in tests) and a set of raised exception names."""
    test_symbols = defaultdict(set)
    raised_exceptions = set()
    test_root = REPO_ROOT / "tests"
    for py_file in test_root.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] Failed to parse test {py_file}: {e}")
            continue
        # imports
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name
                    asname = alias.asname or alias.name
                    test_symbols[mod].add(asname)
            elif isinstance(node, ast.ImportFrom):
                module = node.module
                if module is None:
                    continue
                for alias in node.names:
                    name = alias.name
                    asname = alias.asname or name
                    test_symbols[module].add(name)
        # calls
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    test_symbols["__call__"].add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    test_symbols["__call__"].add(node.func.attr)
                # pytest.raises detection
                if isinstance(node.func, ast.Attribute) and node.func.attr == "raises":
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "pytest":
                        if node.args:
                            exc = node.args[0]
                            if isinstance(exc, ast.Name):
                                raised_exceptions.add(exc.id)
                            elif isinstance(exc, ast.Attribute):
                                raised_exceptions.add(exc.attr)
    return test_symbols, raised_exceptions

def map_coverage(source_symbols, test_symbols, raised_exceptions):
    covered = defaultdict(set)
    uncovered = defaultdict(set)
    for module, symbols in source_symbols.items():
        for sym in symbols:
            if sym.startswith("EXCEPTION:"):
                exc_name = sym.split(":", 1)[1]
                if exc_name in raised_exceptions:
                    covered[module].add(sym)
                else:
                    uncovered[module].add(sym)
            else:
                found = False
                for test_mod, test_set in test_symbols.items():
                    if sym in test_set or any(sym.split('.')[-1] == t for t in test_set):
                        found = True
                        break
                if found:
                    covered[module].add(sym)
                else:
                    uncovered[module].add(sym)
    return covered, uncovered

def generate_report(covered, uncovered, source_symbols):
    total_symbols = sum(len(s) for s in source_symbols.values())
    covered_symbols = sum(len(s) for s in covered.values())
    coverage_pct = (covered_symbols / total_symbols * 100) if total_symbols else 0
    lines = []
    lines.append("# TEST COVERAGE GAP REPORT")
    lines.append("")
    lines.append(f"**Overall coverage:** {coverage_pct:.1f}% ({covered_symbols}/{total_symbols} symbols covered)")
    lines.append("")
    # Modules with no tests at all
    no_test_modules = [m for m, syms in source_symbols.items() if m not in covered and m not in uncovered]
    if no_test_modules:
        lines.append("## Modules without any test coverage")
        for m in sorted(no_test_modules):
            lines.append(f"- {m}")
        lines.append("")
    # Per‑module gaps
    lines.append("## Untested symbols per module")
    for mod in sorted(uncovered):
        if not uncovered[mod]:
            continue
        lines.append(f"### {mod}")
        for sym in sorted(uncovered[mod]):
            lines.append(f"- {sym}")
        lines.append("")
    # Failure‑path gaps
    failure_gaps = []
    for mod, syms in uncovered.items():
        for sym in syms:
            if sym.startswith("EXCEPTION:"):
                failure_gaps.append(f"{mod}:{sym.split(':',1)[1]}")
    if failure_gaps:
        lines.append("## Missing failure‑mode tests (exceptions not exercised)")
        for item in failure_gaps:
            lines.append(f"- {item}")
        lines.append("")
    report_path = REPO_ROOT / "TEST_COVERAGE_GAP_REPORT.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {report_path}")

def main():
    source_symbols = collect_source_symbols()
    test_symbols, raised_exceptions = collect_test_symbols()
    covered, uncovered = map_coverage(source_symbols, test_symbols, raised_exceptions)
    generate_report(covered, uncovered, source_symbols)

if __name__ == "__main__":
    main()
