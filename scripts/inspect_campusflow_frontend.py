import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

static_dir = Path(r"C:\Users\SUBBU\Downloads\testing 1\static")
html_text = (static_dir / "index.html").read_text(encoding="utf-8")
css_text = (static_dir / "style.css").read_text(encoding="utf-8")

# Extract IDs from HTML
html_ids = set(re.findall(r'id=["\']([^"\']+)["\']', html_text))

# Extract classes from HTML
raw_classes = re.findall(r'class=["\']([^"\']+)["\']', html_text)
html_classes = set()
for c in raw_classes:
    for item in c.split():
        html_classes.add(item)

# Extract CSS class selectors
css_classes = set(re.findall(r'\.([a-zA-Z0-9_-]+)', css_text))

print(f"Total HTML IDs: {len(html_ids)}")
print(f"HTML IDs: {sorted(html_ids)}")
print(f"\nTotal HTML Classes: {len(html_classes)}")
print(f"Total CSS Selectors: {len(css_classes)}")

missing_in_css = sorted(html_classes - css_classes)
print(f"\nHTML Classes NOT found in CSS ({len(missing_in_css)}):")
for c in missing_in_css:
    print(f"  .{c}")
