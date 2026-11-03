import re
from pathlib import Path

ws = Path(r"C:\Users\SUBBU\Downloads\HERMES_FINAL_REVIEW_DEMO")
html = (ws / "index.html").read_text(encoding="utf-8")

sections = re.findall(r'<section[^>]*id=["\']([^"\']+)["\'][^>]*>(.*?)</section>', html, re.DOTALL)
print(f"Found {len(sections)} sections in index.html:")
for sid, content in sections:
    print(f"\n=== Section: {sid} (length {len(content)}) ===")
    lines = content.strip().splitlines()
    for l in lines[:15]:
        print(" ", l)
