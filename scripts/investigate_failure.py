import re
import os
import json

ws = 'C:/Users/SUBBU/Downloads/rocket12 hermes test'

print("=== 1. Workspace Files in rocket12 hermes test ===")
for root, dirs, files in os.walk(ws):
    if '.git' in root or 'node_modules' in root:
        continue
    for f in files:
        p = os.path.join(root, f)
        print(f" - {p} ({os.path.getsize(p)} bytes)")

print("\n=== 2. ID / Selector Analysis ===")
with open(os.path.join(ws, 'index.html'), 'r', encoding='utf-8') as f:
    html = f.read()

with open(os.path.join(ws, 'style.css'), 'r', encoding='utf-8') as f:
    css = f.read()

html_ids = set(re.findall(r'id=["\']([^"\']+)["\']', html))
css_ids = set(re.findall(r'#([a-zA-Z0-9_\-]+)', css))

print("HTML IDs found:", sorted(list(html_ids)))
print("\nCSS #ID selectors found:", sorted(list(css_ids)))

common = html_ids.intersection(css_ids)
in_css_only = css_ids - html_ids
in_html_only = html_ids - css_ids

print(f"\nCommon IDs: {len(common)}")
print(f"In CSS but missing from HTML ({len(in_css_only)}):", sorted(list(in_css_only)))
print(f"In HTML but missing from CSS ({len(in_html_only)}):", sorted(list(in_html_only)))

print("\n=== 3. Scripts referenced in HTML ===")
scripts = re.findall(r'<script[^>]*src=["\']([^"\']+)["\']', html)
print("Scripts referenced in index.html:", scripts)

for s in scripts:
    sp = os.path.join(ws, s)
    print(f" - {s}: exists={os.path.exists(sp)}")

print("\n=== 4. CSS referenced in HTML ===")
links = re.findall(r'<link[^>]*href=["\']([^"\']+)["\']', html)
print("Links referenced in index.html:", links)
for l in links:
    lp = os.path.join(ws, l)
    print(f" - {l}: exists={os.path.exists(lp)}")
