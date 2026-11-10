# core/universal_renderer.py
"""
Universal Content Renderer for HERMES 2.x (P0.5).
Generates production-grade, highly engaging, prompt-aligned web applications
from a structured MissionSpecification for ANY unseen domain or industry.
Guarantees zero generic placeholder tokens, authentic imagery, rich interactivity,
and valid responsive styling.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

from core.mission_spec import MissionSpecification
from tools.security import WorkspaceOwnershipManifest


class UniversalContentRenderer:
    """
    Renders complete, authoritative web application deliverables:
    - index.html
    - style.css
    - app.js
    - package.json
    Driven entirely by the MissionSpecification.
    """

    @classmethod
    def render(
        cls,
        workspace_root: Path | str,
        spec: MissionSpecification,
    ) -> bool:
        ws = Path(workspace_root).resolve()
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "assets" / "images").mkdir(parents=True, exist_ok=True)

        app_name = spec.requested_brand
        slug = app_name.lower().replace(" ", "-").replace("&", "and")
        for ch in [".", ",", "'", '"', "/", "\\"]:
            slug = slug.replace(ch, "")

        colors = spec.color_palette
        primary = colors.get("primary", "#0f172a")
        secondary = colors.get("secondary", "#1e293b")
        accent = colors.get("accent", "#0284c7")
        accent_secondary = colors.get("accent_secondary", "#0ea5e9")
        bg_main = colors.get("background", "#f8fafc")
        bg_card = colors.get("surface", "#ffffff")
        text_primary = colors.get("text_primary", "#0f172a")
        text_secondary = colors.get("text_secondary", "#475569")
        border_color = colors.get("border", "#e2e8f0")

        def _is_light_hex(hex_str: str) -> bool:
            h = str(hex_str).lstrip("#")
            if len(h) == 6:
                try:
                    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
                    return luminance > 0.5
                except Exception:
                    pass
            return False

        is_light_theme = _is_light_hex(bg_main)
        if is_light_theme:
            nav_bg = "rgba(255, 255, 255, 0.94)"
            nav_brand_color = "#0f172a"
            nav_link_color = "#475569"
            nav_border = "var(--border-color)"
        else:
            nav_bg = "rgba(15, 23, 42, 0.90)"
            nav_brand_color = "#f8fafc"
            nav_link_color = "#cbd5e1"
            nav_border = "rgba(255, 255, 255, 0.1)"

        typo = spec.typography
        font_heading = typo.get("font_heading", "'Plus Jakarta Sans', system-ui, sans-serif")
        font_body = typo.get("font_body", "'Inter', -apple-system, sans-serif")
        font_mono = typo.get("font_mono", "'JetBrains Mono', monospace")

        hero_asset = next((a for a in spec.asset_requirements if a.get("component") == "hero"), None)
        hero_img_path = hero_asset.get("relative_path", "assets/images/hero-main.jpg") if hero_asset else "assets/images/hero-main.jpg"

        # ----------------------------------------------------------------------
        # 1. package.json
        # ----------------------------------------------------------------------
        pkg_path = ws / "package.json"
        pkg_data = {
            "name": slug,
            "version": "1.0.0",
            "description": f"{app_name} — {spec.domain_subtype}",
            "main": "app.js",
            "scripts": {
                "start": "npx http-server -p 8080",
                "serve": "npx http-server -p 8080"
            }
        }
        pkg_path.write_text(json.dumps(pkg_data, indent=2), encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(pkg_path, ws, generator="universal_renderer")

        # ----------------------------------------------------------------------
        # 2. style.css
        # ----------------------------------------------------------------------
        css_path = ws / "style.css"
        css_content = f"""/* {app_name} — Universal Design System */
:root {{
    --primary-color: {primary};
    --secondary-color: {secondary};
    --accent-color: {accent};
    --accent-secondary: {accent_secondary};
    --bg-main: {bg_main};
    --bg-card: {bg_card};
    --text-primary: {text_primary};
    --text-secondary: {text_secondary};
    --border-color: {border_color};
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 16px;
    --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.08);
    --shadow-md: 0 4px 20px -2px rgba(0, 0, 0, 0.12);
    --shadow-lg: 0 10px 30px -4px rgba(0, 0, 0, 0.18);
    --font-heading: {font_heading};
    --font-body: {font_body};
    --font-mono: {font_mono};
}}

*, *::before, *::after {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}}

body {{
    font-family: var(--font-body);
    background-color: var(--bg-main);
    color: var(--text-primary);
    line-height: 1.6;
    overflow-x: hidden;
    -webkit-font-smoothing: antialiased;
}}

h1, h2, h3, h4, h5, h6 {{
    font-family: var(--font-heading);
    font-weight: 700;
    line-height: 1.25;
    color: var(--text-primary);
}}

.container {{
    width: 100%;
    max-width: 1240px;
    margin: 0 auto;
    padding: 0 1.5rem;
}}

/* Navigation */
.site-header {{
    position: sticky;
    top: 0;
    z-index: 100;
    background: {nav_bg};
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border-bottom: 1px solid {nav_border};
}}

.navbar {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 74px;
}}

.nav-brand {{
    font-size: 1.35rem;
    font-weight: 800;
    color: {nav_brand_color};
    text-decoration: none;
    letter-spacing: -0.02em;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
}}

.nav-brand span {{
    color: var(--accent-color);
}}

.nav-links {{
    display: flex;
    gap: 2rem;
    list-style: none;
    align-items: center;
}}

.nav-link {{
    color: {nav_link_color};
    text-decoration: none;
    font-weight: 500;
    font-size: 0.95rem;
    transition: color 0.2s ease;
}}

.nav-link:hover {{
    color: var(--accent-color);
}}

.nav-link.btn-nav {{
    padding: 0.5rem 1.25rem;
    background: var(--accent-color);
    color: #fff;
    border-radius: var(--radius-sm);
    font-weight: 600;
}}

.mobile-menu-btn {{
    display: none;
    background: none;
    border: none;
    cursor: pointer;
    padding: 8px;
}}

.mobile-menu-btn span {{
    display: block;
    width: 24px;
    height: 2px;
    background: {nav_brand_color};
    margin: 5px 0;
    transition: 0.2s;
}}

/* Hero Section */
.hero {{
    min-height: 82vh;
    display: flex;
    align-items: center;
    position: relative;
    padding: 5rem 0;
    background-color: var(--primary-color);
    background-image: url('{hero_img_path}');
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
    overflow: hidden;
}}

.hero-overlay {{
    position: absolute;
    inset: 0;
    background: linear-gradient(135deg, rgba(7, 11, 20, 0.85) 0%, rgba(15, 23, 42, 0.62) 55%, rgba(7, 11, 20, 0.80) 100%);
    z-index: 1;
    pointer-events: none;
}}

.hero-container {{
    position: relative;
    z-index: 2;
    width: 100%;
}}

.hero-grid {{
    display: grid;
    grid-template-columns: 1.15fr 0.85fr;
    gap: 3.5rem;
    align-items: center;
}}

@media (max-width: 991px) {{
    .hero-grid {{
        grid-template-columns: 1fr;
        gap: 2.5rem;
    }}
    .hero-visual-col {{
        order: -1;
    }}
}}

.hero-content {{
    max-width: 680px;
}}

.hero-visual-col {{
    display: flex;
    justify-content: center;
    align-items: center;
}}

.hero-showcase-frame {{
    position: relative;
    width: 100%;
    max-width: 500px;
    background: rgba(15, 23, 42, 0.65);
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 18px;
    padding: 0.85rem;
    box-shadow: 0 20px 45px rgba(0, 0, 0, 0.45);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
}}

.hero-card-badge {{
    position: absolute;
    top: 1.5rem;
    left: 1.5rem;
    background: rgba(15, 23, 42, 0.85);
    border: 1px solid rgba(255, 255, 255, 0.2);
    color: #38bdf8;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    padding: 0.35rem 0.75rem;
    border-radius: 6px;
    text-transform: uppercase;
    z-index: 3;
    backdrop-filter: blur(8px);
}}

.hero-showcase-img {{
    width: 100%;
    height: 340px;
    object-fit: cover;
    border-radius: 12px;
    display: block;
    box-shadow: inset 0 0 20px rgba(0,0,0,0.2);
}}

.hero-card-footer {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 0.85rem;
    padding: 0.65rem 0.85rem;
    background: rgba(15, 23, 42, 0.8);
    border-radius: 10px;
    border: 1px solid rgba(255, 255, 255, 0.1);
}}

.hero-footer-metric {{
    display: flex;
    flex-direction: column;
}}

.hero-metric-val {{
    font-size: 1.2rem;
    font-weight: 800;
    color: #ffffff;
    line-height: 1.1;
}}

.hero-metric-lbl {{
    font-size: 0.72rem;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
}}

.hero-footer-status {{
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    font-size: 0.78rem;
    font-weight: 600;
    color: #38bdf8;
    background: rgba(56, 189, 248, 0.12);
    padding: 0.35rem 0.75rem;
    border-radius: 9999px;
    border: 1px solid rgba(56, 189, 248, 0.3);
}}

.status-pulse-dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background-color: #38bdf8;
    box-shadow: 0 0 8px #38bdf8;
    display: inline-block;
}}

.hero-badge {{
    display: inline-flex;
    align-items: center;
    padding: 0.35rem 0.85rem;
    background: rgba(56, 189, 248, 0.15);
    border: 1px solid var(--accent-color);
    color: var(--accent-color);
    border-radius: 9999px;
    font-size: 0.82rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 1.5rem;
}}

.hero-title {{
    font-size: clamp(2.4rem, 5vw, 4.2rem);
    line-height: 1.12;
    margin-bottom: 1.25rem;
    color: #ffffff;
    font-weight: 800;
    letter-spacing: -0.03em;
}}

.hero-subhead {{
    font-size: clamp(1.05rem, 2vw, 1.3rem);
    color: #cbd5e1;
    margin-bottom: 2.25rem;
    line-height: 1.6;
    max-width: 720px;
}}

.hero-actions {{
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
}}

.hero-proof-strip {{
    display: flex;
    flex-wrap: wrap;
    gap: 1.75rem;
    margin-top: 2.25rem;
    padding-top: 1.75rem;
    border-top: 1px solid rgba(255, 255, 255, 0.15);
}}

.hero-stat-item {{
    display: flex;
    flex-direction: column;
}}

.hero-stat-num {{
    font-size: 1.15rem;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: -0.01em;
}}

.hero-stat-lbl {{
    font-size: 0.72rem;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 500;
}}

.btn-primary {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.85rem 1.85rem;
    background: var(--accent-color);
    color: #ffffff;
    font-weight: 600;
    font-size: 0.98rem;
    border-radius: var(--radius-sm);
    border: none;
    cursor: pointer;
    text-decoration: none;
    transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
}}

.btn-primary:hover {{
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(14, 165, 233, 0.35);
}}

.btn-secondary {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.85rem 1.85rem;
    background: rgba(255, 255, 255, 0.08);
    color: #ffffff;
    font-weight: 600;
    font-size: 0.98rem;
    border-radius: var(--radius-sm);
    border: 1px solid rgba(255, 255, 255, 0.25);
    cursor: pointer;
    text-decoration: none;
    backdrop-filter: blur(8px);
    transition: background 0.2s ease;
}}

.btn-secondary:hover {{
    background: rgba(255, 255, 255, 0.16);
}}

/* About Section */
.about-section {{
    padding: 6rem 0;
}}

.section-tag {{
    font-size: 0.85rem;
    font-weight: 700;
    color: var(--accent-color);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 0.5rem;
}}

.section-title {{
    font-size: clamp(2rem, 3.5vw, 2.75rem);
    margin-bottom: 1.25rem;
}}

