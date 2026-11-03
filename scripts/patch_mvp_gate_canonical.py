with open("core/agent_loop/mvp_gate.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

start_idx = None
end_idx = None

for i, line in enumerate(lines):
    if "# 2. index.html" in line:
        start_idx = i
    if start_idx is not None and "style_cands = [" in line:
        end_idx = i
        break

print(f"Found block from line {start_idx + 1} to {end_idx + 1}")

replacement_lines = [
    "        # Resolve canonical paths via ProjectContract (Phase B)\n",
    "        from core.project_contract import ProjectContract\n",
    "        contract = ProjectContract.create_or_load(ws)\n",
    "        canonical_html_rel = contract.canonical_html\n",
    "        canonical_css_rel = contract.canonical_css\n",
    "        canonical_js_rel = contract.canonical_js\n",
    "\n",
    "        # 2. HTML entrypoint\n",
    "        html_path = ws / canonical_html_rel\n",
    "        if not html_path.exists():\n",
    '            alt_html = ws / ("index.html" if "static/" in canonical_html_rel else "static/index.html")\n',
    "            if alt_html.exists() and alt_html.stat().st_size >= 50:\n",
    "                html_path = alt_html\n",
    "\n",
    "        if not html_path.exists() or html_path.stat().st_size < 50:\n",
    "            missing.append(canonical_html_rel)\n",
    "        else:\n",
    "            try:\n",
    "                html_txt = html_path.read_text(encoding='utf-8', errors='ignore')\n",
    '                has_script = bool(re.search(r\'<script[^>]+src=["\\\']([^"\\\']+\\.js)["\\\']\', html_txt, re.I))\n',
    "                if not has_script:\n",
    '                    missing.append(f"{canonical_html_rel} (missing entrypoint <script> tag)")\n',
    "            except Exception:\n",
    "                pass\n",
    "\n",
    "        # 3. Primary JavaScript entrypoint (contract-driven & dynamic)\n",
    "        expected_js = canonical_js_rel\n",
    "        if html_path.exists():\n",
    "            try:\n",
    "                html_txt_check = html_path.read_text(encoding='utf-8', errors='ignore')\n",
    '                scripts_found = re.findall(r\'<script[^>]+src=["\\\']([^"\\\']+\\.js)["\\\']\', html_txt_check, re.I)\n',
    "                for s in scripts_found:\n",
    '                    if not s.startswith(("http://", "https://", "//")):\n',
    "                        clean_name = Path(s.lstrip('./')).name\n",
    '                        expected_js = f"static/{clean_name}" if "static/" in canonical_html_rel else clean_name\n',
    "                        break\n",
    "            except Exception:\n",
    "                pass\n",
    "        elif pkg_path.exists():\n",
    "            try:\n",
    "                pkg_data_check = json.loads(pkg_path.read_text(encoding='utf-8', errors='ignore'))\n",
    '                if pkg_data_check.get("main") and isinstance(pkg_data_check["main"], str):\n',
    '                    expected_js = pkg_data_check["main"].lstrip("./")\n',
    "            except Exception:\n",
    "                pass\n",
    "\n",
    "        main_cands = [\n",
    "            expected_js,\n",
    "            canonical_js_rel,\n",
    '            "static/app.js",\n',
    '            "static/main.js",\n',
    '            "app.js",\n',
    '            "main.js",\n',
    '            "src/main.js",\n',
    '            "src/app.js",\n',
    '            "index.js",\n',
    '            "script.js",\n',
    "        ]\n",
    "        seen_cands = set()\n",
    "        ordered_cands = []\n",
    "        for c in main_cands:\n",
    "            if c not in seen_cands:\n",
    "                seen_cands.add(c)\n",
    "                ordered_cands.append(c)\n",
    "\n",
    "        found_main: Optional[Path] = None\n",
    "        for p in ordered_cands:\n",
    "            cand_p = ws / p\n",
    "            if cand_p.exists() and cand_p.stat().st_size > 40:\n",
    "                found_main = cand_p\n",
    "                break\n",
    "\n",
    "        if not found_main:\n",
    "            missing.append(expected_js)\n",
    "        else:\n",
    "            try:\n",
    "                from core.code_completeness import validate_implementation_completeness\n",
    "                code_txt = found_main.read_text(encoding='utf-8', errors='ignore')\n",
    "                is_complete, comp_err = validate_implementation_completeness(code_txt, found_main.name)\n",
    "                if not is_complete:\n",
    '                    missing.append(f"{found_main.name} (incomplete or contains placeholder stubs: {comp_err})")\n',
    "            except Exception as e:\n",
    '                logger.debug(f"WebsiteMvpGate: completeness check notice on {found_main}: {e}")\n',
    "\n",
    "        # 4. Stylesheet (must exist, > 20 bytes, and connected)\n",
    '        style_cands = [canonical_css_rel, "static/style.css", "style.css", "src/style.css", "styles.css", "src/styles.css"]\n',
]

new_lines = lines[:start_idx] + replacement_lines + lines[end_idx + 1:]
with open("core/agent_loop/mvp_gate.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)
print("Updated core/agent_loop/mvp_gate.py successfully!")
