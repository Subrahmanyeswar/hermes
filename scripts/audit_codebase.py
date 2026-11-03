import os
import re

search_terms = [
    r"node\s+--check",
    r"\.pending",
    r"recovery_checkpoint",
    r"progress\.json",
    r"project_contract",
    r"FUNCTIONAL_EVALUATION",
    r"ARTIFACT_WRITE",
    r"js_syntax_validator",
    r"syntax_repair",
]

repo_root = r"C:\Users\SUBBU\Downloads\hermes"
target_dirs = ["core", "models", "tools", "tests", "config"]

results = {term: [] for term in search_terms}

for target_dir in target_dirs:
    dir_path = os.path.join(repo_root, target_dir)
    if not os.path.exists(dir_path):
        continue
    for root, dirs, files in os.walk(dir_path):
        dirs[:] = [d for d in dirs if d not in {".git", "venv", ".pytest_cache", "__pycache__"}]
        for file in files:
            if file.endswith((".py", ".json")):
                path = os.path.join(root, file)
                rel_path = os.path.relpath(path, repo_root)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        for term in search_terms:
                            matches = list(re.finditer(term, content))
                            if matches:
                                results[term].append((rel_path, len(matches)))
                except Exception as e:
                    pass

for term, file_counts in results.items():
    print(f"=== Search: {term} ===")
    for rel_path, count in file_counts:
        print(f"  {rel_path}: {count} occurrences")
