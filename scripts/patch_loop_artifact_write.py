with open("core/agent_loop/loop.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace both occurrences of FUNCTIONAL_EVALUATION in _advance_task and _complete_task_for_target_file
target = "source_type=EvidenceSourceType.FUNCTIONAL_EVALUATION,"
replacement = "source_type=EvidenceSourceType.ARTIFACT_WRITE,"

count = content.count(target)
print(f"Found {count} occurrences of target")
if count > 0:
    content = content.replace(target, replacement)
    with open("core/agent_loop/loop.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Updated loop.py successfully!")
else:
    print("No occurrences found!")
