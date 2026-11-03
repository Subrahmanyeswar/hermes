# scripts/patch_app_fallback.py
from pathlib import Path

app_path = Path("core/server/app.py")
content = app_path.read_text(encoding="utf-8")

old_text = """        if status_val == "COMPLETED" and not final_out:
            created_list = "\\n".join(f"- `{f}`" for f in (all_created or ["index.html"]))
            final_out = (
                f"### Mission Completed Successfully\\n\\n"
                f"**Objective:** {state.mission.prompt or 'Build web application'}\\n\\n"
                f"**Outcome & Deliverables:**\\n{created_list}\\n\\n"
                f"**Verification:** All requirements and behavioral contracts verified.\\n\\n"
                f"**Launch Instructions:** Open `index.html` in your browser or run a local web server to explore the application."
            )"""

new_text = """        if status_val == "COMPLETED" and not final_out:
            created_list = "\\n".join(f"- `{f}`" for f in (all_created or ["index.html"]))
            entry_f = all_created[0] if all_created else 'index.html'
            final_out = (
                f"### Mission Completed\\n\\n"
                f"**Objective:** {state.mission.prompt or 'Build web application'}\\n\\n"
                f"**Outcome & Deliverables:**\\n{created_list}\\n\\n"
                f"**Verification:** Mission reached completion; inspect individual verification checks and evidence log for specific status.\\n\\n"
                f"**Launch Instructions:** Open `{entry_f}` in your browser or run the local application server."
            )"""

norm_content = content.replace("\r\n", "\n")
norm_old = old_text.replace("\r\n", "\n")
norm_new = new_text.replace("\r\n", "\n")

assert norm_old in norm_content, "Target old text not found in app.py"
updated = norm_content.replace(norm_old, norm_new)
app_path.write_text(updated, encoding="utf-8")
print("Successfully patched completion fallback in core/server/app.py")