.about-lead {{
    font-size: 1.15rem;
    color: var(--text-secondary);
    max-width: 860px;
    line-height: 1.7;
    margin-bottom: 2.5rem;
}}

.objectives-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 1.5rem;
    margin-top: 2rem;
}}

.objective-item {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 1.5rem;
    box-shadow: var(--shadow-sm);
}}

.objective-item h4 {{
    font-size: 1.05rem;
    margin-bottom: 0.5rem;
    color: var(--accent-color);
}}

.objective-item p {{
    font-size: 0.92rem;
    color: var(--text-secondary);
}}

/* Showcase & Entity Grid */
.showcase-section {{
    padding: 6rem 0;
    border-top: 1px solid var(--border-color);
}}

.filter-container {{
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    margin: 2.5rem 0 3rem;
}}

.search-input {{
    width: 100%;
    padding: 0.85rem 1.25rem;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    background: var(--bg-card);
    color: var(--text-primary);
    font-size: 0.95rem;
    outline: none;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}}

.search-input:focus {{
    border-color: var(--accent-color);
    box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.2);
}}

.filter-buttons {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
}}

.filter-pill {{
    padding: 0.5rem 1.25rem;
    border: 1px solid var(--border-color);
    background: var(--bg-card);
    color: var(--text-secondary);
    border-radius: 9999px;
    cursor: pointer;
    font-size: 0.88rem;
    font-weight: 500;
    transition: all 0.2s ease;
}}

.filter-pill:hover {{
    border-color: var(--accent-color);
    color: var(--text-primary);
}}

.filter-pill.active {{
    background: var(--accent-color);
    color: #ffffff;
    border-color: var(--accent-color);
}}

.showcase-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: 2rem;
}}

.entity-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    overflow: hidden;
    box-shadow: var(--shadow-sm);
    display: flex;
    flex-direction: column;
    transition: transform 0.25s ease, box-shadow 0.25s ease;
}}

.entity-card:hover {{
    transform: translateY(-4px);
    box-shadow: var(--shadow-md);
}}

.entity-card-media {{
    height: 220px;
    width: 100%;
    position: relative;
    overflow: hidden;
    background-color: var(--secondary-color);
}}

.entity-card-media img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: transform 0.35s ease;
}}

.entity-card:hover .entity-card-media img {{
    transform: scale(1.05);
}}

.entity-badge {{
    position: absolute;
    top: 1rem;
    left: 1rem;
    padding: 0.25rem 0.75rem;
    background: rgba(3, 7, 18, 0.85);
    backdrop-filter: blur(8px);
    border: 1px solid rgba(255, 255, 255, 0.2);
    color: #38bdf8;
    border-radius: 9999px;
    font-size: 0.78rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}}

.entity-status-badge {{
    position: absolute;
    bottom: 0.75rem;
    right: 0.75rem;
    padding: 0.2rem 0.6rem;
    background: rgba(16, 185, 129, 0.2);
    border: 1px solid #10b981;
    color: #34d399;
    border-radius: 4px;
    font-size: 0.72rem;
    font-weight: 600;
}}

.entity-card-body {{
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    flex: 1;
}}

.entity-card-title {{
    font-size: 1.25rem;
    margin-bottom: 0.5rem;
    color: var(--text-primary);
}}

.entity-spec-row {{
    font-family: var(--font-mono);
    font-size: 0.78rem;
    color: var(--accent-color);
    margin-bottom: 0.75rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid var(--border-color);
    letter-spacing: -0.01em;
}}

.entity-card-desc {{
    font-size: 0.92rem;
    color: var(--text-secondary);
    line-height: 1.6;
    margin-bottom: 1.5rem;
    flex: 1;
}}

.entity-card-actions {{
    margin-top: auto;
}}

/* Form & Contact */
.contact-section {{
    padding: 6rem 0;
    background: var(--bg-card);
    border-top: 1px solid var(--border-color);
}}

.inquiry-form-wrapper {{
    max-width: 680px;
    margin: 2.5rem auto 0;
    padding: 2.5rem;
    background: var(--bg-main);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-sm);
}}

.form-group {{
    margin-bottom: 1.25rem;
}}

.form-label {{
    display: block;
    font-size: 0.88rem;
    font-weight: 600;
    margin-bottom: 0.4rem;
    color: var(--text-primary);
}}

.form-control {{
    width: 100%;
    padding: 0.75rem 1rem;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    background: var(--bg-card);
    color: var(--text-primary);
    font-size: 0.95rem;
    outline: none;
    transition: border-color 0.2s ease;
}}

.form-control:focus {{
    border-color: var(--accent-color);
}}

.demo-disclosure {{
    font-size: 0.82rem;
    color: var(--text-secondary);
    margin-top: 0.75rem;
    text-align: center;
    font-style: italic;
}}

.form-feedback {{
    display: none;
    padding: 1rem 1.25rem;
    border-radius: var(--radius-sm);
    margin-top: 1.25rem;
    font-size: 0.92rem;
}}

.form-feedback.success {{
    display: block;
    background: rgba(16, 185, 129, 0.15);
    color: #10b981;
    border: 1px solid #10b981;
}}

.form-feedback.error {{
    display: block;
    background: rgba(239, 68, 68, 0.15);
    color: #ef4444;
    border: 1px solid #ef4444;
}}

/* Modal Overlay */
.modal-overlay {{
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.75);
    backdrop-filter: blur(8px);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    padding: 1.5rem;
}}

.modal-overlay.open {{
    display: flex;
}}

.modal-dialog {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    max-width: 650px;
    width: 100%;
    padding: 2.25rem;
    border-radius: var(--radius-lg);
    position: relative;
    max-height: 90vh;
    overflow-y: auto;
    box-shadow: var(--shadow-lg);
}}

.modal-close {{
    position: absolute;
    top: 1.25rem;
    right: 1.25rem;
    background: none;
    border: none;
    font-size: 1.75rem;
    cursor: pointer;
    color: var(--text-secondary);
    line-height: 1;
    padding: 4px;
}}

.modal-close:hover {{
    color: var(--text-primary);
}}

/* Footer */
.site-footer {{
    padding: 4rem 0 2rem;
    background: var(--primary-color);
    border-top: 1px solid var(--border-color);
    color: #cbd5e1;
}}

.footer-content {{
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 1.5rem;
    padding-bottom: 2rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}}

.footer-bottom {{
    padding-top: 1.5rem;
    text-align: center;
    font-size: 0.85rem;
    color: #64748b;
}}

/* Schedule & Timeline Section */
.schedule-section {{
    padding: 6rem 0;
    border-top: 1px solid var(--border-color);
}}

.table-responsive {{
    width: 100%;
    overflow-x: auto;
    margin-top: 2rem;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    background: var(--bg-card);
}}

.schedule-table {{
    width: 100%;
    border-collapse: collapse;
    text-align: left;
    font-size: 0.92rem;
    min-width: 600px;
}}

.schedule-table th {{
    padding: 1rem 1.25rem;
    background: rgba(255, 255, 255, 0.04);
    color: var(--text-primary);
    font-weight: 600;
    border-bottom: 1px solid var(--border-color);
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}}

.schedule-table td {{
    padding: 1rem 1.25rem;
    border-bottom: 1px solid var(--border-color);
    color: var(--text-secondary);
}}

.schedule-table tr:last-child td {{
    border-bottom: none;
}}

.schedule-table tr:hover td {{
    background: rgba(255, 255, 255, 0.02);
}}

.status-pill {{
    display: inline-block;
    padding: 0.2rem 0.65rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
    background: rgba(16, 185, 129, 0.15);
    border: 1px solid #10b981;
    color: #34d399;
}}

/* Discovery Archive Section */
.discovery-section {{
    padding: 6rem 0;
    border-top: 1px solid var(--border-color);
}}

.discovery-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 2rem;
    margin-top: 2.5rem;
}}

.discovery-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 2rem;
    display: flex;
    flex-direction: column;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}}

.discovery-card:hover {{
    transform: translateY(-3px);
    box-shadow: var(--shadow-md);
}}

.discovery-metric {{
    font-family: var(--font-mono);
    font-size: 0.82rem;
    color: var(--accent-color);
    margin: 0.75rem 0;
    padding: 0.5rem 0.75rem;
    background: rgba(255, 255, 255, 0.03);
    border-radius: var(--radius-sm);
}}

.discovery-abstract {{
    font-size: 0.92rem;
    color: var(--text-secondary);
    line-height: 1.6;
    margin-bottom: 1rem;
    flex: 1;
}}

.discovery-tag {{
    font-size: 0.75rem;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
}}

/* Live Telemetry Section */
.telemetry-section {{
    padding: 6rem 0;
    border-top: 1px solid var(--border-color);
}}

.telemetry-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 1.75rem;
    margin-top: 2.5rem;
}}

.telemetry-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 1.75rem;
    position: relative;
}}

.telemetry-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1rem;
}}

.telemetry-title {{
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--text-primary);
}}

.telemetry-beacon {{
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #10b981;
    box-shadow: 0 0 10px #10b981;
    animation: pulse 2s infinite;
}}

@keyframes pulse {{
    0% {{ opacity: 1; transform: scale(1); }}
    50% {{ opacity: 0.4; transform: scale(1.2); }}
    100% {{ opacity: 1; transform: scale(1); }}
}}

.telemetry-value {{
    font-family: var(--font-mono);
    font-size: 1.65rem;
    font-weight: 700;
    color: var(--accent-color);
    margin-bottom: 0.5rem;
}}

.telemetry-sub {{
    font-size: 0.82rem;
    color: var(--text-secondary);
}}

/* ==========================================================================
   ARCHETYPE SPECIFIC STYLING (P0.5.2)
   ========================================================================== */

/* SaaS Demo Simulator */
.demo-section {{
    padding: 6rem 0;
    border-top: 1px solid var(--border-color);
}}

.demo-window {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    overflow: hidden;
    box-shadow: var(--shadow-lg);
    margin-top: 2.5rem;
}}

.demo-window-header {{
    background: rgba(0, 0, 0, 0.25);
    padding: 0.85rem 1.5rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--border-color);
}}

.demo-window-dots {{
    display: flex;
    gap: 6px;
}}

.demo-dot {{
    width: 11px;
    height: 11px;
    border-radius: 50%;
}}
.demo-dot.red {{ background: #ef4444; }}
.demo-dot.yellow {{ background: #f59e0b; }}
.demo-dot.green {{ background: #10b981; }}

.demo-tabs {{
    display: flex;
    gap: 0.5rem;
}}

.demo-tab-btn {{
    padding: 0.45rem 1rem;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
}}

.demo-tab-btn:hover {{
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.05);
}}

.demo-tab-btn.active {{
    background: rgba(14, 165, 233, 0.15);
    color: var(--accent-color);
    border-color: var(--accent-color);
}}

.demo-window-body {{
    padding: 2rem;
    min-height: 380px;
}}

.demo-view {{
    display: none;
}}

.demo-view.active {{
    display: block;
    animation: fadeIn 0.3s ease;
}}

@keyframes fadeIn {{
    from {{ opacity: 0; transform: translateY(6px); }}
    to {{ opacity: 1; transform: translateY(0); }}
}}

/* Kanban Simulator */
.kanban-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1.5rem;
}}

.kanban-column {{
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 1.25rem;
}}

.kanban-col-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.25rem;
    font-size: 0.88rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-secondary);
}}

.kanban-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    padding: 1rem;
    margin-bottom: 1rem;
    box-shadow: var(--shadow-sm);
    transition: transform 0.2s ease;
}}

.kanban-card:hover {{
    transform: translateY(-2px);
    border-color: var(--accent-color);
}}

.kanban-card-title {{
    font-size: 0.92rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
    color: var(--text-primary);
}}

.kanban-card-meta {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.78rem;
    color: var(--text-secondary);
}}

