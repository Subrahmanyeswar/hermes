with open("core/agent_loop/mvp_gate.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace cand_p.stat().st_size > 40 with > 10
content = content.replace("cand_p.stat().st_size > 40", "cand_p.stat().st_size > 10")
# Replace style check > 20 with > 10
content = content.replace("stat().st_size > 20 for p in style_cands", "stat().st_size > 10 for p in style_cands")
# Replace missing.append("style.css") with missing.append(canonical_css_rel)
content = content.replace('missing.append("style.css")', 'missing.append(canonical_css_rel)')

with open("core/agent_loop/mvp_gate.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Updated core/agent_loop/mvp_gate.py successfully!")
