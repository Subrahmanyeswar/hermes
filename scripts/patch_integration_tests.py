from pathlib import Path

p = Path("tests/test_hermes_reliability_integration.py")
content = p.read_text(encoding="utf-8").replace("\r\n", "\n")

# 1. Fix test_i11: store.record -> store.add
content = content.replace("store.record(rec)", "store.add(rec)")

# 2. Fix test_i13 and test_j04: ledger.record_check -> ledger.add_check
content = content.replace("ledger.record_check(chk)", "ledger.add_check(chk)")

# 3. Fix test_j03 fixture
old_j03 = '''    def test_j03_does_not_mark_complete_with_unresolved_contract_error(self, tmp_path):
        """3. Does not mark a mission complete with an unresolved high-confidence contract error."""
        (tmp_path / "index.html").write_text("<html><body><script src='app.js'></script></body></html>", encoding="utf-8")
        (tmp_path / "style.css").write_text("body {}", encoding="utf-8")
        (tmp_path / "app.js").write_text("document.getElementById('missing_target_btn').click();", encoding="utf-8")

        policy = CompletionPolicy()
        ok, reason, issues = policy.evaluate_completion(
            mission_prompt="Build full web app with interactive controls", workspace=tmp_path, written_files=["index.html", "style.css", "app.js"]
        )
        assert ok is False
        assert "contract" in reason.lower()'''

new_j03 = '''    def test_j03_does_not_mark_complete_with_unresolved_contract_error(self, tmp_path):
        """3. Does not mark a mission complete with an unresolved high-confidence contract error."""
        (tmp_path / "index.html").write_text(
            '<!DOCTYPE html><html><head><title>Test App</title><link rel="stylesheet" href="style.css"></head>'
            '<body><div id="app"><button id="existing_btn">Click Me</button><input id="text_input" type="text"/></div>'
            '<script src="app.js"></script></body></html>',
            encoding="utf-8"
        )
        (tmp_path / "style.css").write_text('body { margin: 0; padding: 20px; font-family: sans-serif; }', encoding="utf-8")
        js_content = (
            '// Application logic\\n'
            'console.log("Initializing app...");\\n'
            'const el = document.getElementById("missing_target_btn");\\n'
            'if (el) { el.addEventListener("click", () => console.log("clicked")); }\\n'
            'console.log("Setup complete for active dashboard view.");\\n'
        )
        (tmp_path / "app.js").write_text(js_content, encoding="utf-8")

        policy = CompletionPolicy()
        ok, reason, issues = policy.evaluate_completion(
            mission_prompt="Build full web app with interactive controls", workspace=tmp_path, written_files=["index.html", "style.css", "app.js"]
        )
        assert ok is False
        assert "contract" in reason.lower()'''

assert old_j03 in content, "Could not find old_j03"
content = content.replace(old_j03, new_j03, 1)

p.write_text(content, encoding="utf-8")
print("Successfully updated test_hermes_reliability_integration.py")
