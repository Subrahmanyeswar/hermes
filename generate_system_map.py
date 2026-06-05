import ast, os, json, pathlib

repo_root = pathlib.Path(r"C:/Users/SUBBU/Downloads/hermes")
output_path = repo_root / "SYSTEM_MAP.md"

lines = []
lines.append("# SYSTEM MAP\n")
lines.append("Generated system map of the Hermes codebase.\n")

for py_path in repo_root.rglob("*.py"):
    rel = py_path.relative_to(repo_root)
    try:
        tree = ast.parse(py_path.read_text())
    except Exception as e:
        lines.append(f"## {rel}\n")
        lines.append(f"*Failed to parse: {e}*\n\n")
        continue
    imports = []
    classes = []
    functions = []
    emitters = []
    listeners = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append(f"{module}.{alias.name}" if module else alias.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.FunctionDef):
            functions.append(node.name)
            # simple heuristic for listeners
            if node.name.startswith("on_") or node.name.startswith("handle_"):
                listeners.append(node.name)
        elif isinstance(node, ast.Call):
            # detect emit calls
            if isinstance(node.func, ast.Attribute) and node.func.attr.startswith("emit"):
                emitters.append(ast.unparse(node.func))
            elif isinstance(node.func, ast.Name) and node.func.id.startswith("emit"):
                emitters.append(node.func.id)
    lines.append(f"## {rel}\n")
    if imports:
        lines.append("**Imports:**\n")
        for imp in sorted(set(imports)):
            lines.append(f"- {imp}\n")
    if classes:
        lines.append("**Classes:**\n")
        for cls in sorted(set(classes)):
            lines.append(f"- {cls}\n")
    if functions:
        lines.append("**Functions:**\n")
        for fn in sorted(set(functions)):
            lines.append(f"- {fn}\n")
    if emitters:
        lines.append("**Emitters (calls to emit*):**\n")
        for em in sorted(set(emitters)):
            lines.append(f"- {em}\n")
    if listeners:
        lines.append("**Listeners (functions starting with on_/handle_):**\n")
        for li in sorted(set(listeners)):
            lines.append(f"- {li}\n")
    lines.append("\n")

output_path.write_text("".join(lines), encoding="utf-8")
print(f"SYSTEM_MAP generated at {output_path}")
