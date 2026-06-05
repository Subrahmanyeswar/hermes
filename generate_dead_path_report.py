import ast
import pathlib
import os

repo_root = pathlib.Path(r"C:/Users/SUBBU/Downloads/hermes")
report_path = repo_root / "DEAD_PATH_REPORT.md"

# Helper to read file safely
def safe_read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        try:
            return path.read_text(encoding="latin-1", errors="ignore")
        except Exception:
            return ""

# Collect definitions (functions and classes)
definitions = {}
for py_path in repo_root.rglob('*.py'):
    rel = py_path.relative_to(repo_root)
    try:
        tree = ast.parse(safe_read_text(py_path))
    except Exception:
        continue
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions.setdefault(rel, []).append(('function', node.name))
        elif isinstance(node, ast.ClassDef):
            definitions.setdefault(rel, []).append(('class', node.name))

# Initialize usage counters
usage_counts = { (rel, kind, name): 0 for rel, defs in definitions.items() for kind, name in defs }

# Scan all .py files for name occurrences (excluding definition file)
for py_path in repo_root.rglob('*.py'):
    content = safe_read_text(py_path)
    rel = py_path.relative_to(repo_root)
    for (def_rel, kind, name), _ in list(usage_counts.items()):
        if def_rel == rel:
            continue
        if name in content:
            usage_counts[(def_rel, kind, name)] += content.count(name)

# Build report lines
lines = ["# Dead Path Detection Report", "", f"Generated on {pathlib.Path().absolute()}", "", "## Unused Definitions (potential dead code)", ""]
for (rel, kind, name), cnt in usage_counts.items():
    if cnt == 0:
        lines.append(f"- `{kind}` `{name}` defined in `{rel}` appears to have no usages.")

# Detect duplicate definitions (same name in multiple modules)
name_to_locations = {}
for rel, defs in definitions.items():
    for kind, name in defs:
        name_to_locations.setdefault(name, []).append((rel, kind))
for name, locs in name_to_locations.items():
    if len(locs) > 1:
        lines.append(f"\n### Duplicate definition: `{name}` found in:")
        for rel, kind in locs:
            lines.append(f"  - `{kind}` in `{rel}`")

# Simple config key detection (assignments in config/*.py)
config_keys = set()
config_dir = repo_root / "config"
for cfg in config_dir.rglob('*.py'):
    try:
        tree = ast.parse(safe_read_text(cfg))
    except Exception:
        continue
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    config_keys.add(target.id)

unused_keys = []
for key in config_keys:
    used = False
    for py_path in repo_root.rglob('*.py'):
        if key in safe_read_text(py_path):
            used = True
            break
    if not used:
        unused_keys.append(key)

if unused_keys:
    lines.append("\n## Unused Config Keys")
    for k in unused_keys:
        lines.append(f"- `{k}`")

# Write report
report_path.write_text("\n".join(lines), encoding='utf-8')
print(f"DEAD_PATH_REPORT generated at {report_path}")
