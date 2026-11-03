import re
import json
import sys
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

ws = Path(r"C:\Users\SUBBU\Downloads\HERMES_FINAL_REVIEW_DEMO")
html_text = (ws / "index.html").read_text(encoding="utf-8")
js_text = (ws / "main.js").read_text(encoding="utf-8")
css_text = (ws / "style.css").read_text(encoding="utf-8")

print("=== CROSS-FILE AUDIT ===")

# 1. Script and Stylesheet links
scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html_text)
stylesheets = re.findall(r'<link[^>]+href=["\']([^"\']+)["\']', html_text)
print("Script links in HTML:", scripts)
print("Stylesheet links in HTML:", stylesheets)
for s in scripts:
    if not s.startswith(("http://", "https://")):
        exists = (ws / s).exists()
        print(f"  Script {s} exists locally: {exists}")
for s in stylesheets:
    if not s.startswith(("http://", "https://")):
        exists = (ws / s).exists()
        print(f"  Stylesheet {s} exists locally: {exists}")

# 2. Check duplicate IDs in HTML
ids = re.findall(r'\bid=["\']([^"\']+)["\']', html_text)
id_counts = Counter(ids)
duplicates = {k: v for k, v in id_counts.items() if v > 1}
print(f"Total HTML IDs: {len(ids)}, Unique: {len(id_counts)}")
if duplicates:
    print("Duplicate IDs found:", duplicates)
else:
    print("All HTML IDs are unique!")

# 3. Check getElementById in main.js
get_elem_ids = re.findall(r'getElementById\(["\']([^"\']+)["\']\)', js_text)
print(f"getElementById calls in main.js ({len(get_elem_ids)}):")
missing_ids = []
for gid in set(get_elem_ids):
    if gid not in id_counts:
        missing_ids.append(gid)
if missing_ids:
    print("  MISSING IDs in HTML:", missing_ids)
else:
    print("  All getElementById targets exist in index.html!")

# 4. Check data-view consistency
html_views = set(re.findall(r'data-view=["\']([^"\']+)["\']', html_text))
view_sections = set(re.findall(r'id=["\']view-([^"\']+)["\']', html_text))
print("data-view attributes in HTML:", html_views)
print("view sections in HTML (view-*):", view_sections)
view_diff = html_views - view_sections
if view_diff:
    print("  data-view targets without corresponding view-* section:", view_diff)
else:
    print("  All data-view targets have corresponding view-* sections!")

# 5. Functions and Listeners in main.js
fns = re.findall(r'function\s+([a-zA-Z0-9_]+)', js_text)
arrow_fns = re.findall(r'const\s+([a-zA-Z0-9_]+)\s*=\s*\([^)]*\)\s*=>', js_text)
listeners = re.findall(r'addEventListener\(["\']([^"\']+)["\']', js_text)
print("Named functions:", fns)
print("Arrow functions:", arrow_fns)
print("Event listeners attached:", listeners)

# 6. Forms and Sections in HTML
forms = re.findall(r'<form[^>]*id=["\']([^"\']+)["\'][^>]*>', html_text)
sections = re.findall(r'<section[^>]*id=["\']([^"\']+)["\'][^>]*>', html_text)
print("Forms in HTML:", forms)
print("Sections in HTML:", sections)

# 7. Form inputs inspection
for fid in ["testDriveForm", "contactForm"]:
    pattern = rf'<form[^>]*id="{fid}"[^>]*>(.*?)</form>'
    m = re.search(pattern, html_text, re.DOTALL)
    if m:
        form_content = m.group(1)
        inputs = re.findall(r'name=["\']([^"\']+)["\']', form_content)
        print(f"Inputs in {fid}:", inputs)

# 8. View details inspection
idx = html_text.find('id="view-details"')
if idx != -1:
    print("view-details snippet:", html_text[idx:idx+300])

# 9. Check .view-section styling in style.css
print("view-section in CSS:", "view-section" in css_text)
idx_vs = css_text.find("view-section")
if idx_vs != -1:
    print("view-section CSS snippet:", css_text[idx_vs:idx_vs+300])
