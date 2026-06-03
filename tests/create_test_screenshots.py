#!/usr/bin/env python3
"""
Create 3 synthetic test screenshots for screenshot-to-code testing.
These are simple PNG images with basic UI layouts drawn using Pillow.
If Pillow is not installed, it will be installed automatically.

Run: python tests/create_test_screenshots.py
Output: tests/screenshots/ directory with 3 PNG files.
"""
import subprocess
import sys
from pathlib import Path


def ensure_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
        return True
    except ImportError:
        print("Installing Pillow for test screenshot generation...")
        subprocess.run([sys.executable, "-m", "pip", "install", "Pillow", "--quiet"], check=True)
        return True


def create_screenshot_1_login_form(output_path: Path) -> None:
    """Create a simple login form screenshot."""
    from PIL import Image, ImageDraw

    width, height = 400, 500
    img = Image.new("RGB", (width, height), color="#1F2937")  # Dark background
    draw = ImageDraw.Draw(img)

    # Header
    draw.rectangle([0, 0, width, 60], fill="#111827")
    draw.text((20, 20), "HERMES Login", fill="#F9FAFB")

    # Card
    draw.rounded_rectangle([40, 100, 360, 440], radius=8, fill="#374151")

    # Title
    draw.text((160, 120), "Sign In", fill="#F9FAFB")

    # Email field
    draw.text((60, 170), "Email", fill="#9CA3AF")
    draw.rounded_rectangle([60, 190, 340, 220], radius=4, fill="#1F2937", outline="#4B5563")
    draw.text((70, 200), "user@example.com", fill="#6B7280")

    # Password field
    draw.text((60, 240), "Password", fill="#9CA3AF")
    draw.rounded_rectangle([60, 260, 340, 290], radius=4, fill="#1F2937", outline="#4B5563")
    draw.text((70, 270), "••••••••", fill="#6B7280")

    # Remember me checkbox
    draw.rectangle([60, 310, 76, 326], outline="#4B5563")
    draw.text((85, 310), "Remember me", fill="#9CA3AF")

    # Submit button
    draw.rounded_rectangle([60, 350, 340, 385], radius=4, fill="#3B82F6")
    draw.text((155, 360), "Sign In", fill="#FFFFFF")

    # Footer link
    draw.text((110, 400), "Don't have an account? Sign up", fill="#3B82F6")

    img.save(str(output_path), "PNG")
    print(f"  Created: {output_path}")


def create_screenshot_2_dashboard(output_path: Path) -> None:
    """Create a simple dashboard with stats cards."""
    from PIL import Image, ImageDraw

    width, height = 800, 500
    img = Image.new("RGB", (width, height), color="#F3F4F6")  # Light background
    draw = ImageDraw.Draw(img)

    # Sidebar
    draw.rectangle([0, 0, 200, height], fill="#1E3A5F")
    draw.text((20, 30), "Dashboard", fill="#FFFFFF")
    for i, item in enumerate(["Overview", "Analytics", "Reports", "Settings"]):
        y = 100 + i * 50
        if i == 0:
            draw.rectangle([0, y - 5, 200, y + 30], fill="#2563EB")
        draw.text((30, y), f"  {item}", fill="#FFFFFF" if i == 0 else "#93C5FD")

    # Main content
    draw.text((230, 30), "Overview", fill="#111827")
    draw.text((230, 55), "Welcome back, Admin", fill="#6B7280")

    # Stat cards
    cards = [
        ("Total Users", "12,450", "#3B82F6"),
        ("Revenue", "$48,290", "#10B981"),
        ("Orders", "1,234", "#F59E0B"),
        ("Pending", "89", "#EF4444"),
    ]
    for i, (label, value, colour) in enumerate(cards):
        x = 220 + i * 145
        draw.rounded_rectangle([x, 90, x + 130, 160], radius=8, fill="#FFFFFF")
        draw.rectangle([x, 90, x + 4, 160], fill=colour)
        draw.text((x + 15, 105), label, fill="#6B7280")
        draw.text((x + 15, 130), value, fill="#111827")

    # Chart area placeholder
    draw.rounded_rectangle([220, 180, 780, 460], radius=8, fill="#FFFFFF")
    draw.text((460, 310), "Chart Area", fill="#9CA3AF")

    img.save(str(output_path), "PNG")
    print(f"  Created: {output_path}")


def create_screenshot_3_api_docs(output_path: Path) -> None:
    """Create a simple API documentation page screenshot."""
    from PIL import Image, ImageDraw

    width, height = 700, 600
    img = Image.new("RGB", (width, height), color="#FFFFFF")
    draw = ImageDraw.Draw(img)

    # Top nav
    draw.rectangle([0, 0, width, 50], fill="#0F172A")
    draw.text((20, 15), "HERMES API Docs", fill="#F1F5F9")
    draw.text((500, 15), "v1.0   GitHub", fill="#94A3B8")

    # Sidebar
    draw.rectangle([0, 50, 180, height], fill="#F8FAFC")
    draw.text((15, 70), "Getting Started", fill="#0F172A")
    draw.text((15, 95), "Authentication", fill="#3B82F6")
    draw.text((15, 115), "Endpoints", fill="#64748B")
    draw.text((15, 135), "  POST /run", fill="#64748B")
    draw.text((15, 155), "  GET /status", fill="#64748B")
    draw.text((15, 175), "  GET /memory", fill="#64748B")
    draw.text((15, 195), "Errors", fill="#64748B")
    draw.text((15, 215), "Rate Limits", fill="#64748B")

    # Main content
    draw.text((200, 70), "POST /api/run", fill="#0F172A")
    draw.rounded_rectangle([200, 95, 680, 115], radius=4, fill="#DCFCE7")
    draw.text((210, 100), "200 OK", fill="#166534")

    draw.text((200, 130), "Request Body", fill="#374151")
    draw.rounded_rectangle([200, 150, 680, 270], radius=4, fill="#F1F5F9", outline="#E2E8F0")
    code_lines = [
        '  {',
        '    "task": "list all files",',
        '    "mode": "auto",',
        '    "project": "myapp"',
        '  }',
    ]
    for i, line in enumerate(code_lines):
        draw.text((210, 160 + i * 20), line, fill="#0F172A")

    draw.text((200, 285), "Response", fill="#374151")
    draw.rounded_rectangle([200, 305, 680, 420], radius=4, fill="#F1F5F9", outline="#E2E8F0")
    resp_lines = [
        '  {',
        '    "success": true,',
        '    "output": "core/ tools/ memory/",',
        '    "tool": "list_directory",',
        '    "trace_id": "abc12345"',
        '  }',
    ]
    for i, line in enumerate(resp_lines):
        draw.text((210, 315 + i * 18), line, fill="#0F172A")

    img.save(str(output_path), "PNG")
    print(f"  Created: {output_path}")


def main():
    ensure_pillow()

    screenshots_dir = Path("tests/screenshots")
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    print("Creating 3 test screenshots...")
    create_screenshot_1_login_form(screenshots_dir / "test_login_form.png")
    create_screenshot_2_dashboard(screenshots_dir / "test_dashboard.png")
    create_screenshot_3_api_docs(screenshots_dir / "test_api_docs.png")

    print(f"\nAll 3 screenshots saved to: {screenshots_dir}/")
    print("Use these with the screenshot_to_code tool:")
    for f in screenshots_dir.glob("*.png"):
        print(f"  {f}")


if __name__ == "__main__":
    main()
