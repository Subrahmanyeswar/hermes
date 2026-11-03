from pathlib import Path

p = Path("core/project_contract.py")
txt = p.read_text(encoding="utf-8").replace("\r\n", "\n")

target = '''        # Handle ambiguity without creating duplicates
        if has_static_index and has_root_index:
            logger.info("ProjectContract: Both root and static index.html exist. Inspecting mounts to disambiguate.")
            if has_static_mount or ("static" in p_lower and "root" not in p_lower):
                selected_layout = "static"
            elif "root" in p_lower and "static" not in p_lower:
                selected_layout = "root"
            elif backend_file and has_static_mount:
                selected_layout = "static"
            elif not has_static_mount and not ("static" in p_lower or "root" in p_lower):
                # Return ambiguous error layout to prevent split-brain writes (Section 5.1)
                canonical_js_name = cls.determine_canonical_js(prompt, ws, layout="root")
                return "ambiguous", {
                    "error": "WORKSPACE_LAYOUT_AMBIGUOUS",
                    "message": "Both root and static index.html exist without mount or prompt cues to disambiguate.",
                    "canonical_html": "index.html",
                    "canonical_css": "style.css",
                    "canonical_js": canonical_js_name,
                }
            else:
                selected_layout = "static" if (has_static_mount or backend_file) else "root"'''

replacement = '''        # Handle ambiguity without creating duplicates
        if has_static_index and has_root_index:
            logger.info("ProjectContract: Both root and static index.html exist. Inspecting mounts and backend files to disambiguate.")
            if has_static_mount or ("static" in p_lower and "root" not in p_lower):
                selected_layout = "static"
            elif "root" in p_lower and "static" not in p_lower:
                selected_layout = "root"
            elif backend_file:
                # Backend file (FastAPI/Flask) disambiguates conflicting entrypoints to static/
                selected_layout = "static"
            elif not has_static_mount and not ("static" in p_lower or "root" in p_lower):
                # Pure frontend with conflicting entrypoints and no prompt cues is ambiguous
                canonical_js_name = cls.determine_canonical_js(prompt, ws, layout="root")
                return "ambiguous", {
                    "error": "WORKSPACE_LAYOUT_AMBIGUOUS",
                    "message": "Both root and static index.html exist without mount or prompt cues to disambiguate.",
                    "canonical_html": "index.html",
                    "canonical_css": "style.css",
                    "canonical_js": canonical_js_name,
                }
            else:
                selected_layout = "static" if (has_static_mount or backend_file) else "root"'''

assert target in txt, "Could not find target in project_contract.py"
txt = txt.replace(target, replacement, 1)
p.write_text(txt, encoding="utf-8")
print("Successfully patched project_contract.py layout disambiguation")