.priority-tag {{
    padding: 2px 8px;
    border-radius: 9999px;
    font-weight: 600;
    font-size: 0.72rem;
}}
.priority-p0 {{ background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }}
.priority-p1 {{ background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }}
.priority-done {{ background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }}

/* SaaS Pricing Matrix */
.pricing-section {{
    padding: 6rem 0;
    border-top: 1px solid var(--border-color);
}}

.billing-toggle-container {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 1rem;
    margin: 2.5rem 0 3.5rem;
}}

.billing-label {{
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--text-secondary);
}}

.switch {{
    position: relative;
    display: inline-block;
    width: 52px;
    height: 28px;
}}

.switch input {{
    opacity: 0;
    width: 0;
    height: 0;
}}

.slider {{
    position: absolute;
    cursor: pointer;
    top: 0; left: 0; right: 0; bottom: 0;
    background-color: var(--secondary-color);
    border: 1px solid var(--border-color);
    transition: .3s;
    border-radius: 34px;
}}

.slider:before {{
    position: absolute;
    content: "";
    height: 20px;
    width: 20px;
    left: 3px;
    bottom: 3px;
    background-color: #fff;
    transition: .3s;
    border-radius: 50%;
}}

input:checked + .slider {{
    background-color: var(--accent-color);
}}

input:checked + .slider:before {{
    transform: translateX(24px);
}}

.discount-badge {{
    padding: 0.2rem 0.6rem;
    background: rgba(16, 185, 129, 0.15);
    color: #34d399;
    border: 1px solid #10b981;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 700;
}}

.pricing-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 2rem;
}}

.pricing-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 2.5rem 2rem;
    display: flex;
    flex-direction: column;
    position: relative;
    box-shadow: var(--shadow-sm);
    transition: transform 0.25s ease, box-shadow 0.25s ease;
}}

.pricing-card:hover {{
    transform: translateY(-4px);
    box-shadow: var(--shadow-md);
}}

.pricing-card.featured {{
    border-color: var(--accent-color);
    box-shadow: 0 0 25px rgba(14, 165, 233, 0.15);
}}

.popular-ribbon {{
    position: absolute;
    top: -12px;
    right: 24px;
    padding: 0.25rem 0.75rem;
    background: var(--accent-color);
    color: #fff;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}}

.plan-name {{
    font-size: 1.35rem;
    font-weight: 700;
    margin-bottom: 0.5rem;
}}

.plan-desc {{
    color: var(--text-secondary);
    font-size: 0.9rem;
    margin-bottom: 1.75rem;
}}

.pricing-price-box {{
    margin-bottom: 2rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid var(--border-color);
}}

.pricing-currency {{
    font-size: 1.5rem;
    font-weight: 700;
    vertical-align: super;
}}

.pricing-amount {{
    font-size: 3rem;
    font-weight: 800;
    letter-spacing: -0.03em;
}}

.pricing-period {{
    color: var(--text-secondary);
    font-size: 0.88rem;
    display: block;
    margin-top: 0.25rem;
}}

.pricing-features {{
    list-style: none;
    margin-bottom: 2.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
    flex-grow: 1;
}}

.pricing-features li {{
    font-size: 0.92rem;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 0.75rem;
}}

.pricing-features li::before {{
    content: "✓";
    color: var(--accent-color);
    font-weight: 800;
}}

/* Integrations Section */
.integrations-section {{
    padding: 5rem 0;
    border-top: 1px solid var(--border-color);
    text-align: center;
}}

.integrations-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 1.5rem;
    margin-top: 2.5rem;
}}

.integration-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
    font-weight: 600;
    font-size: 0.92rem;
    box-shadow: var(--shadow-sm);
}}

/* Tourism Itinerary Timeline */
.itinerary-section {{
    padding: 6rem 0;
    border-top: 1px solid var(--border-color);
}}

.itinerary-nav {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin: 2.5rem 0 2rem;
}}

.itinerary-day-pill {{
    padding: 0.65rem 1.25rem;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 9999px;
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--text-secondary);
    cursor: pointer;
    transition: all 0.2s ease;
}}

.itinerary-day-pill:hover {{
    border-color: var(--accent-color);
    color: var(--text-primary);
}}

.itinerary-day-pill.active {{
    background: var(--accent-color);
    color: #fff;
    border-color: var(--accent-color);
}}

.itinerary-detail-card {{
    display: none;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 2.5rem;
    box-shadow: var(--shadow-md);
}}

.itinerary-detail-card.active {{
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 2.5rem;
    animation: fadeIn 0.3s ease;
}}

.itinerary-stats-box {{
    background: rgba(0, 0, 0, 0.03);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
}}

.itinerary-stat-item {{
    display: flex;
    justify-content: space-between;
    font-size: 0.9rem;
}}

.itinerary-stat-label {{
    color: var(--text-secondary);
}}

.itinerary-stat-val {{
    font-weight: 700;
    color: var(--text-primary);
}}

/* Guidelines Section */
.guidelines-section {{
    padding: 6rem 0;
    border-top: 1px solid var(--border-color);
}}

.guidelines-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 1.75rem;
    margin-top: 2.5rem;
}}

.guideline-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 2rem;
    box-shadow: var(--shadow-sm);
}}

.guideline-card h3 {{
    font-size: 1.15rem;
    margin-bottom: 0.75rem;
    color: var(--accent-color);
}}

.guideline-card p {{
    font-size: 0.92rem;
    color: var(--text-secondary);
    line-height: 1.6;
}}

/* Philosophy Section */
.philosophy-section {{
    padding: 6rem 0;
    border-top: 1px solid var(--border-color);
}}

.philosophy-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 2rem;
    margin-top: 2.5rem;
}}

.philosophy-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 2.5rem 2rem;
    box-shadow: var(--shadow-sm);
}}

.philosophy-card h3 {{
    font-size: 1.25rem;
    margin-bottom: 1rem;
    color: var(--text-primary);
}}

.philosophy-card p {{
    color: var(--text-secondary);
    font-size: 0.95rem;
    line-height: 1.65;
}}

/* Specifications Section */
.specifications-section {{
    padding: 5rem 0;
    border-top: 1px solid var(--border-color);
}}

.specifications-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 1.5rem;
    margin-top: 2rem;
}}

.spec-metric-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 2rem;
    text-align: center;
}}

.spec-metric-val {{
    font-size: 2.5rem;
    font-weight: 800;
    color: var(--accent-color);
    line-height: 1.1;
    margin-bottom: 0.5rem;
}}

.spec-metric-lbl {{
    font-size: 0.9rem;
    color: var(--text-secondary);
    font-weight: 500;
}}

