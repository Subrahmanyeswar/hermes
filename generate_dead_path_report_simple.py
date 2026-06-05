import ast, pathlib
repo_root = pathlib.Path(r"C:/Users/SUBBU/Downloads/hermes")
report_path = repo_root / "DEAD_PATH_REPORT.md"

# Helper to safely read text
def safe_read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        try:
            return path.read_text(encoding="latin-1", errors="ignore")
        except Exception:
            return ""

# Collect all definitions (function and class names) across the repo
name_locations = {}
for py_path in repo_root.rglob('*.py'):
    rel = py_path.relative_to(repo_root)
    try:
        tree = ast.parse(safe_read(py_path))
    except Exception:
        continue
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            name_locations.setdefault(name, []).append(rel)

# Detect duplicate definitions (same name in multiple files)
duplicate_lines = []
for name, locs in name_locations.items():
    if len(locs) > 1:
        duplicate_lines.append(f"### Duplicate definition: `{name}` found in:")
        for loc in locs:
            duplicate_lines.append(f"  - `{loc}`")

# Simple config key detection (assignments in config/*.py)
config_keys = set()
for cfg_path in (repo_root / "config").rglob('*.py'):
    try:
        tree = ast.parse(safe_read(cfg_path))
    except Exception:
        continue
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    config_keys.add(target.id)

# Find unused config keys (not referenced elsewhere)
unused_keys = []
for key in config_keys:
    used = False
    for py_path in repo_root.rglob('*.py'):
        if key in safe_read(py_path):
            used = True
            break
    if not used:
        unused_keys.append(key)

# Build report
lines = ["# Dead Path Detection Report", "", f"Generated on {pathlib.Path().absolute()}", ""]
if duplicate_lines:
    lines.append("## Duplicate Definitions")
    lines.extend(duplicate_lines)
else:
    lines.append("## Duplicate Definitions\n- None found.")

if unused_keys:
    lines.append("\n## Unused Config Keys")
    for k in unused_keys:
        lines.append(f"- `{k}`")
else:
    lines.append("\n## Unused Config Keys\n- None found.")

report_path.write_text("\n".join(lines), encoding='utf-8')
print(f"DEAD_PATH_REPORT generated at {report_path}")
