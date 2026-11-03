import re
from pathlib import Path

ws = Path(r"C:\Users\SUBBU\Downloads\HERMES_FINAL_REVIEW_DEMO")
html_text = (ws / "index.html").read_text(encoding="utf-8")
css_text = (ws / "style.css").read_text(encoding="utf-8")

html_classes = set(re.findall(r'class=["\']([^"\']+)["\']', html_text))
flat_html_classes = set()
for c in html_classes:
    for item in c.split():
        flat_html_classes.add(item)

css_selectors = set(re.findall(r'\.([a-zA-Z0-9_\-]+)', css_text))

print(f"Total classes in HTML: {len(flat_html_classes)}")
print(f"Total class selectors in CSS: {len(css_selectors)}")
missing_in_css = flat_html_classes - css_selectors
print("HTML classes NOT in CSS (total " + str(len(missing_in_css)) + "):")
for c in sorted(missing_in_css):
    print(f"  .{c}")

# Image sources in HTML
imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', html_text)
print("\nImages in index.html:")
for img in imgs:
    print("  ", img)