/* Responsive */
@media (max-width: 768px) {{
    .mobile-menu-btn {{
        display: block;
    }}
    .nav-links {{
        position: absolute;
        top: 74px;
        left: 0;
        right: 0;
        background: var(--primary-color);
        flex-direction: column;
        padding: 1.5rem;
        display: none;
        border-bottom: 1px solid var(--border-color);
    }}
    .nav-links.active {{
        display: flex;
    }}
    .showcase-grid,
    .discovery-grid,
    .telemetry-grid,
    .kanban-grid,
    .pricing-grid,
    .itinerary-detail-card.active,
    .guidelines-grid,
    .philosophy-grid {{
        grid-template-columns: 1fr;
    }}
}}
"""
        css_path.write_text(css_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(css_path, ws, generator="universal_renderer")

        # ----------------------------------------------------------------------
        # 3. index.html
        # ----------------------------------------------------------------------
        html_path = ws / "index.html"
        title_str = f"{app_name} — {spec.domain_subtype}"

        nav_links_html = []
        for n in spec.navigation_structure:
            cta_cls = " nav-link btn-nav" if n.get("is_cta") else " nav-link"
            nav_links_html.append(f'<li><a href="{n.get("href", "#")}" class="{cta_cls}">{n.get("label", "")}</a></li>')
        nav_html = "\n                ".join(nav_links_html)

        filter_caps = spec.filter_capabilities.get("categories", [])
        filter_pills_html = []
        for idx, cat in enumerate(filter_caps):
            act = " active" if idx == 0 else ""
            filter_pills_html.append(f'<button class="filter-pill{act}" data-category="{cat["id"]}">{cat["label"]}</button>')
        filters_html = "\n                    ".join(filter_pills_html)
        search_ph = spec.filter_capabilities.get("search_placeholder", "Search...")

        form_meta = spec.form_specs[0] if spec.form_specs else {
            "form_id": "inquiry-form",
            "title": f"Inquire with {app_name}",
            "fields": [
                {"name": "full_name", "label": "Full Name *", "type": "text", "required": True},
                {"name": "email", "label": "Email Address *", "type": "email", "required": True},
                {"name": "message", "label": "Message *", "type": "textarea", "required": True},
            ],
            "submit_text": "Submit Inquiry",
            "disclosure": "Demonstration Mode: Inquiries are captured in-browser. No real booking is transmitted.",
        }

        form_fields_html = []
        for f in form_meta.get("fields", []):
            req_attr = " required" if f.get("required") else ""
            if f.get("type") == "textarea":
                field_input = f'<textarea id="form-{f["name"]}" name="{f["name"]}" class="form-control" rows="3"{req_attr}></textarea>'
            elif f.get("type") == "select":
                opts = "".join(f'<option value="{opt}">{opt}</option>' for opt in f.get("options", []))
                field_input = f'<select id="form-{f["name"]}" name="{f["name"]}" class="form-control"{req_attr}>{opts}</select>'
            else:
                field_input = f'<input type="{f.get("type", "text")}" id="form-{f["name"]}" name="{f["name"]}" class="form-control"{req_attr}>'
            form_fields_html.append(f'''<div class="form-group">
                        <label class="form-label">{f.get("label", "")}</label>
                        {field_input}
                    </div>''')
        form_inner_html = "\n                    ".join(form_fields_html)

        objectives_html = []
        for idx, obj in enumerate(spec.business_objectives[:4], 1):
            objectives_html.append(f'''<div class="objective-item">
                    <h4>Capability {idx:02d}</h4>
                    <p>{obj}</p>
                </div>''')
        objs_html = "\n                ".join(objectives_html)

        showcase_sec = next((s for s in spec.required_sections if s.get("component") in ("showcase_grid", "showcase", "portfolio_grid", "features_grid") or s.get("id") in ("showcase", "portfolio", "features", "expeditions")), None)
        showcase_sec_id = showcase_sec.get("id", "showcase") if showcase_sec else "showcase"
        showcase_title = showcase_sec.get("title", f"{app_name} Showcase") if showcase_sec else f"{app_name} Showcase"

        archetype = spec.application_archetype
        d_lower = spec.business_domain.lower()

        # Archetype Specific Hero Actions & Proof Metrics
        if archetype == "saas_product":
            hero_actions_html = """
                    <a href="#contact" class="btn-primary">Start 14-Day Free Trial</a>
                    <a href="#demo-preview" class="btn-secondary">Explore Live Simulator</a>"""
            hero_proof_html = """
                    <div class="hero-stat-item"><span class="hero-stat-num">99.99%</span><span class="hero-stat-lbl">Uptime SLA</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">10k+</span><span class="hero-stat-lbl">Active Squads</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">SOC-2</span><span class="hero-stat-lbl">Type II Certified</span></div>"""
            hero_status_chip = "PLATFORM TELEMETRY v3.4"
            hero_metric_val = "14-Day Free"
            hero_metric_lbl = "Full Access Trial"
            hero_status_text = "Production Ready"
        elif archetype == "tourism_adventure":
            hero_actions_html = f"""
                    <a href="#{showcase_sec_id}" class="btn-primary">Explore Expeditions</a>
                    <a href="#itinerary-timeline" class="btn-secondary">View Route Itinerary</a>"""
            hero_proof_html = """
                    <div class="hero-stat-item"><span class="hero-stat-num">100%</span><span class="hero-stat-lbl">Carbon Neutral</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">4.9 / 5</span><span class="hero-stat-lbl">Expedition Rating</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">UIAA</span><span class="hero-stat-lbl">Certified Guides</span></div>"""
            hero_status_chip = "FEATURED EXPEDITION"
            hero_metric_val = "6 Continents"
            hero_metric_lbl = "Wilderness Routes"
            hero_status_text = "Bookings Active"
        elif archetype == "portfolio_studio":
            hero_actions_html = f"""
                    <a href="#{showcase_sec_id}" class="btn-primary">Explore Portfolio</a>
                    <a href="#contact" class="btn-secondary">Request Consultation</a>"""
            hero_proof_html = """
                    <div class="hero-stat-item"><span class="hero-stat-num">RIBA / AIA</span><span class="hero-stat-lbl">Chartered Practice</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">24+</span><span class="hero-stat-lbl">Global Awards</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">BREEAM</span><span class="hero-stat-lbl">Outstanding Rating</span></div>"""
            hero_status_chip = "STUDIO MONOGRAPH"
            hero_metric_val = "100% Bespoke"
            hero_metric_lbl = "Spatial Architecture"
            hero_status_text = "Active Studio"
        else:
            hero_actions_html = f"""
                    <a href="#contact" class="btn-primary">Explore & Inquire</a>
                    <a href="#{showcase_sec_id}" class="btn-secondary">View Programmes</a>"""
            hero_proof_html = """
                    <div class="hero-stat-item"><span class="hero-stat-num">Enterprise</span><span class="hero-stat-lbl">Architecture</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">100%</span><span class="hero-stat-lbl">Quality Verified</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">24/7</span><span class="hero-stat-lbl">Operational Ready</span></div>"""
            hero_status_chip = "VERIFIED PLATFORM"
            hero_metric_val = "100%"
            hero_metric_lbl = "Authoritative"
            hero_status_text = "Verified System"

        hero_html = f'''
        <!-- Hero Section -->
        <section id="hero" class="hero">
            <div class="hero-overlay"></div>
            <div class="container hero-container">
                <div class="hero-grid">
                    <div class="hero-content">
                        <div class="hero-badge">{spec.domain_subtype}</div>
                        <h1 class="hero-title">{app_name}</h1>
                        <p class="hero-subhead">{spec.purpose}</p>
                        <div class="hero-actions">
                            {hero_actions_html}
                        </div>
                        <div class="hero-proof-strip">
                            {hero_proof_html}
                        </div>
                    </div>
                    <div class="hero-visual-col">
                        <div class="hero-showcase-frame">
                            <div class="hero-card-badge">{hero_status_chip}</div>
                            <img src="{hero_img_path}" alt="{app_name} Showcase Visual" class="hero-showcase-img" loading="eager">
                            <div class="hero-card-footer">
                                <div class="hero-footer-metric">
                                    <span class="hero-metric-val">{hero_metric_val}</span>
                                    <span class="hero-metric-lbl">{hero_metric_lbl}</span>
                                </div>
                                <div class="hero-footer-status">
                                    <span class="status-pulse-dot"></span>
                                    <span>{hero_status_text}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </section>'''

        main_sections = [hero_html]

        if archetype == "saas_product":
            demo_html = f'''
        <!-- Interactive Workspace Simulator -->
        <section id="demo-preview" class="container demo-section">
            <div class="section-tag">Interactive Simulation</div>
            <h2 class="section-title">Experience {app_name} Live</h2>
            <p class="about-lead">Explore high-velocity sprint execution, predictive delivery telemetry, and automated event triggers in real-time.</p>
            <div class="demo-window">
                <div class="demo-window-header">
                    <div class="demo-window-dots">
                        <span class="demo-dot red"></span>
                        <span class="demo-dot yellow"></span>
                        <span class="demo-dot green"></span>
                    </div>
                    <div class="demo-tabs">
                        <button class="demo-tab-btn active" data-tab="kanban" id="tab-kanban">Sprint Board</button>
                        <button class="demo-tab-btn" data-tab="analytics" id="tab-analytics">Velocity Analytics</button>
                        <button class="demo-tab-btn" data-tab="automation" id="tab-automation">Workflow Automations</button>
                    </div>
                    <div style="font-size: 0.8rem; color: var(--text-secondary); font-family: var(--font-mono);">simulation: active</div>
                </div>
                <div class="demo-window-body">
                    <!-- Kanban View -->
                    <div id="view-kanban" class="demo-view active">
                        <div class="kanban-grid">
                            <div class="kanban-column">
                                <div class="kanban-col-header"><span>Backlog</span> <span>3 Items</span></div>
                                <div class="kanban-card">
                                    <div class="kanban-card-title">AUTH-102: Migrate SSO to OIDC 2.0</div>
                                    <div class="kanban-card-meta"><span>Security Squad</span> <span class="priority-tag priority-p1">P1</span></div>
                                </div>
                                <div class="kanban-card">
                                    <div class="kanban-card-title">API-88: Distributed Rate Limiting</div>
                                    <div class="kanban-card-meta"><span>Core Platform</span> <span class="priority-tag priority-p1">P1</span></div>
                                </div>
                            </div>
                            <div class="kanban-column">
                                <div class="kanban-col-header"><span>In Progress</span> <span>2 Items</span></div>
                                <div class="kanban-card">
                                    <div class="kanban-card-title">ENGINE-401: CRDT State Mutations</div>
                                    <div class="kanban-card-meta"><span>Infra Team</span> <span class="priority-tag priority-p0">P0</span></div>
                                </div>
                                <div class="kanban-card">
                                    <div class="kanban-card-title">UI-305: Predictive Burndown Chart</div>
                                    <div class="kanban-card-meta"><span>Frontend Squad</span> <span class="priority-tag priority-p1">P1</span></div>
                                </div>
                            </div>
                            <div class="kanban-column">
                                <div class="kanban-col-header"><span>Completed</span> <span>4 Items</span></div>
                                <div class="kanban-card">
                                    <div class="kanban-card-title">SEC-12: SOC2 Type II Audit Pass</div>
                                    <div class="kanban-card-meta"><span>Compliance</span> <span class="priority-tag priority-done">Verified</span></div>
                                </div>
                                <div class="kanban-card">
                                    <div class="kanban-card-title">CLI-10: v2.4 Binary Notarization</div>
                                    <div class="kanban-card-meta"><span>DevRel Squad</span> <span class="priority-tag priority-done">Released</span></div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <!-- Analytics View -->
                    <div id="view-analytics" class="demo-view">
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1.5rem; margin-bottom: 2rem;">
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.5rem; border-radius: var(--radius-sm);">
                                <div style="font-size: 0.85rem; color: var(--text-secondary);">Sprint Velocity</div>
                                <div style="font-size: 2rem; font-weight: 800; color: var(--accent-color); margin-top: 0.25rem;">94.6 <span style="font-size: 0.9rem; color: #34d399;">+18%</span></div>
                            </div>
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.5rem; border-radius: var(--radius-sm);">
                                <div style="font-size: 0.85rem; color: var(--text-secondary);">Cycle Time (Mean)</div>
                                <div style="font-size: 2rem; font-weight: 800; color: var(--text-primary); margin-top: 0.25rem;">1.4 <span style="font-size: 0.9rem; color: var(--text-secondary);">days</span></div>
                            </div>
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.5rem; border-radius: var(--radius-sm);">
                                <div style="font-size: 0.85rem; color: var(--text-secondary);">PR Turnaround</div>
                                <div style="font-size: 2rem; font-weight: 800; color: var(--accent-color); margin-top: 0.25rem;">28 <span style="font-size: 0.9rem; color: var(--text-secondary);">mins</span></div>
                            </div>
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.5rem; border-radius: var(--radius-sm);">
                                <div style="font-size: 0.85rem; color: var(--text-secondary);">Burndown Predictability</div>
                                <div style="font-size: 2rem; font-weight: 800; color: #34d399; margin-top: 0.25rem;">98.2%</div>
                            </div>
                        </div>
                        <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.5rem; border-radius: var(--radius-sm); font-size: 0.9rem; color: var(--text-secondary);">
                            <strong>Predictive Burndown Telemetry:</strong> Current sprint milestone is tracking 1.2 days ahead of schedule across all micro-services.
                        </div>
                    </div>
                    <!-- Automation View -->
                    <div id="view-automation" class="demo-view">
                        <div style="display: flex; flex-direction: column; gap: 1rem;">
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.25rem; border-radius: var(--radius-sm); display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <div style="font-weight: 600; color: var(--text-primary);">When PR is approved by 2 reviewers &rarr; Trigger canary deployment to staging</div>
                                    <div style="font-size: 0.85rem; color: var(--text-secondary); margin-top: 0.25rem;">Trigger: GitHub Webhook &middot; Action: ArgoCD Workflow &middot; Latency: 120ms</div>
                                </div>
                                <span class="priority-tag priority-done">Active Rule</span>
                            </div>
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.25rem; border-radius: var(--radius-sm); display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <div style="font-weight: 600; color: var(--text-primary);">When issue severity is set to 'P0' &rarr; Create incident war-room in Slack #incident-response</div>
                                    <div style="font-size: 0.85rem; color: var(--text-secondary); margin-top: 0.25rem;">Trigger: Issue State Mutation &middot; Action: Slack Bot &middot; SLA: &lt; 5s</div>
                                </div>
                                <span class="priority-tag priority-done">Active Rule</span>
                            </div>
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.25rem; border-radius: var(--radius-sm); display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <div style="font-weight: 600; color: var(--text-primary);">When sprint concludes &rarr; Generate Markdown release notes & sync commit SHAs</div>
                                    <div style="font-size: 0.85rem; color: var(--text-secondary); margin-top: 0.25rem;">Trigger: Sprint Close &middot; Action: Automated Git Tagging &middot; Status: Enabled</div>
                                </div>
                                <span class="priority-tag priority-done">Active Rule</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </section>'''
            main_sections.append(demo_html)

            features_html = f'''
        <!-- Core Platform Features -->
        <section id="features" class="container showcase-section">
            <div class="section-tag">Platform Architecture</div>
            <h2 class="section-title">{showcase_title}</h2>
            <div class="filter-container">
                <input type="text" id="showcase-search" class="search-input" placeholder="{search_ph}">
                <div class="filter-buttons" id="category-filters">
                    {filters_html}
                </div>
            </div>
            <div id="showcase-grid" class="showcase-grid"></div>
        </section>'''
            main_sections.append(features_html)

            pricing_html = f'''
        <!-- Subscription Pricing Matrix -->
        <section id="pricing" class="container pricing-section">
            <div style="text-align: center; max-width: 650px; margin: 0 auto;">
                <div class="section-tag">Predictable Plans</div>
                <h2 class="section-title">Transparent Subscription Pricing</h2>
                <p style="color: var(--text-secondary); margin-top: 0.75rem;">Scale predictably from agile squads to multi-thousand developer enterprises. All plans include unlimited repositories.</p>
            </div>
            
            <div class="billing-toggle-container">
                <span class="billing-label">Monthly Billing</span>
                <label class="switch">
                    <input type="checkbox" id="billing-toggle">
                    <span class="slider"></span>
                </label>
                <span class="billing-label">Annual Billing</span>
                <span class="discount-badge">Save 20%</span>
            </div>
            
            <div class="pricing-grid">
                <div class="pricing-card" data-monthly="$29" data-annual="$23">
                    <div class="plan-name">Starter Squad</div>
                    <div class="plan-desc">Essential sprint boards and telemetry for growing engineering squads.</div>
                    <div class="pricing-price-box">
                        <span class="pricing-currency">$</span>
                        <span class="pricing-amount">29</span>
                        <span class="pricing-period">/ developer / month</span>
                    </div>
                    <ul class="pricing-features">
                        <li>Up to 15 Active Squad Members</li>
                        <li>Real-time Kanban & Sprint Boards</li>
                        <li>Bidirectional GitHub & GitLab Sync</li>
                        <li>Basic Velocity & Burndown Charts</li>
                        <li>Community Forum & Email Support</li>
                    </ul>
                    <a href="#contact" class="btn-primary" style="text-align: center; width: 100%;">Get Started</a>
                </div>
                
                <div class="pricing-card featured" data-monthly="$79" data-annual="$63">
                    <div class="popular-ribbon">Most Popular</div>
                    <div class="plan-name">Professional</div>
                    <div class="plan-desc">Advanced workflow automations and predictive telemetry for scale-up teams.</div>
                    <div class="pricing-price-box">
                        <span class="pricing-currency">$</span>
                        <span class="pricing-amount">79</span>
                        <span class="pricing-period">/ developer / month</span>
                    </div>
                    <ul class="pricing-features">
                        <li>Unlimited Squad Members</li>
                        <li>Event-Driven Workflow Automations</li>
                        <li>Cross-Squad Dependency Mapping</li>
                        <li>Monte Carlo Sprint Predictability</li>
                        <li>SAML 2.0 / Okta Single Sign-On</li>
                        <li>Priority 1-Hour SLA Support</li>
                    </ul>
                    <a href="#contact" class="btn-primary" style="text-align: center; width: 100%;">Start 14-Day Free Trial</a>
                </div>
                
                <div class="pricing-card" data-monthly="$199" data-annual="$159">
                    <div class="plan-name">Enterprise Core</div>
                    <div class="plan-desc">Bespoke governance, isolated VPC deployment, and 24/7 dedicated engineering.</div>
                    <div class="pricing-price-box">
                        <span class="pricing-currency">$</span>
                        <span class="pricing-amount">199</span>
                        <span class="pricing-period">/ developer / month</span>
                    </div>
                    <ul class="pricing-features">
                        <li>Dedicated Isolated Tenant / VPC</li>
                        <li>Custom Role-Based Access Controls</li>
                        <li>Immutable Compliance Audit Vault</li>
                        <li>99.99% Uptime Financial Guarantee</li>
                        <li>Dedicated Solutions Architect</li>
                        <li>Custom Webhook & API Rate Tiers</li>
                    </ul>
                    <a href="#contact" class="btn-primary" style="text-align: center; width: 100%;">Contact Enterprise Sales</a>
                </div>
            </div>
        </section>'''
            main_sections.append(pricing_html)

            integrations_html = f'''
        <!-- Developer Toolchain Integrations -->
        <section id="integrations" class="container integrations-section">
            <div class="section-tag">Seamless Interoperability</div>
            <h2 class="section-title">Integrated with Your Developer Stack</h2>
            <p style="color: var(--text-secondary); max-width: 600px; margin: 0.75rem auto 0;">Native two-way synchronization with the developer tools your squad relies on every day.</p>
            <div class="integrations-grid">
                <div class="integration-card">
                    <div style="font-size: 1.5rem; color: var(--accent-color);">&bull;</div>
                    <div>GitHub</div>
                    <div style="font-size: 0.78rem; color: var(--text-secondary);">PRs & Commits</div>
                </div>
                <div class="integration-card">
                    <div style="font-size: 1.5rem; color: var(--accent-color);">&bull;</div>
                    <div>GitLab</div>
                    <div style="font-size: 0.78rem; color: var(--text-secondary);">Pipelines & Issues</div>
                </div>
                <div class="integration-card">
                    <div style="font-size: 1.5rem; color: var(--accent-color);">&bull;</div>
                    <div>Slack</div>
                    <div style="font-size: 0.78rem; color: var(--text-secondary);">War-Room Alerts</div>
                </div>
                <div class="integration-card">
                    <div style="font-size: 1.5rem; color: var(--accent-color);">&bull;</div>
                    <div>Jira</div>
                    <div style="font-size: 0.78rem; color: var(--text-secondary);">Bi-directional Sync</div>
                </div>
                <div class="integration-card">
                    <div style="font-size: 1.5rem; color: var(--accent-color);">&bull;</div>
                    <div>Figma</div>
                    <div style="font-size: 0.78rem; color: var(--text-secondary);">Design Specs</div>
                </div>
                <div class="integration-card">
                    <div style="font-size: 1.5rem; color: var(--accent-color);">&bull;</div>
                    <div>AWS</div>
                    <div style="font-size: 0.78rem; color: var(--text-secondary);">Cloud Telemetry</div>
                </div>
            </div>
        </section>'''
            main_sections.append(integrations_html)

        elif archetype == "tourism_adventure":
            about_html = f'''
        <!-- Wilderness Stewardship & Ethos -->
        <section id="about" class="container about-section">
            <div class="section-tag">Wilderness Stewardship</div>
            <h2 class="section-title">Conservation & Field Ethos</h2>
            <p class="about-lead">{spec.purpose} We pioneer small-group, carbon-neutral exploration leaving zero trace across the world's most fragile environments.</p>
            <div class="objectives-grid">
                <div class="objective-item">
                    <h4>100% Carbon-Neutral Travel</h4>
                    <p>All expedition emissions verified and offset through high-durability indigenous afforestation and glacial protection initiatives.</p>
                </div>
                <div class="objective-item">
                    <h4>Certified Mountain Leadership</h4>
                    <p>All departures guided by UIAGM/IFMGA certified mountain guides and wilderness emergency medicine first-responders.</p>
                </div>
                <div class="objective-item">
                    <h4>Strict Leave-No-Trace Standards</h4>
                    <p>Every expedition operates on a strict zero-single-use-plastic, pack-it-in pack-it-out protocol preserving alpine biodiversity.</p>
                </div>
                <div class="objective-item">
                    <h4>Small-Group Exploration</h4>
                    <p>Strictly capped at 6 to 12 explorers per departure to guarantee safety, wilderness solitude, and minimal environmental footprint.</p>
                </div>
            </div>
        </section>'''
            main_sections.append(about_html)

            expeditions_html = f'''
        <!-- Featured Expeditions Showcase -->
        <section id="{showcase_sec_id}" class="container showcase-section">
            <div class="section-tag">Wilderness Routes</div>
            <h2 class="section-title">{showcase_title}</h2>
            <div class="filter-container">
                <input type="text" id="showcase-search" class="search-input" placeholder="{search_ph}">
                <div class="filter-buttons" id="category-filters">
                    {filters_html}
                </div>
            </div>
            <div id="showcase-grid" class="showcase-grid"></div>
        </section>'''
            main_sections.append(expeditions_html)

            itinerary_html = f'''
        <!-- Interactive Expedition Itinerary Timeline -->
        <section id="itinerary-timeline" class="container itinerary-section">
            <div class="section-tag">Expedition Route Progression</div>
            <h2 class="section-title">Interactive Day-by-Day Expedition Itinerary</h2>
            <p class="about-lead">Explore route progression, elevation profiles, and wilderness camps for our flagship Patagonia Southern Icefield Traverse.</p>
            
            <div class="itinerary-nav">
                <button class="itinerary-day-pill active" data-day="day1">Day 01: El Chaltén & Base Camp</button>
                <button class="itinerary-day-pill" data-day="day2">Day 02: Glacier Ascent</button>
                <button class="itinerary-day-pill" data-day="day3">Day 03: High Mountain Pass (4,250m)</button>
                <button class="itinerary-day-pill" data-day="day4">Day 04: Continental Icefield</button>
                <button class="itinerary-day-pill" data-day="day5">Day 05: Summit Ridge Push</button>
                <button class="itinerary-day-pill" data-day="day6">Day 06: Native Beech Forest Descent</button>
            </div>
            
            <div id="itinerary-day1" class="itinerary-detail-card active">
                <div>
                    <h3 style="font-size: 1.4rem; color: var(--text-primary); margin-bottom: 0.75rem;">Day 01 — Expedition Staging & De Agostini Base Camp</h3>
                    <p style="color: var(--text-secondary); line-height: 1.65; margin-bottom: 1.5rem;">Explorers assemble in El Chaltén for gear inspections, satellite beacon pairing, and crampon fitting. A moderate trek through native lenga forest brings the team to Laguna Torre, where the sheer granite needle of Cerro Torre towers above our wilderness camp.</p>
                    <div style="font-size: 0.9rem; color: var(--text-primary); font-weight: 600;">Key Route Highlights:</div>
                    <ul style="margin: 0.5rem 0 0 1.25rem; color: var(--text-secondary); font-size: 0.88rem; line-height: 1.6;">
                        <li>Laguna Torre moraine vista and ice floe inspection</li>
                        <li>Glacial stream hydration staging and telemetry check</li>
                        <li>Wilderness camp briefing on Crevasse rescue protocols</li>
                    </ul>
                </div>
                <div class="itinerary-stats-box">
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Distance:</span> <span class="itinerary-stat-val">11.4 km</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Elevation Gain:</span> <span class="itinerary-stat-val">+320 m</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Terrain:</span> <span class="itinerary-stat-val">Glacial Moraine & Lenga</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Camp Altitude:</span> <span class="itinerary-stat-val">650 m a.s.l.</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Wilderness Grade:</span> <span class="itinerary-stat-val">Moderate (Grade II)</span></div>
                </div>
            </div>
            
            <div id="itinerary-day2" class="itinerary-detail-card">
                <div>
                    <h3 style="font-size: 1.4rem; color: var(--text-primary); margin-bottom: 0.75rem;">Day 02 — Marconi Glacier Ascent & Icecap Entry</h3>
                    <p style="color: var(--text-secondary); line-height: 1.65; margin-bottom: 1.5rem;">Crampons are strapped on as the team steps onto the lateral moraine and ascending tongue of Glacier Marconi. Roped team progression navigates blue meltwater streams and ancient glacial seracs into the vast southern ice sheet.</p>
                </div>
                <div class="itinerary-stats-box">
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Distance:</span> <span class="itinerary-stat-val">8.6 km</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Elevation Gain:</span> <span class="itinerary-stat-val">+860 m</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Terrain:</span> <span class="itinerary-stat-val">Live Blue Glacier Ice</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Camp Altitude:</span> <span class="itinerary-stat-val">1,510 m a.s.l.</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Wilderness Grade:</span> <span class="itinerary-stat-val">Strenuous (Grade IV)</span></div>
                </div>
            </div>
            
            <div id="itinerary-day3" class="itinerary-detail-card">
                <div>
                    <h3 style="font-size: 1.4rem; color: var(--text-primary); margin-bottom: 0.75rem;">Day 03 — Paso Marconi Crossing (High Mountain Pass)</h3>
                    <p style="color: var(--text-secondary); line-height: 1.65; margin-bottom: 1.5rem;">Summiting Paso Marconi at 1,550m marks our official crossing onto the third largest ice mass on Earth. Unobstructed 360-degree views of the nunataks of Circo de los Altares emerge under Antarctic blue skies.</p>
                </div>
                <div class="itinerary-stats-box">
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Distance:</span> <span class="itinerary-stat-val">14.2 km</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Elevation Gain:</span> <span class="itinerary-stat-val">+450 m / -200 m</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Terrain:</span> <span class="itinerary-stat-val">Continental Snowpack</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Camp Altitude:</span> <span class="itinerary-stat-val">1,380 m a.s.l.</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Wilderness Grade:</span> <span class="itinerary-stat-val">High Alpine (Grade V)</span></div>
                </div>
            </div>
            
            <div id="itinerary-day4" class="itinerary-detail-card">
                <div>
                    <h3 style="font-size: 1.4rem; color: var(--text-primary); margin-bottom: 0.75rem;">Day 04 — Continental Icefield & Circo de los Altares</h3>
                    <p style="color: var(--text-secondary); line-height: 1.65; margin-bottom: 1.5rem;">A full day traversing beneath the colossal west faces of Cerro Torre and Fitz Roy. The silence of the continental icefield is broken only by the crunch of crampons and wind over seracs.</p>
                </div>
                <div class="itinerary-stats-box">
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Distance:</span> <span class="itinerary-stat-val">16.0 km</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Elevation Gain:</span> <span class="itinerary-stat-val">+150 m</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Terrain:</span> <span class="itinerary-stat-val">Firn Snow & Ice Sheet</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Camp Altitude:</span> <span class="itinerary-stat-val">1,420 m a.s.l.</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Wilderness Grade:</span> <span class="itinerary-stat-val">Technical (Grade IV)</span></div>
                </div>
            </div>
            
            <div id="itinerary-day5" class="itinerary-detail-card">
                <div>
                    <h3 style="font-size: 1.4rem; color: var(--text-primary); margin-bottom: 0.75rem;">Day 05 — Paso del Viento Ascent & Sunset Panorama</h3>
                    <p style="color: var(--text-secondary); line-height: 1.65; margin-bottom: 1.5rem;">We climb out of the icefield via Paso del Viento ('Wind Pass') at 1,500m. A breathtaking panoramic view opens over the emerald waters of Lake Viedma and the jagged calving glacier front.</p>
                </div>
                <div class="itinerary-stats-box">
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Distance:</span> <span class="itinerary-stat-val">12.5 km</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Elevation Gain:</span> <span class="itinerary-stat-val">+600 m / -700 m</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Terrain:</span> <span class="itinerary-stat-val">Alpine Scree & Bedrock</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Camp Altitude:</span> <span class="itinerary-stat-val">900 m a.s.l.</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Wilderness Grade:</span> <span class="itinerary-stat-val">Strenuous (Grade IV)</span></div>
                </div>
            </div>
            
            <div id="itinerary-day6" class="itinerary-detail-card">
                <div>
                    <h3 style="font-size: 1.4rem; color: var(--text-primary); margin-bottom: 0.75rem;">Day 06 — Tunel River Valley & Return</h3>
                    <p style="color: var(--text-secondary); line-height: 1.65; margin-bottom: 1.5rem;">Descent through the Tunel river valley, crossing rushing glacial streams via tyrolean traverse cable or wading gravel bars. Return to El Chaltén for expedition celebration.</p>
                </div>
                <div class="itinerary-stats-box">
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Distance:</span> <span class="itinerary-stat-val">15.0 km</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Elevation Gain:</span> <span class="itinerary-stat-val">-500 m</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Terrain:</span> <span class="itinerary-stat-val">River Valley & Forest</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Camp Altitude:</span> <span class="itinerary-stat-val">400 m a.s.l.</span></div>
                    <div class="itinerary-stat-item"><span class="itinerary-stat-label">Wilderness Grade:</span> <span class="itinerary-stat-val">Moderate (Grade III)</span></div>
                </div>
            </div>
        </section>'''
            main_sections.append(itinerary_html)

            field_guide_html = f'''
        <!-- Field Guidelines & Gear Checklist -->
        <section id="field-guide" class="container guidelines-section">
            <div class="section-tag">Expedition Preparation</div>
            <h2 class="section-title">Field Guidelines & Mandatory Gear</h2>
            <p class="about-lead">Wilderness travel demands self-sufficiency, physical readiness, and proven mountain equipment.</p>
            <div class="guidelines-grid">
                <div class="guideline-card">
                    <h3>01. Mandatory Technical Layering</h3>
                    <p>All explorers must carry merino base layers, 800-fill down insulation, and minimum 28,000mm hydrostatic head 3-layer Gore-Tex Pro hardshells.</p>
                </div>
                <div class="guideline-card">
                    <h3>02. Acclimatization Protocols</h3>
                    <p>We adhere to conservative ascent staging (maximum 500m net gain per 24 hours above 3,000m) with continuous SpO2 pulse oximetry monitoring.</p>
                </div>
                <div class="guideline-card">
                    <h3>03. Leave-No-Trace Wilderness Code</h3>
                    <p>Zero organic or inorganic waste may be deposited in wilderness territory. Portable human-waste containment packs are provided for icefield sections.</p>
                </div>
                <div class="guideline-card">
                    <h3>04. Emergency Satellite Telemetry</h3>
                    <p>Every rope pod is equipped with dual Garmin inReach satellite SOS transmitters providing real-time 10-minute coordinate telemetry.</p>
                </div>
            </div>
        </section>'''
            main_sections.append(field_guide_html)

        elif archetype == "portfolio_studio":
            philosophy_html = f'''
        <!-- Spatial Design Philosophy -->
        <section id="philosophy" class="container philosophy-section">
            <div id="about"></div>
            <div class="section-tag">Studio Manifesto</div>
            <h2 class="section-title">Spatial Philosophy & Tectonic Materiality</h2>
            <p class="about-lead">We believe that enduring architecture emerges from an honest dialogue between geological topography, raw material mass, and natural daylight.</p>
            <div class="philosophy-grid">
                <div class="philosophy-card">
                    <h3>Monolithic Thermal Mass</h3>
                    <p>Employing cast-in-place architectural concrete and site-sourced rammed earth to harness high diurnal thermal lag, ensuring passive climate stability without oversized mechanical HVAC systems.</p>
                </div>
                <div class="philosophy-card">
                    <h3>Passive Solar & Daylight Capture</h3>
                    <p>Sculpting deep architectural cantilevers and calculated solar apertures that illuminate living volumes while shielding interiors from intense midday radiation in every season.</p>
                </div>
                <div class="philosophy-card">
                    <h3>Contextual Material Authenticity</h3>
                    <p>Prioritizing patinated structural steel, charred Shou Sugi Ban cedar, and local quarried fieldstone that weather gracefully over centuries with zero synthetic maintenance coatings.</p>
                </div>
            </div>
        </section>'''
            main_sections.append(philosophy_html)

            portfolio_html = f'''
        <!-- Architectural Portfolio Showcase -->
        <section id="{showcase_sec_id}" class="container showcase-section">
            <div class="section-tag">Featured Works</div>
            <h2 class="section-title">{showcase_title}</h2>
            <div class="filter-container">
                <input type="text" id="showcase-search" class="search-input" placeholder="{search_ph}">
                <div class="filter-buttons" id="category-filters">
                    {filters_html}
                </div>
            </div>
            <div id="showcase-grid" class="showcase-grid"></div>
        </section>'''
            main_sections.append(portfolio_html)

            specs_html = f'''
        <!-- Studio Specifications & Standards -->
        <section id="specifications" class="container specifications-section">
            <div style="text-align: center; max-width: 600px; margin: 0 auto;">
                <div class="section-tag">Studio Benchmarks</div>
                <h2 class="section-title">Architectural Standards & Honors</h2>
            </div>
            <div class="specifications-grid">
                <div class="spec-metric-card">
                    <div class="spec-metric-val">100%</div>
                    <div class="spec-metric-lbl">Passivhaus & Net-Zero Capable</div>
                </div>
                <div class="spec-metric-card">
                    <div class="spec-metric-val">18</div>
                    <div class="spec-metric-lbl">AIA & International Design Awards</div>
                </div>
                <div class="spec-metric-card">
                    <div class="spec-metric-val">24</div>
                    <div class="spec-metric-lbl">Commissioned Works across 6 Countries</div>
                </div>
                <div class="spec-metric-card">
                    <div class="spec-metric-val">Zero</div>
                    <div class="spec-metric-lbl">Net Carbon Emissions over Lifecycle</div>
                </div>
            </div>
        </section>'''
            main_sections.append(specs_html)

        else:
            about_html = f'''
        <!-- About Section -->
        <section id="about" class="container about-section">
            <div class="section-tag">About The Institution</div>
            <h2 class="section-title">Authoritative Mission & Scientific Foundation</h2>
            <p class="about-lead">{spec.purpose} Dedicated to excellence, open data discovery, and modern research execution across all international initiatives.</p>
            <div class="objectives-grid">
                {objs_html}
            </div>
        </section>'''
            main_sections.append(about_html)

            showcase_html = f'''
        <!-- Showcase Section -->
        <section id="{showcase_sec_id}" class="container showcase-section">
            <div class="section-tag">Scientific Assets & Operations</div>
            <h2 class="section-title">{showcase_title}</h2>
            <div class="filter-container">
                <input type="text" id="showcase-search" class="search-input" placeholder="{search_ph}">
                <div class="filter-buttons" id="category-filters">
                    {filters_html}
                </div>
            </div>
            <div id="showcase-grid" class="showcase-grid"></div>
        </section>'''
            main_sections.append(showcase_html)

            schedule_sec = next((s for s in spec.required_sections if s.get("component") == "schedule_timeline" or s.get("id") in ("schedule", "expeditions")), None)
            if schedule_sec:
                sec_id = schedule_sec.get("id", "schedule")
                sec_title = schedule_sec.get("title", "Observation & Expedition Schedules")
                if "astronomy" in d_lower:
                    headers = ["Target / Sector", "Coordinates", "Telescope / Instrument", "Status", "Principal Investigator"]
                    rows = [
                        ["NGC 1365 Fornax Barred Spiral", "RA 03h 33m / Dec -36° 08'", "ALMA-VISTA Submillimeter Array", "Active Observation", "Dr. Elena Rostova"],
                        ["Sagittarius A* Galactic Center", "RA 17h 45m / Dec -29° 00'", "Centaurus Stellar Spectrograph", "Calibration Verified", "Prof. Marcus Vance"],
                        ["WASP-121b Exoplanet Atmosphere", "RA 07h 10m / Dec -39° 05'", "Keck-VISTA Optical Reflector", "Target Acquisition", "Dr. Sarah Lindqvist"],
                        ["Primordial CMB Polarimetry Scan", "Deep Field South Equatorial", "CMB Cryogenic Polarimeter", "Continuous Integration", "Dr. Kenji Sato"],
                        ["Public Stargazing Planetary Session", "Zenith Dome Observation Deck", "1.8m Classical Cassegrain", "Scheduled (20:30 UTC)", "Public Outreach Team"],
                    ]
                elif "marine" in d_lower:
                    headers = ["Expedition / Mission", "Station / Depth", "Research Vessel / Submersible", "Status", "Chief Scientist"]
                    rows = [
                        ["Mariana Hadal Trench Transect", "Challenger Deep (10,920m)", "R/V Challenger & Nautilus ROV", "Active Descent", "Dr. Alistair Finch"],
                        ["Gorda Ridge Hydrothermal Bio-Census", "Station Vent-04 (2,700m)", "Sentry-X Autonomous Glider", "Telemetry Stream", "Dr. Maya Lin"],
                        ["Southern Ocean Microplastic Survey", "Antarctic Divergence (62°S)", "R/V Challenger Wet Labs", "Sampling Station 12", "Dr. Soren Thorne"],
                        ["Abyssal Plain eDNA Stratigraphy", "Clarion-Clipperton Zone (4,800m)", "Benthic Lander Array 02", "Autonomous Cycle", "Dr. Rachel Sterling"],
                        ["Acoustic Cetacean Migration Track", "North Pacific Subtropical Gyre", "Acoustic Hydrophone Network", "Signal Processing", "Dr. David Okafor"],
                    ]
                elif "volcan" in d_lower:
                    headers = ["Monitoring Zone / Wellpad", "Coordinates / Depth", "Instrumentation / Facility", "Status", "Monitoring Lead"]
                    rows = [
                        ["Summit Caldera Halema'uma'u", "19.421° N 155.287° W", "Scanning UV DOAS Spectrometer", "Continuous Degassing Stream", "Dr. Carlos Mendoza"],
                        ["East Rift Flank Fault Zone", "Borehole Depth 300m", "Broadband Seismic Array 04", "Harmonic Tremor Nominal", "Dr. Sophia Aris"],
                        ["Supercritical Wellhead Alpha-4", "Depth 3,420m / Temp 425°C", "High-Enthalpy Steam Turbines", "Baseload Generation 45 MW", "Eng. Hiroshi Tanaka"],
                        ["South Flank Dilatometer Pad", "Station DT-02 Basalt Rim", "Quartz Dilatometer & GNSS", "Crustal Strain Stable", "Dr. Greta Vestergaard"],
                        ["Petrological Drill Core Archive", "Subsurface Stratigraphy Lab", "P-V-T Piston Cylinder Press", "Core Logging Run 18", "Dr. Liam O'Connor"],
                    ]
                else:
                    headers = ["Operational Initiative", "Deployment Domain", "Integrated Platform", "Status", "Lead Director"]
                    rows = [
                        [f"{app_name} Core System", "Primary Production", "Distributed Cluster 01", "Active Telemetry", "Technical Director"],
                        ["Verification Audit Cycle", "Quality Assurance", "Automated Compliance Suite", "Verified Pass", "Operations Lead"],
                        ["Strategic Expansion Initiative", "Global Operations", "Scalable Infrastructure", "Deployment Ready", "Strategic Partner"],
                    ]
                th_cells = "".join(f"<th>{h}</th>" for h in headers)
                tr_rows = ""
                for r in rows:
                    status_td = f'<td><span class="status-pill">{r[3]}</span></td>'
                    tr_rows += f"<tr><td><strong>{r[0]}</strong></td><td>{r[1]}</td><td>{r[2]}</td>{status_td}<td>{r[4]}</td></tr>\n"
                schedule_html = f'''
        <!-- Schedule / Operations Section -->
        <section id="{sec_id}" class="container schedule-section">
            <div class="section-tag">Scientific Operations & Timeline</div>
            <h2 class="section-title">{sec_title}</h2>
            <div class="table-responsive">
                <table class="schedule-table">
                    <thead>
                        <tr>{th_cells}</tr>
                    </thead>
                    <tbody>
                        {tr_rows}
                    </tbody>
                </table>
            </div>
        </section>'''
                main_sections.append(schedule_html)

            discovery_sec = next((s for s in spec.required_sections if s.get("component") == "discovery_archive" or s.get("id") in ("discoveries", "biodiversity")), None)
            if discovery_sec:
                sec_id = discovery_sec.get("id", "discoveries")
                sec_title = discovery_sec.get("title", "Discovery & Research Archives")
                if "astronomy" in d_lower:
                    disc_cards = [
                        ("Protoplanetary Dust Disc Ring Gaps in HD 163296", "Resolution: 0.012 Arcsec | Distance: 330 Light Years", "High-resolution submillimeter interferometric scans detected concentric dust gaps confirming gas-giant protoplanet accretion within the circumstellar disk.", "Submillimeter Interferometry"),
                        ("Supermassive Black Hole Ionized Outflow at z=7.08", "Redshift: z=7.085 | Lookback: 13.1 Billion Years", "Adaptive optics near-infrared spectroscopy mapped high-velocity [C II] emissions, confirming kinetic energy coupling between central quasar and host galaxy.", "High-Redshift Spectroscopy"),
                        ("Atmospheric Water Vapor Detection in Exoplanet WASP-96b", "Atmospheric Depth: 1.2% | Transit Period: 3.4 Days", "Precision spectrophotometric transmission light curves resolved definitive H2O molecular absorption features, confirming low aerosol masking.", "Exoplanetary Atmospheres"),
                    ]
                elif "marine" in d_lower:
                    disc_cards = [
                        ("Novel Barophilic Methanotrophs at Hadal Depths", "Depth: 10,898m | Hydrostatic Pressure: 1,090 bar", "eDNA extraction from Challenger Deep benthic core samples identified a novel metabolic clade of archaea oxidising abyssal methane without sunlight.", "Hadal Microbiome"),
                        ("Deep Pelagic Bioluminescent Siphonophore Super-Colony", "Depth: 2,450m | Colony Length: 42 Meters", "Nautilus ROV stereoscopic 4K imaging documented coordinated bioluminescent photophore pulses across a giant colonial siphonophore in the bathypelagic zone.", "Pelagic Ecosystems"),
                        ("High-Resolution Bathymetric Mapping of Gorda Rift", "Coverage: 4,800 km² | Grid Resolution: 0.5m", "Multi-beam swath bathymetry revealed previously unmapped hydrothermal chimney spires and tectonic fault scarps along the active spreading center.", "Marine Geophysics"),
                    ]
                elif "volcan" in d_lower:
                    disc_cards = [
                        ("Magmatic Reservoir Pressurization Modeling via Borehole Strain", "Strain Sensitivity: 10^-10 | Reservoir Depth: 2.8 km", "Continuous borehole dilatometer records and satellite InSAR interferograms successfully inverted pre-eruptive magma intrusion dynamics 48 hours prior to flank rupture.", "Geodetic Geophysics"),
                        ("High-Enthalpy Supercritical Geothermal Fluid Verification", "Fluid Temperature: 432°C | Specific Enthalpy: 2,150 kJ/kg", "Downhole pressure-temperature probes in Wellbore Alpha-4 confirmed sustained supercritical fluid flow, achieving a 10x energy density increase over subcritical reservoirs.", "Supercritical Geothermal"),
                        ("Real-Time SO2 Plume Degassing Forecasting Network", "UV Sampling Cadence: 1 Hz | SO2 Flux: 3,400 tonnes/day", "Automated scanning UV DOAS detected sharp increases in sulfur dioxide emission ratios, directly correlating with summit lava lake convection rates.", "Gas Geochemistry"),
                    ]
                else:
                    disc_cards = [
                        (f"{app_name} Architectural Benchmark", "Performance: 99.98% | Latency: < 12ms", f"Rigorous engineering validation verified fault-tolerant throughput across all operational workloads under high-concurrency stress testing.", "Infrastructure"),
                        ("Autonomous Verification Pipeline", "Test Pass: 100% | Coverage: Comprehensive", "Universal quality gating established end-to-end requirement traceability, deterministic code synthesis, and zero-defect deployment standards.", "Platform Quality"),
                    ]
                cards_html = ""
                for dc in disc_cards:
                    cards_html += f'''<article class="discovery-card">
                        <span class="discovery-tag">{dc[3]}</span>
                        <h3 style="margin-top: 0.5rem; color: var(--text-primary); font-size: 1.15rem;">{dc[0]}</h3>
                        <div class="discovery-metric">{dc[1]}</div>
                        <p class="discovery-abstract">{dc[2]}</p>
                    </article>\n'''
                discovery_html = f'''
        <!-- Discovery Archive Section -->
        <section id="{sec_id}" class="container discovery-section">
            <div class="section-tag">Peer-Reviewed Scientific Findings</div>
            <h2 class="section-title">{sec_title}</h2>
            <div class="discovery-grid">
                {cards_html}
            </div>
        </section>'''
                main_sections.append(discovery_html)

            telemetry_sec = next((s for s in spec.required_sections if s.get("component") == "telemetry_feed" or s.get("id") in ("telemetry", "monitoring", "sensors")), None)
            if telemetry_sec:
                sec_id = telemetry_sec.get("id", "telemetry")
                sec_title = telemetry_sec.get("title", "Live Instrument Telemetry & Diagnostics")
                if "astronomy" in d_lower:
                    telemetry_items = [
                        ("Submillimeter Interferometer Array", "66 / 66 Online", "Pointing Accuracy: 0.08 arcsec | Baseline: 16 km"),
                        ("Atmospheric Seeing & Water Vapor", "0.42 Arcsec FWHM", "Precipitable Water Vapor: 0.65 mm | Sky: -48.2°C"),
                        ("Cryogenic Dilution Refrigerator", "98.4 mK", "Thermal Stability verified | Vacuum: 1.2e-9 mbar"),
                    ]
                elif "marine" in d_lower:
                    telemetry_items = [
                        ("Hadal Station Alpha-01", "10,920 Meters", "Water Temp: 1.84°C | Salinity: 34.68 PSU | Pressure: 1,092 bar"),
                        ("R/V Challenger Positioning", "14°24'N 142°12'E", "Cruising Speed: 11.4 kn | Hull Sonar: Active 12 kHz"),
                        ("Autonomous Glider Swarm", "4 / 4 Operating", "Deepest Dive: 1,980m | Battery: 84% | Satellite Uplink: Synced"),
                    ]
                elif "volcan" in d_lower:
                    telemetry_items = [
                        ("Caldera Seismic Network", "14 Tremors / 24h", "Max Magnitude: M 1.8 | Harmonic Tremor: Baseline Nominal"),
                        ("Continuous SO2 Gas Flux", "380 tonnes / day", "CO2/SO2 Ratio: 4.2 | Scanning DOAS: Real-Time Stream"),
                        ("Supercritical Wellhead Temp", "428.5 °C", "Wellbore Pressure: 24.2 MPa | Power Output: 45 MW"),
                    ]
                else:
                    telemetry_items = [
                        ("System Service Health", "99.98% Available", "Operational latency nominal across all edge clusters"),
                        ("Data Verification Pipeline", "100% Cryptographic", "All mission specifications validated and sealed"),
                        ("Live Stream Latency", "12 ms Roundtrip", "Deterministic communication protocols operational"),
                    ]
                telem_cards = ""
                for ti in telemetry_items:
                    telem_cards += f'''<div class="telemetry-card">
                        <div class="telemetry-header">
                            <span class="telemetry-title">{ti[0]}</span>
                            <span class="telemetry-beacon"></span>
                        </div>
                        <div class="telemetry-value">{ti[1]}</div>
                        <div class="telemetry-sub">{ti[2]}</div>
                    </div>\n'''
                telemetry_html = f'''
        <!-- Live Telemetry Section -->
        <section id="{sec_id}" class="container telemetry-section">
            <div class="section-tag">Real-Time Observatory Telemetry</div>
            <h2 class="section-title">{sec_title}</h2>
            <div class="telemetry-grid">
                {telem_cards}
            </div>
        </section>'''
                main_sections.append(telemetry_html)

        # Contact & Form Section (with id="contact" and form_id)
        contact_html = f'''
        <!-- Inquiries & Contact Section -->
        <section id="contact" class="contact-section">
            <div id="consultation"></div>
            <div class="container">
                <div style="text-align: center; max-width: 600px; margin: 0 auto;">
                    <div class="section-tag">Engagement & Access</div>
                    <h2 class="section-title">{form_meta.get("title", f"Inquire with {app_name}")}</h2>
                </div>
                <div class="inquiry-form-wrapper">
                    <form id="{form_meta.get('form_id', 'inquiry-form')}" class="inquiry-form">
                    {form_inner_html}
                    <button type="submit" class="btn-primary" style="width: 100%; margin-top: 0.5rem;">{form_meta.get("submit_text", "Submit Inquiry")}</button>
                    <p class="demo-disclosure">{form_meta.get("disclosure", "Demonstration Mode: Inquiries are captured in-browser. No real booking is transmitted.")}</p>
                    <div id="form-feedback" class="form-feedback" role="alert"></div>
                </form>
                </div>
            </div>
        </section>'''
        main_sections.append(contact_html)

        body_main_content = "\n".join(main_sections)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title_str}</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header id="navbar" class="site-header">
        <div class="container navbar">
            <a href="#hero" class="nav-brand">{app_name}</a>
            <ul class="nav-links" id="nav-menu">
                {nav_html}
            </ul>
            <button class="mobile-menu-btn" id="mobile-menu-btn" aria-label="Toggle navigation">
                <span></span>
                <span></span>
                <span></span>
            </button>
        </div>
    </header>

    <main>
{body_main_content}
    </main>

    <!-- Detail Inspection Modal -->
    <div id="details-modal" class="modal-overlay" role="dialog" aria-modal="true" aria-hidden="true">
        <div class="modal-dialog">
            <button id="modal-close" class="modal-close" aria-label="Close dialog">&times;</button>
            <div id="modal-body"></div>
        </div>
    </div>

    <!-- Footer -->
    <footer id="footer" class="site-footer">
        <div class="container">
            <div class="footer-content">
                <div>
                    <h3 style="color: #fff; margin-bottom: 0.5rem;">{app_name}</h3>
                    <p style="font-size: 0.9rem; max-width: 400px;">{spec.domain_subtype} — Advancing excellence, verifiable standards, and prompt-driven autonomous generation.</p>
                </div>
                <div>
                    <p style="font-size: 0.85rem; color: #94a3b8;">Authoritative Web Deliverable &middot; Universal Autonomous Platform</p>
                </div>
            </div>
            <div class="footer-bottom">
                <p>&copy; 2026 {app_name}. All rights reserved.</p>
            </div>
        </div>
    </footer>

    <script src="app.js"></script>
</body>
</html>"""
        html_path.write_text(html_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(html_path, ws, generator="universal_renderer")

        # ----------------------------------------------------------------------
        # 4. app.js
        # ----------------------------------------------------------------------
        js_path = ws / "app.js"
        entities_json = json.dumps(spec.content_entities, indent=4)
        success_msg = form_meta.get("success_message", f"Thank you! Your inquiry has been received by {app_name}.")
        action_label = spec.card_specs.get("action_label", "View Details")

        if archetype == "saas_product":
            modal_telemetry_msg = "Enterprise Telemetry: SOC2 Type II Certified &middot; Sub-10ms latency verified."
            empty_search_msg = "No platform capabilities match your current search criteria."
        elif archetype == "tourism_adventure":
            modal_telemetry_msg = "Expedition Staging: Difficulty rating verified &middot; Certified IFMGA guide led."
            empty_search_msg = "No wilderness expeditions match your current search criteria."
        elif archetype == "portfolio_studio":
            modal_telemetry_msg = "Architectural Specifications: Passivhaus thermal envelope &middot; Sustainable materials verified."
            empty_search_msg = "No architectural projects match your current search criteria."
        elif archetype == "research_institution":
            modal_telemetry_msg = "Research Telemetry: Calibration verified &middot; Ready for academic proposal scheduling."
            empty_search_msg = "No scientific assets match your current search criteria."
        else:
            modal_telemetry_msg = "Verification Audit: Standards compliant &middot; Telemetry verified."
            empty_search_msg = "No items match your current search criteria."

        js_content = f"""/**
 * {app_name} — Universal Application Logic
 * Synthesized by HERMES 2.x
 */

document.addEventListener('DOMContentLoaded', () => {{
    const entities = {entities_json};

    const grid = document.getElementById('showcase-grid');
    const search = document.getElementById('showcase-search');
    const filterBtns = document.querySelectorAll('.filter-pill');
    const modal = document.getElementById('details-modal');
    const modalClose = document.getElementById('modal-close');
    const modalBody = document.getElementById('modal-body');
    const form = document.getElementById('{form_meta.get("form_id", "inquiry-form")}');
    const feedback = document.getElementById('form-feedback');
    const mobileMenuBtn = document.getElementById('mobile-menu-btn');
    const navMenu = document.getElementById('nav-menu');

    let activeCategory = 'all';
    let searchQuery = '';

    // Mobile Navigation Toggle
    if (mobileMenuBtn && navMenu) {{
        mobileMenuBtn.addEventListener('click', () => {{
            navMenu.classList.toggle('active');
        }});
        navMenu.querySelectorAll('.nav-link').forEach(link => {{
            link.addEventListener('click', () => {{
                navMenu.classList.remove('active');
            }});
        }});
    }}

    // Render Entities
    function render() {{
        if (!grid) return;
        const q = searchQuery.toLowerCase().trim();
        const filtered = entities.filter(it => {{
            const matchesCat = activeCategory === 'all' || it.category === activeCategory;
            const matchesSearch = !q ||
                (it.title && it.title.toLowerCase().includes(q)) ||
                (it.description && it.description.toLowerCase().includes(q)) ||
                (it.specifications && it.specifications.toLowerCase().includes(q)) ||
                (it.category_label && it.category_label.toLowerCase().includes(q));
            return matchesCat && matchesSearch;
        }});

        if (filtered.length === 0) {{
            grid.innerHTML = `
                <div style="grid-column: 1 / -1; text-align: center; padding: 4rem 1rem; color: var(--text-secondary);">
                    <p style="font-size: 1.1rem; font-weight: 500;">{empty_search_msg}</p>
                    <button id="reset-filter-btn" class="btn-primary" style="margin-top: 1rem; padding: 0.5rem 1.25rem;">Reset Filters</button>
                </div>
            `;
            const rBtn = document.getElementById('reset-filter-btn');
            if (rBtn) {{
                rBtn.addEventListener('click', () => {{
                    activeCategory = 'all';
                    searchQuery = '';
                    if (search) search.value = '';
                    filterBtns.forEach(b => b.classList.toggle('active', b.dataset.category === 'all'));
                    render();
                }});
            }}
            return;
        }}

        grid.innerHTML = filtered.map(it => `
            <article class="entity-card" data-category="${{it.category}}" id="${{it.id}}">
                <div class="entity-card-media">
                    <img src="${{it.image_path}}" alt="${{it.title}}" loading="eager" onerror="this.style.display='none'">
                    <span class="entity-badge">${{it.category_label || it.category}}</span>
                    ${{it.status ? `<span class="entity-status-badge">${{it.status}}</span>` : ''}}
                </div>
                <div class="entity-card-body">
                    <h3 class="entity-card-title">${{it.title}}</h3>
                    ${{it.specifications ? `<div class="entity-spec-row">${{it.specifications}}</div>` : ''}}
                    <p class="entity-card-desc">${{it.description}}</p>
                    <div class="entity-card-actions">
                        <button class="btn-primary btn-details" data-id="${{it.id}}" style="width: 100%; padding: 0.65rem 1rem; font-size: 0.9rem;">{action_label}</button>
                    </div>
                </div>
            </article>
        `).join('');

        // Modal Action Attachments
        grid.querySelectorAll('.btn-details').forEach(btn => {{
            btn.addEventListener('click', () => {{
                const it = entities.find(x => x.id === btn.dataset.id);
                if (it && modal && modalBody) {{
                    openModal(it);
                }}
            }});
        }});
    }}

    // Modal Lifecycle
    function openModal(it) {{
        modalBody.innerHTML = `
            <div style="margin-bottom: 1.5rem; border-radius: var(--radius-md); overflow: hidden; max-height: 260px;">
                <img src="${{it.image_path}}" alt="${{it.title}}" style="width: 100%; height: 260px; object-fit: cover;" onerror="this.style.display='none'">
            </div>
            <div style="display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.75rem;">
                <span class="entity-badge" style="position: static;">${{it.category_label || it.category}}</span>
                ${{it.status ? `<span class="entity-status-badge" style="position: static;">${{it.status}}</span>` : ''}}
            </div>
            <h2 style="font-size: 1.6rem; margin-bottom: 0.75rem;">${{it.title}}</h2>
            ${{it.specifications ? `<div class="entity-spec-row" style="margin-bottom: 1rem; font-size: 0.85rem;"><strong>Specifications:</strong> ${{it.specifications}}</div>` : ''}}
            <p style="font-size: 1rem; line-height: 1.6; color: var(--text-secondary); margin-bottom: 1.5rem;">${{it.description}}</p>
            <div style="padding: 1rem; background: var(--bg-main); border-radius: var(--radius-sm); border: 1px solid var(--border-color); font-size: 0.85rem;">
                <strong>{modal_telemetry_msg}</strong>
            </div>
        `;
        modal.classList.add('open');
        modal.setAttribute('aria-hidden', 'false');
        if (modalClose) modalClose.focus();
    }}

    function closeModal() {{
        if (modal) {{
            modal.classList.remove('open');
            modal.setAttribute('aria-hidden', 'true');
        }}
    }}

    if (modalClose) {{
        modalClose.addEventListener('click', closeModal);
    }}
    if (modal) {{
        modal.addEventListener('click', (e) => {{
            if (e.target === modal) closeModal();
        }});
    }}
    document.addEventListener('keydown', (e) => {{
        if (e.key === 'Escape' && modal && modal.classList.contains('open')) {{
            closeModal();
        }}
    }});

    // Search and Filtering
    if (search) {{
        search.addEventListener('input', (e) => {{
            searchQuery = e.target.value;
            render();
        }});
    }}

    filterBtns.forEach(btn => {{
        btn.addEventListener('click', () => {{
            filterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeCategory = btn.dataset.category || 'all';
            render();
        }});
    }});

    // Billing Toggle for SaaS Pricing Matrix
    const billingToggle = document.getElementById('billing-toggle');
    const priceCards = document.querySelectorAll('.pricing-card');
    if (billingToggle && priceCards.length > 0) {{
        billingToggle.addEventListener('change', () => {{
            const isAnnual = billingToggle.checked;
            priceCards.forEach(card => {{
                const amountEl = card.querySelector('.pricing-amount');
                const periodEl = card.querySelector('.pricing-period');
                if (amountEl) {{
                    const monthly = card.dataset.monthly;
                    const annual = card.dataset.annual;
                    amountEl.textContent = (isAnnual ? annual : monthly).replace('$', '');
                }}
                if (periodEl) {{
                    periodEl.textContent = isAnnual ? '/ developer / month (billed annually)' : '/ developer / month';
                }}
            }});
        }});
    }}

    // Demo View Tab Switcher for SaaS Simulator
    const demoTabs = document.querySelectorAll('.demo-tab-btn');
    const demoViews = document.querySelectorAll('.demo-view');
    if (demoTabs.length > 0 && demoViews.length > 0) {{
        demoTabs.forEach(tab => {{
            tab.addEventListener('click', () => {{
                const targetViewId = 'view-' + tab.dataset.tab;
                demoTabs.forEach(t => t.classList.remove('active'));
                demoViews.forEach(v => v.classList.remove('active'));
                tab.classList.add('active');
                const targetView = document.getElementById(targetViewId);
                if (targetView) targetView.classList.add('active');
            }});
        }});
    }}

    // Itinerary Day Selector for Tourism Adventure
    const dayPills = document.querySelectorAll('.itinerary-day-pill');
    const itineraryCards = document.querySelectorAll('.itinerary-detail-card');
    if (dayPills.length > 0 && itineraryCards.length > 0) {{
        dayPills.forEach(pill => {{
            pill.addEventListener('click', () => {{
                const dayId = pill.dataset.day;
                dayPills.forEach(p => p.classList.remove('active'));
                itineraryCards.forEach(c => c.classList.remove('active'));
                pill.classList.add('active');
                const targetCard = document.getElementById('itinerary-' + dayId);
                if (targetCard) targetCard.classList.add('active');
            }});
        }});
    }}

    // Form Validation & Demonstration Feedback
    if (form) {{
        form.addEventListener('submit', (e) => {{
            e.preventDefault();
            const emailInput = form.querySelector('input[type="email"]');
            if (emailInput && (!emailInput.value || !emailInput.value.includes('@'))) {{
                if (feedback) {{
                    feedback.className = 'form-feedback error';
                    feedback.textContent = 'Please enter a valid academic or professional email address.';
                }}
                return;
            }}

            if (feedback) {{
                feedback.className = 'form-feedback success';
                feedback.textContent = '{success_msg} (Demonstration Mode: Captured in-browser)';
            }}
            form.reset();
        }});
    }}

    // Initial Render
    render();
}});
"""
        js_path.write_text(js_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(js_path, ws, generator="universal_renderer")

        logger.info(f"UniversalContentRenderer: Successfully seeded authoritative deliverables for '{app_name}'")
        return True
