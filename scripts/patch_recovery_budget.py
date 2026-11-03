from pathlib import Path

target_file = Path(r"C:\Users\SUBBU\Downloads\hermes\core\agent_loop\loop.py")
text = target_file.read_text(encoding="utf-8")

text = text.replace("self._total_recovery_budget: int = 4", "self._total_recovery_budget: int = 2")
text = text.replace('max_recovery = getattr(self, "_total_recovery_budget", 4)', 'max_recovery = getattr(self, "_total_recovery_budget", 2)')

target_file.write_text(text, encoding="utf-8")
print("Updated recovery budget to 2")
