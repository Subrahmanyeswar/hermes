from pathlib import Path

target_file = Path(r"C:\Users\SUBBU\Downloads\hermes\core\agent_loop\loop.py")
text = target_file.read_text(encoding="utf-8")

target = '        current_tier = getattr(self.orchestrator, "_active_tier", 1)'
replacement = """        raw_tier = getattr(self.orchestrator, "_active_tier", 1)
        try:
            current_tier = int(raw_tier) if not isinstance(raw_tier, (str, bytes)) or raw_tier.isdigit() else 1
        except Exception:
            current_tier = 1"""

if target in text:
    new_text = text.replace(target, replacement, 1)
    target_file.write_text(new_text, encoding="utf-8")
    print("Updated loop.py successfully")
else:
    print("Target not found in loop.py")
