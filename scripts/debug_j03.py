import sys
sys.path.insert(0, ".")
from pathlib import Path
import tempfile
from core.agent_loop.completion import CompletionPolicy

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    (tmp / "index.html").write_text(
        '<!DOCTYPE html><html><head><title>Test App</title><link rel="stylesheet" href="style.css"></head>'
        '<body><div id="app"><button id="existing_btn">Click Me</button><input id="text_input" type="text"/></div>'
        '<script src="app.js"></script></body></html>',
        encoding='utf-8'
    )
    (tmp / "style.css").write_text('body { margin: 0; padding: 20px; font-family: sans-serif; }', encoding='utf-8')
    js_content = (
        '// Application logic\n'
        'console.log("Initializing app...");\n'
        'const el = document.getElementById("missing_target_btn");\n'
        'if (el) { el.addEventListener("click", () => console.log("clicked")); }\n'
        'console.log("Setup complete for active dashboard view.");\n'
    )
    (tmp / "app.js").write_text(js_content, encoding='utf-8')
    policy = CompletionPolicy()
    ok, reason, issues = policy.evaluate_completion('Build full web app with interactive controls', workspace=tmp, written_files=['index.html', 'style.css', 'app.js'])
    print('ok:', ok)
    print('reason:', reason)
    print('issues:', issues)
