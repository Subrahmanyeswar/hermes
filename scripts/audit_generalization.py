import os
import re

targets = ['Campus Event', 'Phase 4E', 'AI Hackathon', 'cards-container', 'search-input', 'item-modal']
dirs = ['core', 'models', 'tools', 'kairos', 'ui']
found_any = False
for d in dirs:
    if not os.path.exists(d):
        continue
    for root, _, files in os.walk(d):
        for f in files:
            if f.endswith('.py'):
                path = os.path.join(root, f)
                content = open(path, encoding='utf-8', errors='ignore').read()
                for t in targets:
                    if t.lower() in content.lower():
                        # Find line numbers
                        lines = content.split('\n')
                        for idx, line in enumerate(lines, 1):
                            if t.lower() in line.lower():
                                clean_line = line.strip().encode('ascii', errors='replace').decode('ascii')
                                print(f"{path}:{idx} -> {clean_line[:100]}")
                                found_any = True

if not found_any:
    print("CLEAN: No overfitted strings found in runtime codebase.")
