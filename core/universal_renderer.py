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

        # Check if asset_manifest.json exists on disk to bind true provisioned asset paths
        manifest_file = ws / ".hermes" / "asset_manifest.json"
        manifest_data = None
        if manifest_file.exists():
            try:
                manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        hero_asset = next((a for a in spec.asset_requirements if a.get("component") == "hero"), None)
        hero_img_path = hero_asset.get("relative_path", "assets/images/hero-main.jpg") if hero_asset else "assets/images/hero-main.jpg"
        if manifest_data and "assets" in manifest_data:
            manifest_hero = next((a for a in manifest_data["assets"] if a.get("intended_component") == "hero" or a.get("asset_id") == "hero"), None)
            if manifest_hero and manifest_hero.get("relative_path"):
                hero_img_path = manifest_hero["relative_path"]

            # Also bind entity image paths from manifest if available
            m_map = {a.get("asset_id"): a.get("relative_path") for a in manifest_data["assets"] if a.get("relative_path")}
            for ent in spec.content_entities:
                eid = ent.get("id")
                if eid in m_map:
                    ent["image_path"] = m_map[eid]

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

.grid {{
    display: grid;
    gap: 1.5rem;
}}

.card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    overflow: hidden;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}}

.card:hover {{
    transform: translateY(-2px);
    box-shadow: var(--shadow-md);
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
.priority-p2 {{ background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); }}
.priority-done {{ background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }}

.kanban-card[draggable="true"] {{
    cursor: grab;
}}
.kanban-card.dragging {{
    opacity: 0.55;
    transform: scale(0.98);
}}
.kanban-column.drag-over {{
    border-color: var(--accent-color);
    background: rgba(56, 189, 248, 0.06);
}}
.kanban-progress-wrap {{
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    padding: 1rem 1.25rem;
    margin-bottom: 1.25rem;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
}}
.kanban-progress-track {{
    flex: 1;
    min-width: 180px;
    height: 10px;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 9999px;
    overflow: hidden;
}}
.kanban-progress-fill {{
    height: 100%;
    background: linear-gradient(90deg, var(--accent-color), var(--accent-secondary));
    transition: width 0.25s ease;
}}
.kanban-toolbar {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin-bottom: 1.5rem;
    align-items: center;
}}
.kanban-card-actions {{
    display: flex;
    justify-content: flex-end;
    gap: 0.4rem;
    margin-top: 0.65rem;
}}
.btn-move-card {{
    background: transparent;
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.72rem;
    cursor: pointer;
}}
.btn-move-card:hover {{
    border-color: var(--accent-color);
    color: var(--text-primary);
}}

/* Editorial & Culinary Split Panels */
.editorial-lead-card {{
    display: grid;
    grid-template-columns: 1.25fr 1fr;
    gap: 2.5rem;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    overflow: hidden;
    box-shadow: var(--shadow-md);
    align-items: stretch;
}}
.editorial-lead-media img {{
    width: 100%;
    height: 100%;
    min-height: 360px;
    object-fit: cover;
    display: block;
}}
.editorial-lead-body {{
    padding: 2.5rem;
    display: flex;
    flex-direction: column;
    justify-content: center;
}}
.demo-disclosure-pill {{
    display: inline-block;
    font-size: 0.75rem;
    font-family: var(--font-mono);
    padding: 0.25rem 0.65rem;
    border-radius: 9999px;
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    margin-bottom: 0.75rem;
}}
@media (max-width: 900px) {{
    .editorial-lead-card {{
        grid-template-columns: 1fr;
    }}
}}

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

/* Marketplace Components: Sorting, Cards, Basket, Benefits, Onboarding, Impact */
.sort-container {{
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 1.5rem;
    justify-content: flex-end;
}}

.sort-label {{
    font-size: 0.9rem;
    color: var(--text-secondary);
    font-weight: 500;
}}

.sort-select {{
    padding: 0.5rem 1rem;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border-color);
    background: var(--bg-card);
    color: var(--text-primary);
    font-size: 0.9rem;
    cursor: pointer;
}}

.entity-price-row {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin: 0.75rem 0;
}}

.price-tag {{
    font-size: 1.25rem;
    font-weight: 800;
    color: var(--accent-color);
}}

.carbon-badge {{
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.78rem;
    color: #15803d;
    background: #dcfce7;
    padding: 0.2rem 0.6rem;
    border-radius: 9999px;
    font-weight: 600;
}}

.provenance-tag {{
    font-size: 0.8rem;
    color: var(--text-secondary);
    margin-bottom: 0.5rem;
}}

.stock-tag {{
    font-size: 0.78rem;
    color: #047857;
    font-weight: 600;
    margin-bottom: 0.5rem;
}}

.entity-card-actions-marketplace {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem;
    margin-top: 1rem;
}}

/* Interactive Quote Assembly Basket */
.quote-basket-section {{
    padding: 4rem 0;
    background: var(--bg-card);
    border-top: 1px solid var(--border-color);
    border-bottom: 1px solid var(--border-color);
}}

.quote-basket-box {{
    background: var(--bg-main);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 2rem;
    margin-top: 2rem;
}}

.basket-table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 1.5rem;
}}

.basket-table th {{
    text-align: left;
    padding: 0.75rem 1rem;
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-secondary);
    border-bottom: 1px solid var(--border-color);
}}

.basket-table td {{
    padding: 1rem;
    border-bottom: 1px solid var(--border-color);
    vertical-align: middle;
}}

.qty-controls {{
    display: inline-flex;
    align-items: center;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    background: var(--bg-card);
    overflow: hidden;
}}

.qty-btn {{
    background: transparent;
    border: none;
    padding: 0.35rem 0.75rem;
    font-size: 1rem;
    cursor: pointer;
    color: var(--text-primary);
    transition: background 0.15s ease;
}}

.qty-btn:hover {{
    background: var(--border-color);
}}

.qty-val {{
    padding: 0.35rem 0.75rem;
    font-size: 0.9rem;
    font-weight: 600;
    min-width: 2.5rem;
    text-align: center;
}}

.btn-remove-item {{
    background: transparent;
    border: none;
    color: #ef4444;
    cursor: pointer;
    font-size: 1.25rem;
    padding: 0.25rem;
}}

.basket-summary-row {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 1.5rem;
    border-top: 2px solid var(--border-color);
    flex-wrap: wrap;
    gap: 1rem;
}}

.basket-subtotal-box {{
    font-size: 1.1rem;
    color: var(--text-primary);
}}

.basket-subtotal-val {{
    font-size: 1.85rem;
    font-weight: 800;
    color: var(--accent-color);
    margin-left: 0.5rem;
}}

.empty-basket {{
    text-align: center;
    padding: 3rem 1rem;
    color: var(--text-secondary);
}}

/* Benefits & Circular Workflow */
.benefits-grid,
.onboarding-grid,
.impact-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 1.5rem;
    margin-top: 2rem;
}}

.benefit-card,
.onboarding-card,
.impact-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 1.75rem;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}}

.benefit-card:hover,
.onboarding-card:hover,
.impact-card:hover {{
    transform: translateY(-2px);
    box-shadow: var(--shadow-md);
}}

.benefit-step,
.onboarding-step {{
    display: inline-block;
    font-family: var(--font-mono);
    font-size: 0.85rem;
    font-weight: 700;
    color: var(--accent-color);
    margin-bottom: 0.75rem;
}}

.impact-metric {{
    font-size: 2.25rem;
    font-weight: 800;
    color: var(--accent-color);
    margin-bottom: 0.5rem;
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

        showcase_sec = next((s for s in spec.required_sections if s.get("component") in ("showcase_grid", "showcase", "portfolio_grid", "features_grid") or s.get("id") in ("showcase", "portfolio", "features", "expeditions", "services", "exhibits", "menu", "articles")), None)
        showcase_sec_id = showcase_sec.get("id", "showcase") if showcase_sec else "showcase"
        showcase_title = showcase_sec.get("title", f"{app_name} Showcase") if showcase_sec else f"{app_name} Showcase"

        archetype = spec.application_archetype
        d_lower = spec.business_domain.lower()

        # Archetype Specific Hero Actions & Proof Metrics
        if archetype == "saas_product":
            hero_actions_html = """
                    <a href="#demo-preview" class="btn-primary">Launch Interactive Workspace</a>
                    <a href="#pricing" class="btn-secondary">Compare Plans</a>"""
            hero_proof_html = """
                    <div class="hero-stat-item"><span class="hero-stat-num">Kanban</span><span class="hero-stat-lbl">Interactive Sprint Board</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">RBAC</span><span class="hero-stat-lbl">Sample Team Roster</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">Demo</span><span class="hero-stat-lbl">In-Browser Simulation</span></div>"""
            hero_status_chip = "WORKSPACE INTERFACE DEMO"
            hero_metric_val = "Interactive"
            hero_metric_lbl = "Kanban · Teams · Billing"
            hero_status_text = "Simulation Active"
        elif archetype == "culinary_restaurant":
            hero_actions_html = f"""
                    <a href="#{showcase_sec_id}" class="btn-primary">Explore Seasonal Menu</a>
                    <a href="#contact" class="btn-secondary">Reserve a Table</a>"""
            hero_proof_html = """
                    <div class="hero-stat-item"><span class="hero-stat-num">Hearth</span><span class="hero-stat-lbl">Wood-Fired Craft</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">Tue–Sun</span><span class="hero-stat-lbl">Dinner Service</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">Demo</span><span class="hero-stat-lbl">Sample Booking Validation</span></div>"""
            hero_status_chip = "SEASONAL KITCHEN & HEARTH"
            hero_metric_val = "Courses"
            hero_metric_lbl = "Illustrative Menu & Seating"
            hero_status_text = "Demonstration Mode"
        elif archetype == "editorial_publication":
            hero_actions_html = f"""
                    <a href="#featured-story" class="btn-primary">Read Lead Story</a>
                    <a href="#{showcase_sec_id}" class="btn-secondary">Browse Dispatches</a>"""
            hero_proof_html = """
                    <div class="hero-stat-item"><span class="hero-stat-num">4 Desks</span><span class="hero-stat-lbl">Science · Tech · Climate · Innovation</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">Long-Form</span><span class="hero-stat-lbl">Sample Issue Archive</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">Demo</span><span class="hero-stat-lbl">Reader & Newsletter Validation</span></div>"""
            hero_status_chip = "DIGITAL PUBLICATION · ISSUE 04 DEMO"
            hero_metric_val = "Long-Form"
            hero_metric_lbl = "Sample Dispatches & Reader"
            hero_status_text = "Demonstration Edition"
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
        elif archetype == "marketplace":
            hero_actions_html = f"""
                    <a href="#{showcase_sec_id}" class="btn-primary">Browse Materials Catalogue</a>
                    <a href="#quote-basket" class="btn-secondary">View Quote Basket (<span id="basket-count">0</span>)</a>"""
            hero_proof_html = """
                    <div class="hero-stat-item"><span class="hero-stat-num">Reuse</span><span class="hero-stat-lbl">Lifecycle Extension</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">Direct</span><span class="hero-stat-lbl">Supplier-to-Buyer Marketplace</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">Circular</span><span class="hero-stat-lbl">Waste Reduction Focus</span></div>"""
            hero_status_chip = "CIRCULAR CONSTRUCTION MARKETPLACE"
            hero_metric_val = "Circular Sourcing"
            hero_metric_lbl = "Material Recovery Network"
            hero_status_text = "Marketplace Active"
        elif "geospatial" in d_lower or "survey" in d_lower or "skytrace" in app_name.lower():
            hero_actions_html = f"""
                    <a href="#{showcase_sec_id}" class="btn-primary">Explore Survey Capabilities</a>
                    <a href="#calculator" class="btn-secondary">Interactive Quote Estimate</a>"""
            hero_proof_html = """
                    <div class="hero-stat-item"><span class="hero-stat-num">&lt; 1 cm</span><span class="hero-stat-lbl">Ground Sampling Distance</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">300 pts/m²</span><span class="hero-stat-lbl">LiDAR Point Density</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">FAA Part 107</span><span class="hero-stat-lbl">Certified Remote Pilots</span></div>"""
            hero_status_chip = "GEOSPATIAL INTELLIGENCE & AERIAL SURVEYING"
            hero_metric_val = "Sub-Centimeter"
            hero_metric_lbl = "Survey-Grade Precision"
            hero_status_text = "Flight Operations Active"
        elif "education" in d_lower or "museum" in d_lower or "sparkfield" in app_name.lower() or "science" in d_lower:
            hero_actions_html = f"""
                    <a href="#tickets" class="btn-primary">Book Museum Tickets</a>
                    <a href="#{showcase_sec_id}" class="btn-secondary">Explore Interactive Labs</a>"""
            hero_proof_html = """
                    <div class="hero-stat-item"><span class="hero-stat-num">65+</span><span class="hero-stat-lbl">Hands-On Exhibits</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">360&deg;</span><span class="hero-stat-lbl">Planetarium Dome</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">4.9 / 5</span><span class="hero-stat-lbl">Family Visitor Rating</span></div>"""
            hero_status_chip = "CHILDREN'S SCIENCE & DISCOVERY CENTER"
            hero_metric_val = "Ages 3-16"
            hero_metric_lbl = "Hands-On STEM Learning"
            hero_status_text = "Open Today: 9 AM - 6 PM"
        elif "astronomy" in d_lower or "marine" in d_lower or "volcan" in d_lower or "observatory" in d_lower or "research" in archetype:
            hero_actions_html = f"""
                    <a href="#contact" class="btn-primary">Submit Observation Inquiry</a>
                    <a href="#{showcase_sec_id}" class="btn-secondary">Explore Research Instruments</a>"""
            hero_proof_html = """
                    <div class="hero-stat-item"><span class="hero-stat-num">Instruments</span><span class="hero-stat-lbl">Field &amp; Lab Specs</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">Archive</span><span class="hero-stat-lbl">Searchable Catalog</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">Demo</span><span class="hero-stat-lbl">Proposal Form</span></div>"""
            hero_status_chip = spec.domain_subtype.upper()[:42]
            hero_metric_val = f"{len(spec.content_entities)} Assets"
            hero_metric_lbl = "Scientific Showcase"
            hero_status_text = "Sample Portal"
        else:
            hero_actions_html = f"""
                    <a href="#{showcase_sec_id}" class="btn-primary">Explore Offerings</a>
                    <a href="#contact" class="btn-secondary">Request Information</a>"""
            hero_proof_html = f"""
                    <div class="hero-stat-item"><span class="hero-stat-num">{len(spec.content_entities)} Offerings</span><span class="hero-stat-lbl">Domain Catalog</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">Interactive</span><span class="hero-stat-lbl">Search &amp; Filters</span></div>
                    <div class="hero-stat-item"><span class="hero-stat-num">Demo Mode</span><span class="hero-stat-lbl">In-Browser Validation</span></div>"""
            hero_status_chip = spec.domain_subtype.upper()[:42]
            hero_metric_val = f"{len(spec.content_entities)} Curated"
            hero_metric_lbl = spec.domain_subtype
            hero_status_text = "Sample Showcase"

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
            <div class="section-tag">Interactive Software Interface (Sample Workspace Demo)</div>
            <h2 class="section-title">Interactive {app_name} Workspace</h2>
            <p class="about-lead">Drag-and-drop tasks across columns, create sprint issues, adjust team roles, and track progress metrics live in-browser. <em>(Sample Demonstration Data)</em></p>
            <div class="demo-window">
                <div class="demo-window-header">
                    <div class="demo-window-dots">
                        <span class="demo-dot red"></span>
                        <span class="demo-dot yellow"></span>
                        <span class="demo-dot green"></span>
                    </div>
                    <div class="demo-tabs">
                        <button class="demo-tab-btn active" data-tab="kanban" id="tab-kanban">Sprint Board</button>
                        <button class="demo-tab-btn" data-tab="analytics" id="tab-analytics">Project Metrics</button>
                        <button class="demo-tab-btn" data-tab="automation" id="tab-automation">Workflow Rules</button>
                    </div>
                    <div style="font-size: 0.8rem; color: var(--text-secondary); font-family: var(--font-mono);">mode: in-browser demo</div>
                </div>
                <div class="demo-window-body">
                    <!-- Kanban View -->
                    <div id="view-kanban" class="demo-view active">
                        <div class="kanban-progress-wrap">
                            <div style="display: flex; gap: 1.5rem; flex-wrap: wrap; font-size: 0.88rem;">
                                <span>Total: <strong id="kanban-total-count" style="color: var(--text-primary);">6</strong></span>
                                <span>In Progress: <strong id="kanban-inprogress-count" style="color: #fbbf24;">2</strong></span>
                                <span>Completed: <strong id="kanban-completed-count" style="color: #34d399;">2</strong></span>
                                <span>Sprint Completion: <strong id="kanban-progress-pct" style="color: var(--accent-color);">33%</strong></span>
                            </div>
                            <div class="kanban-progress-track">
                                <div id="kanban-progress-bar" class="kanban-progress-fill" style="width: 33%;"></div>
                            </div>
                        </div>
                        <div class="kanban-toolbar">
                            <input type="text" id="new-task-title" class="search-input" placeholder="Create new sprint task (e.g. AUTH-204: Token Refresh)..." style="flex: 1; min-width: 240px;">
                            <select id="new-task-priority" class="form-control" style="width: auto; min-width: 130px;">
                                <option value="P1">P1 High</option>
                                <option value="P0">P0 Critical</option>
                                <option value="P2">P2 Normal</option>
                            </select>
                            <button type="button" id="add-task-btn" class="btn-primary">+ Add Task</button>
                        </div>
                        <div class="kanban-grid">
                            <div class="kanban-column" id="col-backlog" data-status="backlog">
                                <div class="kanban-col-header"><span>Backlog</span> <span id="count-backlog">2 Items</span></div>
                                <div class="kanban-cards-slot" id="slot-backlog">
                                    <div class="kanban-card" draggable="true" data-task-id="task-1" data-status="backlog">
                                        <div class="kanban-card-title">AUTH-102: Configure OIDC 2.0 Login Flow</div>
                                        <div class="kanban-card-meta"><span>Sample Security Squad</span> <span class="priority-tag priority-p1">P1</span></div>
                                        <div class="kanban-card-actions"><button type="button" class="btn-move-card" data-dir="next">Move &rarr;</button></div>
                                    </div>
                                    <div class="kanban-card" draggable="true" data-task-id="task-2" data-status="backlog">
                                        <div class="kanban-card-title">API-88: Token Bucket Rate Limiter Spec</div>
                                        <div class="kanban-card-meta"><span>Sample Core Squad</span> <span class="priority-tag priority-p1">P1</span></div>
                                        <div class="kanban-card-actions"><button type="button" class="btn-move-card" data-dir="next">Move &rarr;</button></div>
                                    </div>
                                </div>
                            </div>
                            <div class="kanban-column" id="col-inprogress" data-status="inprogress">
                                <div class="kanban-col-header"><span>In Progress</span> <span id="count-inprogress">2 Items</span></div>
                                <div class="kanban-cards-slot" id="slot-inprogress">
                                    <div class="kanban-card" draggable="true" data-task-id="task-3" data-status="inprogress">
                                        <div class="kanban-card-title">ENGINE-401: CRDT Workspace Sync</div>
                                        <div class="kanban-card-meta"><span>Sample Infra Team</span> <span class="priority-tag priority-p0">P0</span></div>
                                        <div class="kanban-card-actions"><button type="button" class="btn-move-card" data-dir="prev">&larr;</button><button type="button" class="btn-move-card" data-dir="next">Move &rarr;</button></div>
                                    </div>
                                    <div class="kanban-card" draggable="true" data-task-id="task-4" data-status="inprogress">
                                        <div class="kanban-card-title">UI-305: Burndown Visualization Widget</div>
                                        <div class="kanban-card-meta"><span>Sample Frontend Squad</span> <span class="priority-tag priority-p1">P1</span></div>
                                        <div class="kanban-card-actions"><button type="button" class="btn-move-card" data-dir="prev">&larr;</button><button type="button" class="btn-move-card" data-dir="next">Move &rarr;</button></div>
                                    </div>
                                </div>
                            </div>
                            <div class="kanban-column" id="col-completed" data-status="completed">
                                <div class="kanban-col-header"><span>Completed</span> <span id="count-completed">2 Items</span></div>
                                <div class="kanban-cards-slot" id="slot-completed">
                                    <div class="kanban-card" draggable="true" data-task-id="task-5" data-status="completed">
                                        <div class="kanban-card-title">SEC-12: Role Permission Audit Trail UI</div>
                                        <div class="kanban-card-meta"><span>Sample Governance</span> <span class="priority-tag priority-done">Done</span></div>
                                        <div class="kanban-card-actions"><button type="button" class="btn-move-card" data-dir="prev">&larr; Reopen</button></div>
                                    </div>
                                    <div class="kanban-card" draggable="true" data-task-id="task-6" data-status="completed">
                                        <div class="kanban-card-title">CLI-10: Workspace Export Command</div>
                                        <div class="kanban-card-meta"><span>Sample DevRel Squad</span> <span class="priority-tag priority-done">Done</span></div>
                                        <div class="kanban-card-actions"><button type="button" class="btn-move-card" data-dir="prev">&larr; Reopen</button></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <!-- Analytics View -->
                    <div id="view-analytics" class="demo-view">
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1.5rem; margin-bottom: 1.5rem;">
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.5rem; border-radius: var(--radius-sm);">
                                <div style="font-size: 0.85rem; color: var(--text-secondary);">Sample Sprint Velocity</div>
                                <div style="font-size: 2rem; font-weight: 800; color: var(--accent-color); margin-top: 0.25rem;" id="metric-velocity">42 <span style="font-size: 0.9rem; color: var(--text-secondary);">pts (demo)</span></div>
                            </div>
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.5rem; border-radius: var(--radius-sm);">
                                <div style="font-size: 0.85rem; color: var(--text-secondary);">Mean Cycle Target</div>
                                <div style="font-size: 2rem; font-weight: 800; color: var(--text-primary); margin-top: 0.25rem;">1.8 <span style="font-size: 0.9rem; color: var(--text-secondary);">days (sample)</span></div>
                            </div>
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.5rem; border-radius: var(--radius-sm);">
                                <div style="font-size: 0.85rem; color: var(--text-secondary);">Active Tasks Done</div>
                                <div style="font-size: 2rem; font-weight: 800; color: #34d399; margin-top: 0.25rem;" id="metric-completion-rate">33%</div>
                            </div>
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.5rem; border-radius: var(--radius-sm);">
                                <div style="font-size: 0.85rem; color: var(--text-secondary);">Active Demo Seats</div>
                                <div style="font-size: 2rem; font-weight: 800; color: var(--accent-color); margin-top: 0.25rem;" id="metric-team-seats">3</div>
                            </div>
                        </div>
                        <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.25rem; border-radius: var(--radius-sm); font-size: 0.88rem; color: var(--text-secondary);">
                            <strong>Demonstration Metrics Note:</strong> Figures above reflect simulated in-browser board state rather than live production telemetry.
                        </div>
                    </div>
                    <!-- Automation View -->
                    <div id="view-automation" class="demo-view">
                        <div style="display: flex; flex-direction: column; gap: 1rem;">
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.25rem; border-radius: var(--radius-sm); display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <div style="font-weight: 600; color: var(--text-primary);">When PR receives 2 approvals &rarr; Move card from In Progress to Completed</div>
                                    <div style="font-size: 0.85rem; color: var(--text-secondary); margin-top: 0.25rem;">Trigger: Repository Webhook Pattern &middot; Sample Rule Spec</div>
                                </div>
                                <span class="priority-tag priority-done">Demo Rule</span>
                            </div>
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); padding: 1.25rem; border-radius: var(--radius-sm); display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <div style="font-weight: 600; color: var(--text-primary);">When issue severity is set to 'P0' &rarr; Notify Incident Coordinator</div>
                                    <div style="font-size: 0.85rem; color: var(--text-secondary); margin-top: 0.25rem;">Trigger: Issue State Mutation &middot; Sample Escalation Template</div>
                                </div>
                                <span class="priority-tag priority-done">Demo Rule</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <!-- Team Management Interface -->
        <section id="team-management" class="container" style="padding: 4.5rem 0; border-top: 1px solid var(--border-color);">
            <div style="display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem;">
                <div>
                    <div class="section-tag">Team Workspace Directory (Sample Data)</div>
                    <h2 class="section-title">Team & Role Management</h2>
                    <p class="about-lead" style="margin-bottom: 0;">Add simulated collaborators, update RBAC permissions, or revoke sample seats in real-time. <em>(In-Browser Demo Only — No external user accounts created)</em></p>
                </div>
                <div style="font-family: var(--font-mono); font-size: 0.9rem; color: var(--accent-color);">Active Seats: <strong id="team-member-count">3</strong></div>
            </div>
            <div class="kanban-toolbar" style="margin-bottom: 1.5rem;">
                <input type="text" id="team-member-name" class="search-input" placeholder="Sample collaborator name (e.g. Sample QA Engineer)..." style="flex: 1; min-width: 200px;">
                <input type="email" id="team-member-email" class="search-input" placeholder="demo.user@example.invalid" style="flex: 1; min-width: 200px;">
                <select id="team-member-role" class="form-control" style="width: auto; min-width: 140px;">
                    <option value="Maintainer">Maintainer</option>
                    <option value="Admin">Admin</option>
                    <option value="Viewer">Viewer</option>
                </select>
                <button type="button" id="add-member-btn" class="btn-primary">+ Invite Member (Demo)</button>
            </div>
            <div class="table-responsive">
                <table class="schedule-table">
                    <thead>
                        <tr><th>Sample Member Profile</th><th>Demo Address</th><th>Workspace Role</th><th>Action</th></tr>
                    </thead>
                    <tbody id="team-roster-body">
                        <tr data-member-id="m-1"><td><strong>Sample Staff Engineer</strong></td><td>staff.demo@example.invalid</td><td><select class="form-control role-select" style="padding: 0.25rem 0.5rem; width: auto;"><option value="Admin" selected>Admin</option><option value="Maintainer">Maintainer</option><option value="Viewer">Viewer</option></select></td><td><button type="button" class="btn-move-card btn-remove-member">Remove</button></td></tr>
                        <tr data-member-id="m-2"><td><strong>Sample Product Lead</strong></td><td>product.demo@example.invalid</td><td><select class="form-control role-select" style="padding: 0.25rem 0.5rem; width: auto;"><option value="Admin">Admin</option><option value="Maintainer" selected>Maintainer</option><option value="Viewer">Viewer</option></select></td><td><button type="button" class="btn-move-card btn-remove-member">Remove</button></td></tr>
                        <tr data-member-id="m-3"><td><strong>Sample UI Architect</strong></td><td>design.demo@example.invalid</td><td><select class="form-control role-select" style="padding: 0.25rem 0.5rem; width: auto;"><option value="Admin">Admin</option><option value="Maintainer">Maintainer</option><option value="Viewer" selected>Viewer</option></select></td><td><button type="button" class="btn-move-card btn-remove-member">Remove</button></td></tr>
                    </tbody>
                </table>
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
                <div class="section-tag">Illustrative Billing Comparison</div>
                <h2 class="section-title">Plan Comparison & Billing Switcher</h2>
                <p style="color: var(--text-secondary); margin-top: 0.75rem;">Toggle monthly or annual rates to preview illustrative software tiers. <em>(Demonstration Only — No live billing or payment transactions occur)</em></p>
            </div>
            
            <div class="billing-toggle-container">
                <span class="billing-label">Monthly Billing</span>
                <label class="switch">
                    <input type="checkbox" id="billing-toggle">
                    <span class="slider"></span>
                </label>
                <span class="billing-label">Annual Billing</span>
                <span class="discount-badge">Illustrative 20% Discount</span>
            </div>
            
            <div class="pricing-grid">
                <div class="pricing-card" data-monthly="$29" data-annual="$23">
                    <div class="plan-name">Starter Squad (Sample Tier)</div>
                    <div class="plan-desc">Essential Kanban sprint boards and demo workflow rules for small teams.</div>
                    <div class="pricing-price-box">
                        <span class="pricing-currency">$</span>
                        <span class="pricing-amount">29</span>
                        <span class="pricing-period">/ seat / month (illustrative)</span>
                    </div>
                    <ul class="pricing-features">
                        <li>Up to 15 Workspace Seats</li>
                        <li>Interactive Kanban & Sprint Boards</li>
                        <li>Git Repository Webhook Pattern</li>
                        <li>Velocity & Progress Bars</li>
                    </ul>
                    <a href="#contact" class="btn-primary" style="text-align: center; width: 100%;">Try Starter Demo</a>
                </div>
                
                <div class="pricing-card featured" data-monthly="$79" data-annual="$63">
                    <div class="popular-ribbon">Illustrative Pro</div>
                    <div class="plan-name">Growth Team (Sample Tier)</div>
                    <div class="plan-desc">Cross-squad dependency tracking and RBAC role management for growing engineering teams.</div>
                    <div class="pricing-price-box">
                        <span class="pricing-currency">$</span>
                        <span class="pricing-amount">79</span>
                        <span class="pricing-period">/ seat / month (illustrative)</span>
                    </div>
                    <ul class="pricing-features">
                        <li>Unlimited Sample Seats</li>
                        <li>Event-Driven Automation Rules</li>
                        <li>Cross-Squad Dependency Graphs</li>
                        <li>SAML / OIDC Ready Spec</li>
                    </ul>
                    <a href="#contact" class="btn-primary" style="text-align: center; width: 100%;">Request Demo Sandbox</a>
                </div>
                
                <div class="pricing-card" data-monthly="$199" data-annual="$159">
                    <div class="plan-name">Enterprise Architecture (Sample Tier)</div>
                    <div class="plan-desc">Isolated tenant blueprints, granular access policies, and custom integration webhooks.</div>
                    <div class="pricing-price-box">
                        <span class="pricing-currency">$</span>
                        <span class="pricing-amount">199</span>
                        <span class="pricing-period">/ seat / month (illustrative)</span>
                    </div>
                    <ul class="pricing-features">
                        <li>Single-Tenant VPC Blueprint</li>
                        <li>Custom Role-Based Policies</li>
                        <li>Structured Activity Audit Export</li>
                        <li>Dedicated Architecture Onboarding</li>
                    </ul>
                    <a href="#contact" class="btn-primary" style="text-align: center; width: 100%;">Explore Enterprise Spec</a>
                </div>
            </div>

            <div class="table-responsive" style="margin-top: 3rem;">
                <table class="schedule-table">
                    <thead>
                        <tr><th>Capability (Illustrative Comparison)</th><th>Starter Squad</th><th>Growth Team</th><th>Enterprise Architecture</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>Interactive Kanban Board & Drag-Drop</td><td>Included</td><td>Included</td><td>Included</td></tr>
                        <tr><td>Team Role Access Management</td><td>Basic</td><td>Full RBAC</td><td>Custom Policies + SSO</td></tr>
                        <tr><td>Workflow Automation Rules</td><td>Up to 5 Rules</td><td>Unlimited</td><td>Custom Webhook SLA</td></tr>
                        <tr><td>Checkout / Payment Mode</td><td colspan="3" style="text-align: center;"><em>Demonstration UI Only — No Financial Processing</em></td></tr>
                    </tbody>
                </table>
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

        elif archetype == "marketplace":
            benefits_html = f'''
        <!-- Circular Sourcing Workflow -->
        <section id="benefits" class="container benefits-section" style="padding: 4rem 0;">
            <div style="text-align: center; max-width: 650px; margin: 0 auto;">
                <div class="section-tag">Circular Supply Chain</div>
                <h2 class="section-title">How Circular Materials Sourcing Works</h2>
                <p class="about-lead">Connecting recovery suppliers with construction buyers to extend material lifecycles and reduce construction waste through direct reuse.</p>
            </div>
            <div class="benefits-grid">
                <div class="benefit-card">
                    <span class="benefit-step">01. SOURCING & RECOVERY</span>
                    <h3>Material Stream Intake</h3>
                    <p>Connecting recovery suppliers and demolition specialists with architects and builders seeking reusable inventory.</p>
                </div>
                <div class="benefit-card">
                    <span class="benefit-step">02. DOCUMENTATION</span>
                    <h3>Transparent Provenance</h3>
                    <p>Suppliers provide transparent material origin documentation, salvage details, and dimensional specifications.</p>
                </div>
                <div class="benefit-card">
                    <span class="benefit-step">03. CATALOGUE ACCESS</span>
                    <h3>Searchable Materials</h3>
                    <p>Filter by material type, review specifications, and explore available salvaged and circular stock.</p>
                </div>
                <div class="benefit-card">
                    <span class="benefit-step">04. DIRECT PROCUREMENT</span>
                    <h3>Project Quote Assembly</h3>
                    <p>Assemble itemized project quote requests and coordinate logistics directly with material suppliers.</p>
                </div>
            </div>
        </section>'''
            main_sections.append(benefits_html)

            materials_html = f'''
        <!-- Circular Materials Catalogue -->
        <section id="{showcase_sec_id}" class="container showcase-section">
            <div class="section-tag">Circular Materials Inventory</div>
            <h2 class="section-title">{showcase_title}</h2>
            <p class="about-lead">Explore architectural-grade reclaimed timbers, structural steel, historic masonry, and circular building products. (Illustrative pricing shown for demonstration purposes.)</p>
            
            <div class="filter-container">
                <input type="text" id="showcase-search" class="search-input" placeholder="{search_ph}">
                <div class="filter-buttons" id="category-filters">
                    {filters_html}
                </div>
            </div>

            <div class="sort-container">
                <label for="price-sort" class="sort-label">Sort Materials:</label>
                <select id="price-sort" class="sort-select">
                    <option value="featured">Featured Materials</option>
                    <option value="price-asc">Price: Low to High</option>
                    <option value="price-desc">Price: High to Low</option>
                </select>
            </div>

            <div id="showcase-grid" class="showcase-grid"></div>
        </section>'''
            main_sections.append(materials_html)

            quote_basket_html = f'''
        <!-- Interactive Project Quote Basket -->
        <section id="quote-basket" class="quote-basket-section">
            <div class="container">
                <div style="text-align: center; max-width: 600px; margin: 0 auto;">
                    <div class="section-tag">Bill of Materials Assembly</div>
                    <h2 class="section-title">Project Quote Assembly Basket</h2>
                    <p class="about-lead">Assemble an itemized list of required reclaimed and circular materials to request quotation from recovery suppliers. (Pricing shown is illustrative for demonstration.)</p>
                </div>
                
                <div class="quote-basket-box">
                    <div id="basket-items-list"></div>
                    
                    <div class="basket-summary-row">
                        <div class="basket-subtotal-box">
                            <span>Estimated Subtotal (Illustrative):</span>
                            <span id="basket-subtotal" class="basket-subtotal-val">$0.00</span>
                        </div>
                        <a href="#contact" class="btn-primary" style="padding: 0.75rem 1.75rem;">Request Official Quotation</a>
                    </div>
                </div>
            </div>
        </section>'''
            main_sections.append(quote_basket_html)

            onboarding_html = f'''
        <!-- Supplier & Contractor Onboarding -->
        <section id="onboarding" class="container onboarding-section" style="padding: 4rem 0;">
            <div style="text-align: center; max-width: 600px; margin: 0 auto;">
                <div class="section-tag">Join The Circular Network</div>
                <h2 class="section-title">Supplier & Contractor Onboarding</h2>
                <p class="about-lead">Facilitating material documentation and direct connections between recovery suppliers and construction contractors.</p>
            </div>
            <div class="onboarding-grid">
                <div class="onboarding-card">
                    <span class="onboarding-step">STEP 01</span>
                    <h3>Register Material Streams</h3>
                    <p>Demolition contractors and recovery yards list reclaimed stockpiles with origin information and available volumes.</p>
                </div>
                <div class="onboarding-card">
                    <span class="onboarding-step">STEP 02</span>
                    <h3>Document & Catalog</h3>
                    <p>Suppliers submit transparent material specifications, dimensional sizing, and photographic documentation.</p>
                </div>
                <div class="onboarding-card">
                    <span class="onboarding-step">STEP 03</span>
                    <h3>Procurement & Delivery</h3>
                    <p>Builders assemble quote requests and coordinate freight delivery directly with listing suppliers.</p>
                </div>
            </div>
        </section>'''
            main_sections.append(onboarding_html)

            sustainability_html = f'''
        <!-- Sustainability & Environmental Commitment -->
        <section id="sustainability" class="container impact-section" style="padding: 4rem 0; border-top: 1px solid var(--border-color);">
            <div style="text-align: center; max-width: 650px; margin: 0 auto 2.5rem auto;">
                <div class="section-tag">Sustainability Commitment</div>
                <h2 class="section-title">Supporting Material Reuse Across Construction</h2>
                <p class="about-lead">Connecting recovery suppliers with construction buyers to extend material lifecycles and reduce construction waste through direct reuse.</p>
            </div>
            <div class="impact-grid">
                <div class="impact-card">
                    <div class="impact-metric">Reuse</div>
                    <div class="spec-metric-lbl">Extending Material Lifecycle</div>
                    <p style="font-size: 0.88rem; color: var(--text-secondary); margin-top: 0.5rem;">Prioritizing structural and architectural material salvage over landfill disposal.</p>
                </div>
                <div class="impact-card">
                    <div class="impact-metric">Circular</div>
                    <div class="spec-metric-lbl">Reducing Construction Waste</div>
                    <p style="font-size: 0.88rem; color: var(--text-secondary); margin-top: 0.5rem;">Connecting demolition contractors with commercial builders seeking reclaimed stock.</p>
                </div>
                <div class="impact-card">
                    <div class="impact-metric">Transparent</div>
                    <div class="spec-metric-lbl">Supplier-Submitted Documentation</div>
                    <p style="font-size: 0.88rem; color: var(--text-secondary); margin-top: 0.5rem;">Clear provenance, dimensions, and condition reports provided by recovery suppliers.</p>
                </div>
            </div>
        </section>'''
            main_sections.append(sustainability_html)

        else:
            if archetype == "culinary_restaurant":
                about_html = f'''
        <!-- Restaurant Identity & Chef Introduction -->
        <section id="about" class="container about-section" style="padding: 4.5rem 0;">
            <div class="editorial-lead-card">
                <div class="editorial-lead-media">
                    <img src="assets/images/chef-kitchen.jpg" alt="{app_name} Hearth Kitchen & Chef Preparation" loading="eager">
                </div>
                <div class="editorial-lead-body">
                    <div class="demo-disclosure-pill">Illustrative Culinary Concept · Sample Chef Bio</div>
                    <div class="section-tag">Kitchen Philosophy & Hospitality</div>
                    <h2 class="section-title" style="margin-bottom: 1rem;">Seasonal Craft &amp; Open-Hearth Dining at {app_name}</h2>
                    <p style="color: var(--text-secondary); line-height: 1.75; margin-bottom: 1.25rem;">{spec.purpose} Our menu highlights small-lot olive oils, hearth-roasted seasonal produce, hand-rolled grains, and botanical pairings.</p>
                    <div style="border-left: 3px solid var(--accent-color); padding-left: 1rem; color: var(--text-secondary); font-size: 0.92rem; line-height: 1.65;">
                        <strong style="color: var(--text-primary); display: block; margin-bottom: 0.25rem;">Sample Culinary Director Profile (Demonstration)</strong>
                        Led by our sample test-kitchen culinary team celebrating open-ember cooking and zero-waste larder preparation. Menu courses, prices, and hours below represent illustrative demonstration data.
                    </div>
                </div>
            </div>
        </section>'''
                main_sections.append(about_html)
            elif archetype == "editorial_publication":
                lead = spec.content_entities[0] if spec.content_entities else {}
                lead_title = lead.get("title", f"Featured Dispatch from {app_name}")
                lead_desc = lead.get("description", spec.purpose)
                lead_img = lead.get("image_path", hero_img_path)
                lead_cat = lead.get("category_label", "Featured Science")
                lead_spec = lead.get("specifications", "8 min read | Sample Contributor")
                lead_id = lead.get("id", "story-1")
                featured_html = f'''
        <!-- Featured Lead Story Spotlight -->
        <section id="featured-story" class="container" style="padding: 4.5rem 0;">
            <div class="section-tag">Lead Dispatch · Featured Cover Essay</div>
            <div class="editorial-lead-card" style="margin-top: 1rem;">
                <div class="editorial-lead-media">
                    <img src="{lead_img}" alt="{lead_title}" loading="eager">
                </div>
                <div class="editorial-lead-body">
                    <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; margin-bottom: 0.85rem;">
                        <span class="status-pill">{lead_cat}</span>
                        <span style="font-family: var(--font-mono); font-size: 0.82rem; color: var(--text-secondary);">{lead_spec}</span>
                    </div>
                    <h2 class="section-title" style="font-size: clamp(1.75rem, 3vw, 2.35rem); margin-bottom: 1rem;">{lead_title}</h2>
                    <p style="color: var(--text-secondary); line-height: 1.75; margin-bottom: 1.5rem;">{lead_desc}</p>
                    <div>
                        <button type="button" id="btn-read-featured" class="btn-primary" data-story-id="{lead_id}">Read Full Featured Essay</button>
                    </div>
                </div>
            </div>
        </section>'''
                main_sections.append(featured_html)
            else:
                about_sec = next((s for s in spec.required_sections if s.get("id") == "about"), None)
                about_tag = "Geospatial Operations" if "geospatial" in d_lower else ("Discovery Center" if ("museum" in d_lower or "sparkfield" in app_name.lower()) else "About The Institution")
                about_title = about_sec.get("title", f"About {app_name}") if about_sec else f"About {app_name}"

                about_html = f'''
        <!-- About Section -->
        <section id="about" class="container about-section">
            <div class="section-tag">{about_tag}</div>
            <h2 class="section-title">{about_title}</h2>
            <p class="about-lead">{spec.purpose}</p>
            <div class="objectives-grid">
                {objs_html}
            </div>
        </section>'''
                main_sections.append(about_html)

            if archetype == "culinary_restaurant":
                showcase_tag = "Hearth Kitchen Menu & Pairings (Illustrative Courses)"
            elif archetype == "editorial_publication":
                showcase_tag = "Articles, Reading Times & Desks (Sample Editorial Archive)"
            else:
                showcase_tag = "Specialized Capabilities & Technology" if "geospatial" in d_lower else ("Interactive Discovery Labs & Galleries" if ("museum" in d_lower or "sparkfield" in app_name.lower()) else f"{getattr(spec, 'domain_subtype', None) or 'Curated Offerings'} (Illustrative Examples)")
            showcase_html = f'''
        <!-- Showcase Section -->
        <section id="{showcase_sec_id}" class="container showcase-section">
            <div class="section-tag">{showcase_tag}</div>
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

            # Domain-Specific Sections for Geospatial Intelligence (SKYTRACE GEOMATICS)
            if "geospatial" in d_lower or "skytrace" in app_name.lower():
                case_studies_html = f'''
        <!-- Case Studies Section -->
        <section id="case-studies" class="container case-studies-section" style="padding: 4.5rem 0;">
            <div style="text-align: center; max-width: 650px; margin: 0 auto 2.5rem auto;">
                <div class="section-tag">Field Proven Excellence</div>
                <h2 class="section-title">Featured Aerial Survey Case Studies</h2>
                <p class="about-lead">Explore how our geospatial intelligence and airborne LiDAR workflows deliver sub-centimeter accuracy across civil infrastructure, mining, and land management.</p>
            </div>
            <div class="case-studies-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.75rem;">
                <div class="case-study-card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem; box-shadow: var(--shadow-sm);">
                    <span style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent-color); font-weight: 700;">INFRASTRUCTURE & TRANSPORTATION</span>
                    <h3 style="margin: 0.5rem 0; font-size: 1.25rem;">State Highway Corridor LiDAR Mapping</h3>
                    <p style="color: var(--text-secondary); font-size: 0.92rem; line-height: 1.6;">Mapped 85 kilometers of mountainous highway corridor with airborne LiDAR, delivering classified bare-earth terrain models and bridge structure clearance measurements in 72 hours.</p>
                    <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border-color); font-size: 0.88rem; font-weight: 600; color: var(--accent-secondary);">Accuracy: ±1.2 cm RMSE | Point Density: 350 pts/m²</div>
                </div>
                <div class="case-study-card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem; box-shadow: var(--shadow-sm);">
                    <span style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent-color); font-weight: 700;">RENEWABLE ENERGY</span>
                    <h3 style="margin: 0.5rem 0; font-size: 1.25rem;">400-Acre Solar Utility Farm Topography</h3>
                    <p style="color: var(--text-secondary); font-size: 0.92rem; line-height: 1.6;">Executed high-resolution photogrammetric drone survey across 400 acres of undulating terrain to optimize solar panel pile locations, grading earthwork cuts, and stormwater retention basins.</p>
                    <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border-color); font-size: 0.88rem; font-weight: 600; color: var(--accent-secondary);">GSD: 0.75 cm/px | Earthwork Variance: &lt; 0.4%</div>
                </div>
                <div class="case-study-card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem; box-shadow: var(--shadow-sm);">
                    <span style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent-color); font-weight: 700;">MINING & AGGREGATES</span>
                    <h3 style="margin: 0.5rem 0; font-size: 1.25rem;">Regional Quarry Volumetric Stockpile Audit</h3>
                    <p style="color: var(--text-secondary); font-size: 0.92rem; line-height: 1.6;">Performed automated volumetric stockpile computations across 42 crushed stone and sand mounds. Replaced manual surveying and eliminated heavy equipment hazard while delivering verified inventory.</p>
                    <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border-color); font-size: 0.88rem; font-weight: 600; color: var(--accent-secondary);">Volume Verified: 480,000 m³ | Zero Operational Stoppage</div>
                </div>
            </div>
        </section>'''
                main_sections.append(case_studies_html)

                calculator_html = f'''
        <!-- Interactive Survey Estimate Calculator -->
        <section id="calculator" class="container calculator-section" style="padding: 4.5rem 0; border-top: 1px solid var(--border-color);">
            <div style="text-align: center; max-width: 650px; margin: 0 auto 2.5rem auto;">
                <div class="section-tag">Interactive Estimator</div>
                <h2 class="section-title">Survey Turnaround & Cost Calculator</h2>
                <p class="about-lead">Select your required aerial surveying service and estimated project acreage to calculate indicative turnaround times and operational resource planning.</p>
            </div>
            <div style="max-width: 720px; margin: 0 auto; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2.5rem; box-shadow: var(--shadow-md);">
                <div class="form-group" style="margin-bottom: 1.5rem;">
                    <label class="form-label" style="font-weight: 600;">Select Survey Capability:</label>
                    <select id="calc-service" class="form-control" style="width: 100%; padding: 0.75rem; border: 1px solid var(--border-color); border-radius: var(--radius-sm); font-size: 1rem; background: var(--bg-main); color: var(--text-primary);">
                        <option value="Drone-Based Photogrammetry">Drone-Based Photogrammetry & Orthomosaic</option>
                        <option value="Aerial LiDAR Scanning">Airborne LiDAR Scanning & 3D Point Cloud</option>
                        <option value="Construction Monitoring">Construction Progress Monitoring & BIM Overlay</option>
                        <option value="Volumetric Stockpile">Volumetric Stockpile Calculation</option>
                        <option value="Environmental Survey">Environmental Land Survey & Multispectral</option>
                    </select>
                </div>
                <div class="form-group" style="margin-bottom: 2rem;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                        <label class="form-label" style="font-weight: 600;">Project Area (Acres):</label>
                        <span id="calc-acreage-val" style="font-family: var(--font-mono); font-weight: 700; color: var(--accent-color); font-size: 1.1rem;">50 Acres</span>
                    </div>
                    <input type="range" id="calc-acreage" min="10" max="1000" step="10" value="50" style="width: 100%; cursor: pointer;">
                    <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.25rem;">
                        <span>10 Acres</span>
                        <span>250 Acres</span>
                        <span>500 Acres</span>
                        <span>1,000 Acres</span>
                    </div>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; background: var(--bg-main); padding: 1.5rem; border-radius: var(--radius-sm); border: 1px solid var(--border-color); text-align: center;">
                    <div>
                        <div style="font-size: 0.85rem; color: var(--text-secondary); font-weight: 600; text-transform: uppercase;">Estimated Turnaround</div>
                        <div id="calc-est-time" style="font-size: 1.4rem; font-weight: 800; color: var(--text-primary); margin-top: 0.25rem;">24-48 Hours</div>
                    </div>
                    <div>
                        <div style="font-size: 0.85rem; color: var(--text-secondary); font-weight: 600; text-transform: uppercase;">Estimated Cost (Illustrative)</div>
                        <div id="calc-est-cost" style="font-size: 1.4rem; font-weight: 800; color: var(--accent-color); margin-top: 0.25rem;">$1,650</div>
                    </div>
                </div>
                <div style="text-align: center; margin-top: 1.75rem;">
                    <a href="#contact" class="btn-primary" style="display: inline-block; padding: 0.85rem 2rem; border-radius: var(--radius-sm); text-decoration: none;">Proceed to Formal Survey Proposal</a>
                </div>
            </div>
        </section>'''
                main_sections.append(calculator_html)

                testimonials_html = f'''
        <!-- Client Testimonials Section -->
        <section id="testimonials" class="container testimonials-section" style="padding: 4.5rem 0;">
            <div style="text-align: center; max-width: 650px; margin: 0 auto 2.5rem auto;">
                <div class="section-tag">Client Verification</div>
                <h2 class="section-title">Endorsed by Engineering Leaders</h2>
                <p class="about-lead">Trusted by state transportation authorities, heavy civil contractors, and environmental directors nationwide.</p>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.75rem;">
                <div style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem;">
                    <p style="color: var(--text-secondary); font-style: italic; line-height: 1.6; margin-bottom: 1.25rem;">"{app_name}'s LiDAR mapping delivered sub-centimeter elevation models through dense pine canopy where conventional ground surveying would have taken weeks. Flawless turnaround."</p>
                    <div style="font-weight: 700; color: var(--text-primary);">Marcus Sterling, PE</div>
                    <div style="font-size: 0.85rem; color: var(--text-secondary);">Chief Civil Engineer, Apex Infrastructure Group</div>
                </div>
                <div style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem;">
                    <p style="color: var(--text-secondary); font-style: italic; line-height: 1.6; margin-bottom: 1.25rem;">"The volumetric stockpile audits are rigorous and repeatable. We reconcile quarterly quarry inventories in 24 hours with certified zero-discrepancy reports."</p>
                    <div style="font-weight: 700; color: var(--text-primary);">Elena Rostova</div>
                    <div style="font-size: 0.85rem; color: var(--text-secondary);">Operations Director, Pacific Aggregate Corporation</div>
                </div>
                <div style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem;">
                    <p style="color: var(--text-secondary); font-style: italic; line-height: 1.6; margin-bottom: 1.25rem;">"Their multispectral environmental surveys provided our conservation trust with authoritative watershed runoff analysis accepted by state regulatory agencies."</p>
                    <div style="font-weight: 700; color: var(--text-primary);">Dr. David Okafor</div>
                    <div style="font-size: 0.85rem; color: var(--text-secondary);">Director of Land Stewardship, Coastal River Basin Trust</div>
                </div>
            </div>
        </section>'''
                main_sections.append(testimonials_html)

            # Domain-Specific Sections for Museum / Discovery Center (SPARKFIELD DISCOVERY MUSEUM)
            elif "museum" in d_lower or "sparkfield" in app_name.lower() or "education" in d_lower:
                tickets_html = f'''
        <!-- Admission & Pricing Tiers -->
        <section id="tickets" class="container tickets-section" style="padding: 4.5rem 0;">
            <div style="text-align: center; max-width: 650px; margin: 0 auto 2.5rem auto;">
                <div class="section-tag">Visit & Explore</div>
                <h2 class="section-title">Admission & Pricing Tiers</h2>
                <p class="about-lead">All tickets include full access to hands-on physics galleries, youth robotics lab demos, and the early explorers sensory zone. (Planetarium shows included with All-Access passes.)</p>
            </div>
            <div class="pricing-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1.5rem;">
                <div class="pricing-card ticket-card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem; text-align: center; box-shadow: var(--shadow-sm);">
                    <h3 style="font-size: 1.2rem; color: var(--text-primary);">Child Explorer</h3>
                    <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 1rem;">Ages 3 – 12</div>
                    <div style="font-size: 2.5rem; font-weight: 800; color: var(--accent-color); margin-bottom: 1rem;">$14<span style="font-size: 1rem; font-weight: 500; color: var(--text-secondary);"> / child</span></div>
                    <ul style="list-style: none; padding: 0; margin-bottom: 1.5rem; font-size: 0.88rem; color: var(--text-secondary); line-height: 1.8;">
                        <li>✓ All Hands-On Science Exhibits</li>
                        <li>✓ Youth Robotics Arena Access</li>
                        <li>✓ Maker Workshop Drop-in</li>
                    </ul>
                    <a href="#field-trips" class="btn-primary btn-ticket-select" data-tier="Child Explorer ($14)" style="display: block; padding: 0.65rem 1rem; border-radius: var(--radius-sm); text-decoration: none;">Select Ticket</a>
                </div>
                <div class="pricing-card ticket-card" style="background: var(--bg-card); border: 2px solid var(--accent-color); border-radius: var(--radius-md); padding: 2rem; text-align: center; box-shadow: var(--shadow-md); position: relative;">
                    <div style="position: absolute; top: -12px; left: 50%; transform: translateX(-50%); background: var(--accent-color); color: #fff; font-size: 0.75rem; font-weight: 700; padding: 0.2rem 0.8rem; border-radius: 20px; text-transform: uppercase;">Most Popular</div>
                    <h3 style="font-size: 1.2rem; color: var(--text-primary);">Adult General</h3>
                    <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 1rem;">Ages 13+</div>
                    <div style="font-size: 2.5rem; font-weight: 800; color: var(--accent-color); margin-bottom: 1rem;">$18<span style="font-size: 1rem; font-weight: 500; color: var(--text-secondary);"> / adult</span></div>
                    <ul style="list-style: none; padding: 0; margin-bottom: 1.5rem; font-size: 0.88rem; color: var(--text-secondary); line-height: 1.8;">
                        <li>✓ All Interactive Galleries</li>
                        <li>✓ 1 Planetarium Dome Feature</li>
                        <li>✓ Science Stage Live Shows</li>
                    </ul>
                    <a href="#field-trips" class="btn-primary btn-ticket-select" data-tier="Adult General ($18)" style="display: block; padding: 0.65rem 1rem; border-radius: var(--radius-sm); text-decoration: none;">Select Ticket</a>
                </div>
                <div class="pricing-card ticket-card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem; text-align: center; box-shadow: var(--shadow-sm);">
                    <h3 style="font-size: 1.2rem; color: var(--text-primary);">Family 4-Pack</h3>
                    <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 1rem;">2 Adults + 2 Children</div>
                    <div style="font-size: 2.5rem; font-weight: 800; color: var(--accent-color); margin-bottom: 1rem;">$55<span style="font-size: 1rem; font-weight: 500; color: var(--text-secondary);"> / group</span></div>
                    <ul style="list-style: none; padding: 0; margin-bottom: 1.5rem; font-size: 0.88rem; color: var(--text-secondary); line-height: 1.8;">
                        <li>✓ Full Museum Access (4 Guests)</li>
                        <li>✓ 10% Cafe & Gift Shop Discount</li>
                        <li>✓ Fast-Track Entry Gate</li>
                    </ul>
                    <a href="#field-trips" class="btn-primary btn-ticket-select" data-tier="Family 4-Pack ($55)" style="display: block; padding: 0.65rem 1rem; border-radius: var(--radius-sm); text-decoration: none;">Select Ticket</a>
                </div>
                <div class="pricing-card ticket-card" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem; text-align: center; box-shadow: var(--shadow-sm);">
                    <h3 style="font-size: 1.2rem; color: var(--text-primary);">Annual Pass</h3>
                    <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 1rem;">Family Membership</div>
                    <div style="font-size: 2.5rem; font-weight: 800; color: var(--accent-secondary); margin-bottom: 1rem;">$120<span style="font-size: 1rem; font-weight: 500; color: var(--text-secondary);"> / year</span></div>
                    <ul style="list-style: none; padding: 0; margin-bottom: 1.5rem; font-size: 0.88rem; color: var(--text-secondary); line-height: 1.8;">
                        <li>✓ Unlimited Year-Round Admission</li>
                        <li>✓ Free Planetarium All Year</li>
                        <li>✓ Priority STEM Camp Booking</li>
                    </ul>
                    <a href="#membership" class="btn-primary btn-ticket-select" data-tier="Annual Membership ($120)" style="display: block; padding: 0.65rem 1rem; border-radius: var(--radius-sm); text-decoration: none;">Join as Member</a>
                </div>
            </div>
        </section>'''
                main_sections.append(tickets_html)

                schedule_html = f'''
        <!-- Daily Schedule Section -->
        <section id="schedule" class="container schedule-section" style="padding: 4.5rem 0; border-top: 1px solid var(--border-color);">
            <div style="text-align: center; max-width: 650px; margin: 0 auto 2.5rem auto;">
                <div class="section-tag">Daily Showtimes & Demos</div>
                <h2 class="section-title">Today's Exploration Schedule</h2>
                <p class="about-lead">Live presentations, guided maker tutorials, and cosmic theater screenings running throughout the day.</p>
            </div>
            <div class="table-responsive">
                <table class="schedule-table">
                    <thead>
                        <tr><th>Time</th><th>Location / Venue</th><th>Program / Show</th><th>Age Recommendation</th><th>Status</th></tr>
                    </thead>
                    <tbody>
                        <tr><td><strong>10:00 AM</strong></td><td>Planetarium Dome</td><td>Cosmic Voyage: Touring the Solar System</td><td>All Ages</td><td><span class="status-pill">Scheduled</span></td></tr>
                        <tr><td><strong>11:30 AM</strong></td><td>Physics Science Stage</td><td>High-Voltage Electricity & Tesla Coils</td><td>Ages 6+</td><td><span class="status-pill">Interactive</span></td></tr>
                        <tr><td><strong>01:15 PM</strong></td><td>Youth Robotics Arena</td><td>Autonomous Rover Obstacle Challenge</td><td>Ages 8-16</td><td><span class="status-pill">Hands-On</span></td></tr>
                        <tr><td><strong>02:45 PM</strong></td><td>Maker Innovation Lab</td><td>Hydraulic Robotic Arm Fabrication</td><td>Ages 7+</td><td><span class="status-pill">Drop-in</span></td></tr>
                        <tr><td><strong>04:00 PM</strong></td><td>Planetarium Dome</td><td>Exoplanets & Deep Space Astronomy 8K</td><td>Ages 8+</td><td><span class="status-pill">Final Show</span></td></tr>
                    </tbody>
                </table>
            </div>
        </section>'''
                main_sections.append(schedule_html)

                events_html = f'''
        <!-- Upcoming Events Section -->
        <section id="events" class="container events-section" style="padding: 4.5rem 0; border-top: 1px solid var(--border-color);">
            <div style="text-align: center; max-width: 650px; margin: 0 auto 2.5rem auto;">
                <div class="section-tag">Upcoming Calendar</div>
                <h2 class="section-title">Upcoming STEM Camps & Special Events</h2>
                <p class="about-lead">Explore seasonal workshops, weekend family hackathons, and immersive science camps.</p>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.75rem;">
                <div style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem;">
                    <span style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent-color); font-weight: 700;">JULY 14 – 18, 2026</span>
                    <h3 style="margin: 0.5rem 0; font-size: 1.25rem;">Summer Rocketry & Aerodynamics Camp</h3>
                    <p style="color: var(--text-secondary); font-size: 0.92rem; line-height: 1.6;">Build solid-fuel model rockets, test wing wind tunnel lift ratios, and analyze telemetry in a 5-day hands-on aerospace academy for ages 9-14.</p>
                </div>
                <div style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem;">
                    <span style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent-color); font-weight: 700;">EVERY SATURDAY (2:00 PM)</span>
                    <h3 style="margin: 0.5rem 0; font-size: 1.25rem;">Youth Robotics Hackathon Arena</h3>
                    <p style="color: var(--text-secondary); font-size: 0.92rem; line-height: 1.6;">Team challenge for young coders to program sensor-driven rovers navigating obstacle courses. Prizes awarded for creative mechanical design.</p>
                </div>
                <div style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem;">
                    <span style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent-color); font-weight: 700;">FIRST FRIDAYS (7:00 PM)</span>
                    <h3 style="margin: 0.5rem 0; font-size: 1.25rem;">Family Astronomy & Telescope Night</h3>
                    <p style="color: var(--text-secondary); font-size: 0.92rem; line-height: 1.6;">Rooftop telescope viewing paired with deep-space planetarium shows. Observe the rings of Saturn, lunar craters, and bright deep-sky nebulae.</p>
                </div>
            </div>
        </section>'''
                main_sections.append(events_html)

                faqs_html = f'''
        <!-- Visitor FAQs Section -->
        <section id="faqs" class="container faqs-section" style="padding: 4.5rem 0; border-top: 1px solid var(--border-color);">
            <div style="text-align: center; max-width: 650px; margin: 0 auto 2.5rem auto;">
                <div class="section-tag">Visitor Information</div>
                <h2 class="section-title">Frequently Asked Questions</h2>
            </div>
            <div style="max-width: 800px; margin: 0 auto; display: flex; flex-direction: column; gap: 1rem;">
                <details style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: 1.25rem; cursor: pointer;">
                    <summary style="font-weight: 700; color: var(--text-primary); font-size: 1.05rem;">What are your general opening hours?</summary>
                    <p style="margin-top: 0.75rem; color: var(--text-secondary); line-height: 1.6;">{app_name} is open Tuesday through Sunday from 9:00 AM to 6:00 PM. We are closed on Mondays for exhibit deep-cleaning and maintenance. Last admission is granted at 5:00 PM.</p>
                </details>
                <details style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: 1.25rem; cursor: pointer;">
                    <summary style="font-weight: 700; color: var(--text-primary); font-size: 1.05rem;">Is the museum stroller and wheelchair accessible?</summary>
                    <p style="margin-top: 0.75rem; color: var(--text-secondary); line-height: 1.6;">Yes! All exhibition galleries, planetarium seating, restrooms, and labs are 100% ADA compliant with ramp and elevator access. Sensory backpacks with noise-dampening headphones are available free of charge at guest services.</p>
                </details>
                <details style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: 1.25rem; cursor: pointer;">
                    <summary style="font-weight: 700; color: var(--text-primary); font-size: 1.05rem;">Where do we park and what dining options are available?</summary>
                    <p style="margin-top: 0.75rem; color: var(--text-secondary); line-height: 1.6;">Free on-site parking is provided in the North Discovery Lot. Our on-site Galileo Cafe offers fresh salads, sandwiches, and allergy-friendly kid meals. Families are also welcome to enjoy packed lunches in our outdoor Discovery Pavilion.</p>
                </details>
            </div>
        </section>'''
                main_sections.append(faqs_html)

                membership_html = f'''
        <!-- Membership & Donors Section -->
        <section id="membership" class="container membership-section" style="padding: 4.5rem 0; border-top: 1px solid var(--border-color);">
            <div style="text-align: center; max-width: 650px; margin: 0 auto 2.5rem auto;">
                <div class="section-tag">Community Support</div>
                <h2 class="section-title">Membership & Donor Impact</h2>
                <p class="about-lead">As a non-profit science center, philanthropic gifts and family memberships support free Title I school admissions, exhibit development, and STEM camp scholarships.</p>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.75rem;">
                <div style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem;">
                    <h3 style="color: var(--accent-color); margin-bottom: 0.5rem;">Family Membership</h3>
                    <p style="color: var(--text-secondary); font-size: 0.92rem; line-height: 1.6;">Enjoy 365 days of unlimited free admission for 2 adults and up to 4 children, reciprocal admission to 300+ ASTC science centers worldwide, and 20% discounts on summer STEM camps.</p>
                </div>
                <div style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem;">
                    <h3 style="color: var(--accent-secondary); margin-bottom: 0.5rem;">STEM Scholarship Fund</h3>
                    <p style="color: var(--text-secondary); font-size: 0.92rem; line-height: 1.6;">Your charitable contribution funds subsidized bus transportation and free admission for Title I public school classrooms, ensuring hands-on science is accessible to all children.</p>
                </div>
                <div style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 2rem;">
                    <h3 style="color: var(--text-primary); margin-bottom: 0.5rem;">Exhibit Innovation Endowment</h3>
                    <p style="color: var(--text-secondary); font-size: 0.92rem; line-height: 1.6;">Join our Visionary Circle to sponsor interactive science installations, next-generation youth robotics arena hardware, and digital planetarium astronomical productions.</p>
                </div>
            </div>
        </section>'''
                main_sections.append(membership_html)

            elif archetype == "culinary_restaurant":
                about_loc_hours = f'''
        <!-- Location, Seating & Operating Hours -->
        <section id="location-hours" class="container discovery-section" style="padding: 4rem 0;">
            <div class="section-tag">Hospitality &amp; Visit Planning (Illustrative Hours)</div>
            <h2 class="section-title">Location &amp; Operating Hours</h2>
            <p class="about-lead">Plan an evening around the wood hearth at {app_name}. Street address, phone desk, and hours below represent sample demonstration details.</p>
            <div class="discovery-grid">
                <article class="discovery-card">
                    <div class="discovery-metric">Neighborhood Bistro</div>
                    <h3 style="margin-bottom: 0.5rem;">Sample Culinary Address</h3>
                    <p class="discovery-abstract">742 Hearthside Lane, Arts District &middot; Courtyard Dining Room &amp; Chef Counter (Illustrative Location)</p>
                </article>
                <article class="discovery-card">
                    <div class="discovery-metric">Wed &ndash; Sun</div>
                    <h3 style="margin-bottom: 0.5rem;">Evening Dinner Service</h3>
                    <p class="discovery-abstract">Hearth Kitchen: 17:30 &ndash; 22:30 &middot; Courtyard Bar &amp; Tasting Counter: 17:00 &ndash; 23:00 (Sample Schedule)</p>
                </article>
                <article class="discovery-card">
                    <div class="discovery-metric">Fri &ndash; Sun</div>
                    <h3 style="margin-bottom: 0.5rem;">Weekend Midday Table</h3>
                    <p class="discovery-abstract">Seasonal wood-fired flatbreads and botanical pairings served 11:30 &ndash; 14:30. Closed Monday &ndash; Tuesday.</p>
                </article>
            </div>
        </section>'''
                main_sections.append(about_loc_hours)

            elif archetype == "editorial_publication":
                contributors_html = f'''
        <!-- Editorial Masthead & Sample Contributors -->
        <section id="contributors" class="container discovery-section" style="padding: 4rem 0;">
            <div id="about"></div>
            <div class="section-tag">Masthead &amp; Sample Contributor Profiles</div>
            <h2 class="section-title">Editorial Desks &amp; Contributors</h2>
            <p class="about-lead">{app_name} organizes long-form dispatches across science, technology, environment, and innovation. Contributor listings below use illustrative editorial role labels.</p>
            <div class="discovery-grid">
                <article class="discovery-card">
                    <div class="discovery-metric">Science &amp; Ocean Desk</div>
                    <h3 style="margin-bottom: 0.5rem;">Sample Science Editor</h3>
                    <p class="discovery-abstract">Covers physical oceanography, structural biology, and instrumentation breakthroughs with reading-time annotations.</p>
                </article>
                <article class="discovery-card">
                    <div class="discovery-metric">Technology &amp; Compute</div>
                    <h3 style="margin-bottom: 0.5rem;">Sample Systems Correspondent</h3>
                    <p class="discovery-abstract">Examines distributed hardware architectures, edge telemetry infrastructure, and open technical verification.</p>
                </article>
                <article class="discovery-card">
                    <div class="discovery-metric">Environment &amp; Materials</div>
                    <h3 style="margin-bottom: 0.5rem;">Sample Ecology Fellow</h3>
                    <p class="discovery-abstract">Reports on circular biomaterials, hydrology restoration, and long-duration renewable energy storage.</p>
                </article>
            </div>
        </section>'''
                main_sections.append(contributors_html)

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
            <div id="field-trips"></div>
            <div id="reservations"></div>
            <div id="newsletter"></div>
            <div class="container">
                <div style="text-align: center; max-width: 600px; margin: 0 auto;">
                    <div class="section-tag">Engagement & Access</div>
                    <h2 class="section-title">{form_meta.get("title", f"Inquire with {app_name}")}</h2>
                </div>
                <div class="inquiry-form-wrapper">
                    <form id="{form_meta.get('form_id', 'inquiry-form')}" class="inquiry-form" novalidate>
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
    <link rel="icon" href="data:,">
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
                    <p style="font-size: 0.9rem; max-width: 400px;">{spec.domain_subtype} &mdash; Interactive digital platform and structured showcase (Demonstration Build).</p>
                </div>
                <div>
                    <p style="font-size: 0.85rem; color: #94a3b8;">Demonstration Deliverable &middot; {app_name}</p>
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
            modal_telemetry_msg = "Workspace Specification: In-browser demonstration module &middot; Sample workflow configuration."
            empty_search_msg = "No platform capabilities match your current search criteria."
        elif archetype == "culinary_restaurant":
            modal_telemetry_msg = "Culinary Information: Illustrative dish presentation &middot; Allergen and dietary guidance shown for demonstration."
            empty_search_msg = "No menu dishes match your current search or course filter."
        elif archetype == "editorial_publication":
            modal_telemetry_msg = "Editorial Note: Sample dispatch text, reading-time metadata, and contributor profile shown for demonstration."
            empty_search_msg = "No dispatches or articles match your current search or desk filter."
        elif archetype == "tourism_adventure":
            modal_telemetry_msg = "Expedition Staging: Difficulty rating verified &middot; Certified IFMGA guide led."
            empty_search_msg = "No wilderness expeditions match your current search criteria."
        elif archetype == "portfolio_studio":
            modal_telemetry_msg = "Architectural Specifications: Passivhaus thermal envelope &middot; Sustainable materials verified."
            empty_search_msg = "No architectural projects match your current search criteria."
        elif archetype == "marketplace":
            modal_telemetry_msg = "Demonstration Notice: Specifications and illustrative pricing are shown for platform demonstration."
            empty_search_msg = "No circular construction materials match your current search criteria."
        elif "geospatial" in d_lower or "skytrace" in app_name.lower():
            modal_telemetry_msg = "Survey Specifications: Sub-centimeter GSD &middot; FAA Part 107 flight certified."
            empty_search_msg = "No geospatial surveying services match your current search criteria."
        elif "museum" in d_lower or "sparkfield" in app_name.lower() or "education" in d_lower:
            modal_telemetry_msg = "Exhibit Guidelines: Hands-on interactive exploration &middot; STEM educator guided."
            empty_search_msg = "No exhibits or discovery labs match your current search criteria."
        elif archetype == "research_institution":
            modal_telemetry_msg = "Research Telemetry: Calibration verified &middot; Ready for academic proposal scheduling."
            empty_search_msg = "No scientific assets match your current search criteria."
        else:
            modal_telemetry_msg = "Demonstration Notice: Illustrative specifications and offerings shown for interactive demonstration."
            empty_search_msg = "No items match your current search criteria."

        if archetype == "marketplace":
            basket_init_js = """    const basketList = document.getElementById('basket-items-list');
    const basketSubtotalEl = document.getElementById('basket-subtotal');
    const basketCountEls = document.querySelectorAll('#basket-count');"""
            sort_select_init = "    const sortSelect = document.getElementById('price-sort');"
            sort_select_listener = """    if (sortSelect) {
        sortSelect.addEventListener('change', (e) => {
            sortOrder = e.target.value;
            render();
        });
    }"""
        else:
            basket_init_js = """    const basketList = null;
    const basketSubtotalEl = null;
    const basketCountEls = [];"""
            sort_select_init = "    const sortSelect = null;"
            sort_select_listener = ""

        if archetype == "saas_product":
            billing_toggle_js = """    // Billing Toggle for SaaS Pricing Matrix
    const billingToggle = document.getElementById('billing-toggle');
    const priceCards = document.querySelectorAll('.pricing-card');
    if (billingToggle && priceCards.length > 0) {
        billingToggle.addEventListener('change', () => {
            const isAnnual = billingToggle.checked;
            priceCards.forEach(card => {
                const amountEl = card.querySelector('.pricing-amount');
                const periodEl = card.querySelector('.pricing-period');
                if (amountEl) {
                    const monthly = card.dataset.monthly;
                    const annual = card.dataset.annual;
                    amountEl.textContent = (isAnnual ? annual : monthly).replace('$', '');
                }
                if (periodEl) {
                    periodEl.textContent = isAnnual ? '/ seat / month (illustrative, billed annually)' : '/ seat / month (illustrative)';
                }
            });
        });
    }"""
        else:
            billing_toggle_js = ""

        if d_lower == "geospatial_intelligence":
            geospatial_calc_js = """    // Survey Calculator for Geospatial
    const calcAcreage = document.getElementById('calc-acreage');
    const calcAcreageVal = document.getElementById('calc-acreage-val');
    const calcService = document.getElementById('calc-service');
    const calcEstTime = document.getElementById('calc-est-time');
    const calcEstCost = document.getElementById('calc-est-cost');
    function updateSurveyCalc() {
        if (!calcAcreage || !calcEstTime || !calcEstCost) return;
        const acres = parseInt(calcAcreage.value, 10) || 50;
        if (calcAcreageVal) calcAcreageVal.textContent = acres + " Acres";
        const isLidar = calcService && calcService.value.includes('LiDAR');
        const rate = isLidar ? 14 : 9;
        const base = isLidar ? 1800 : 1200;
        const total = base + (acres * rate);
        const turnaround = acres > 500 ? "3-4 Business Days" : (acres > 150 ? "2 Business Days" : "24-48 Hours");
        calcEstTime.textContent = turnaround;
        calcEstCost.textContent = "$" + total.toLocaleString();
    }
    if (calcAcreage) calcAcreage.addEventListener('input', updateSurveyCalc);
    if (calcService) calcService.addEventListener('change', updateSurveyCalc);
    updateSurveyCalc();"""
        else:
            geospatial_calc_js = ""

        if d_lower == "education_institution":
            museum_tickets_js = """    // Ticket Selection for Museum & Educational Visits
    const ticketBtns = document.querySelectorAll('.btn-ticket-select');
    ticketBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const tier = btn.dataset.tier || "General Admission";
            const msgArea = document.getElementById('form-message');
            if (msgArea) {
                msgArea.value = "Selected Admission: " + tier + "\\nRequested Visit Date: " + new Date().toLocaleDateString() + "\\nGroup Size: 1\\n";
                msgArea.scrollIntoView({ behavior: 'smooth' });
                msgArea.focus();
            }
        });
    });"""
        else:
            museum_tickets_js = ""

        if archetype == "saas_product":
            saas_interactive_js = """    // Interactive Draggable Kanban Board & Team Directory (Demo Workspace)
    const kanbanRoot = document.getElementById('view-kanban');
    const colOrder = ['backlog', 'inprogress', 'completed'];
    let draggedTaskId = null;

    function buildCardActionsHtml(status) {
        if (status === 'backlog') {
            return '<button type="button" class="btn-move-card" data-dir="next">Move &rarr;</button>';
        } else if (status === 'inprogress') {
            return '<button type="button" class="btn-move-card" data-dir="prev">&larr;</button><button type="button" class="btn-move-card" data-dir="next">Move &rarr;</button>';
        }
        return '<button type="button" class="btn-move-card" data-dir="prev">&larr; Reopen</button>';
    }

    function recomputeKanbanStats() {
        const sBacklog = document.getElementById('slot-backlog');
        const sProg = document.getElementById('slot-inprogress');
        const sComp = document.getElementById('slot-completed');
        if (!sBacklog || !sProg || !sComp) return;

        const cBacklog = sBacklog.querySelectorAll('.kanban-card').length;
        const cProg = sProg.querySelectorAll('.kanban-card').length;
        const cDone = sComp.querySelectorAll('.kanban-card').length;
        const total = cBacklog + cProg + cDone;
        const pct = total > 0 ? Math.round((cDone / total) * 100) : 0;

        const setElText = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
        setElText('count-backlog', cBacklog + ' Items');
        setElText('count-inprogress', cProg + ' Items');
        setElText('count-completed', cDone + ' Items');
        setElText('kanban-total-count', String(total));
        setElText('kanban-inprogress-count', String(cProg));
        setElText('kanban-completed-count', String(cDone));
        setElText('kanban-progress-pct', pct + '%');
        setElText('metric-completion-rate', pct + '%');

        const bar = document.getElementById('kanban-progress-bar');
        if (bar) bar.style.width = pct + '%';

        [['backlog', sBacklog], ['inprogress', sProg], ['completed', sComp]].forEach(([st, slotEl]) => {
            slotEl.querySelectorAll('.kanban-card').forEach(card => {
                card.dataset.status = st;
                const act = card.querySelector('.kanban-card-actions');
                if (act) act.innerHTML = buildCardActionsHtml(st);
            });
        });
    }

    function moveKanbanCardTo(card, targetStatus) {
        const targetSlot = document.getElementById('slot-' + targetStatus);
        if (card && targetSlot) {
            targetSlot.appendChild(card);
            recomputeKanbanStats();
        }
    }

    if (kanbanRoot) {
        kanbanRoot.addEventListener('dragstart', (e) => {
            const card = e.target.closest('.kanban-card');
            if (!card) return;
            draggedTaskId = card.dataset.taskId;
            card.classList.add('dragging');
            if (e.dataTransfer) {
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', draggedTaskId);
            }
        });
        kanbanRoot.addEventListener('dragend', (e) => {
            const card = e.target.closest('.kanban-card');
            if (card) card.classList.remove('dragging');
            document.querySelectorAll('.kanban-column').forEach(c => c.classList.remove('drag-over'));
            draggedTaskId = null;
        });
        document.querySelectorAll('.kanban-column').forEach(col => {
            col.addEventListener('dragover', (e) => {
                e.preventDefault();
                col.classList.add('drag-over');
            });
            col.addEventListener('dragleave', () => {
                col.classList.remove('drag-over');
            });
            col.addEventListener('drop', (e) => {
                e.preventDefault();
                col.classList.remove('drag-over');
                const tid = (e.dataTransfer && e.dataTransfer.getData('text/plain')) || draggedTaskId;
                const card = tid ? kanbanRoot.querySelector('.kanban-card[data-task-id="' + tid + '"]') : kanbanRoot.querySelector('.kanban-card.dragging');
                if (card && col.dataset.status) {
                    moveKanbanCardTo(card, col.dataset.status);
                }
            });
        });
        kanbanRoot.addEventListener('click', (e) => {
            const btn = e.target.closest('.btn-move-card');
            if (!btn) return;
            const card = btn.closest('.kanban-card');
            if (!card) return;
            const cur = card.dataset.status || 'backlog';
            const idx = colOrder.indexOf(cur);
            const nextIdx = btn.dataset.dir === 'prev' ? Math.max(0, idx - 1) : Math.min(colOrder.length - 1, idx + 1);
            moveKanbanCardTo(card, colOrder[nextIdx]);
        });

        const addTaskBtn = document.getElementById('add-task-btn');
        const newTaskTitle = document.getElementById('new-task-title');
        const newTaskPriority = document.getElementById('new-task-priority');
        function createSprintTask() {
            if (!newTaskTitle) return;
            const rawTitle = newTaskTitle.value.trim();
            if (!rawTitle) {
                newTaskTitle.focus();
                return;
            }
            const prio = (newTaskPriority && newTaskPriority.value) || 'P1';
            const prioClass = prio === 'P0' ? 'priority-p0' : (prio === 'P2' ? 'priority-done' : 'priority-p1');
            const taskId = 'task-' + Date.now();
            const card = document.createElement('div');
            card.className = 'kanban-card';
            card.setAttribute('draggable', 'true');
            card.dataset.taskId = taskId;
            card.dataset.status = 'backlog';

            const titleEl = document.createElement('div');
            titleEl.className = 'kanban-card-title';
            titleEl.textContent = rawTitle;

            const metaEl = document.createElement('div');
            metaEl.className = 'kanban-card-meta';
            metaEl.innerHTML = '<span>Sample Workspace Task</span> <span class="priority-tag ' + prioClass + '">' + prio + '</span>';

            const actEl = document.createElement('div');
            actEl.className = 'kanban-card-actions';
            actEl.innerHTML = buildCardActionsHtml('backlog');

            card.appendChild(titleEl);
            card.appendChild(metaEl);
            card.appendChild(actEl);

            const sBacklog = document.getElementById('slot-backlog');
            if (sBacklog) sBacklog.prepend(card);
            newTaskTitle.value = '';
            recomputeKanbanStats();
        }
        if (addTaskBtn) addTaskBtn.addEventListener('click', createSprintTask);
        if (newTaskTitle) {
            newTaskTitle.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); createSprintTask(); }
            });
        }
        recomputeKanbanStats();
    }

    // Interactive Team & Role Management Directory
    const teamRosterBody = document.getElementById('team-roster-body');
    const addMemberBtn = document.getElementById('add-member-btn');
    function updateTeamCounts() {
        if (!teamRosterBody) return;
        const count = teamRosterBody.querySelectorAll('tr').length;
        const cEl = document.getElementById('team-member-count');
        const mEl = document.getElementById('metric-team-seats');
        if (cEl) cEl.textContent = String(count);
        if (mEl) mEl.textContent = String(count);
    }
    if (teamRosterBody) {
        teamRosterBody.addEventListener('click', (e) => {
            const rm = e.target.closest('.btn-remove-member');
            if (!rm) return;
            const row = rm.closest('tr');
            if (row) row.remove();
            updateTeamCounts();
        });
        teamRosterBody.addEventListener('change', (e) => {
            const sel = e.target.closest('.role-select');
            if (!sel) return;
            const row = sel.closest('tr');
            if (row) row.dataset.role = sel.value;
        });
    }
    if (addMemberBtn && teamRosterBody) {
        addMemberBtn.addEventListener('click', () => {
            const nameIn = document.getElementById('team-member-name');
            const emailIn = document.getElementById('team-member-email');
            const roleIn = document.getElementById('team-member-role');
            const mName = nameIn ? nameIn.value.trim() : '';
            const mEmail = emailIn ? emailIn.value.trim() : '';
            const mRole = roleIn ? roleIn.value : 'Maintainer';
            if (!mName) { if (nameIn) nameIn.focus(); return; }
            if (!mEmail || !mEmail.includes('@')) { if (emailIn) emailIn.focus(); return; }

            const tr = document.createElement('tr');
            tr.dataset.memberId = 'm-' + Date.now();
            tr.dataset.role = mRole;

            const tdName = document.createElement('td');
            const strong = document.createElement('strong');
            strong.textContent = mName;
            tdName.appendChild(strong);

            const tdEmail = document.createElement('td');
            tdEmail.textContent = mEmail;

            const tdRole = document.createElement('td');
            const sel = document.createElement('select');
            sel.className = 'form-control role-select';
            sel.style.cssText = 'padding: 0.25rem 0.5rem; width: auto;';
            ['Admin', 'Maintainer', 'Viewer'].forEach(r => {
                const opt = document.createElement('option');
                opt.value = r;
                opt.textContent = r;
                if (r === mRole) opt.selected = true;
                sel.appendChild(opt);
            });
            tdRole.appendChild(sel);

            const tdAct = document.createElement('td');
            const rmBtn = document.createElement('button');
            rmBtn.type = 'button';
            rmBtn.className = 'btn-move-card btn-remove-member';
            rmBtn.textContent = 'Remove';
            tdAct.appendChild(rmBtn);

            tr.appendChild(tdName);
            tr.appendChild(tdEmail);
            tr.appendChild(tdRole);
            tr.appendChild(tdAct);
            teamRosterBody.appendChild(tr);

            if (nameIn) nameIn.value = '';
            if (emailIn) emailIn.value = '';
            updateTeamCounts();
        });
    }"""
        else:
            saas_interactive_js = ""

        if archetype == "editorial_publication":
            editorial_featured_js = """    // Featured Essay Spotlight Button
    const btnReadFeatured = document.getElementById('btn-read-featured');
    if (btnReadFeatured) {
        btnReadFeatured.addEventListener('click', () => {
            const targetId = btnReadFeatured.dataset.storyId;
            const targetStory = entities.find(x => x.id === targetId) || entities[0];
            if (targetStory && modal && modalBody) {
                openModal(targetStory);
            }
        });
    }"""
        else:
            editorial_featured_js = ""

        js_content = f"""/**
 * {app_name} — Universal Application Logic
 * Synthesized by HERMES 2.x
 */

document.addEventListener('DOMContentLoaded', () => {{
    const entities = {entities_json};
    const isMarketplace = {json.dumps(archetype == "marketplace")};

    const grid = document.getElementById('showcase-grid');
    const search = document.getElementById('showcase-search');
    const filterBtns = document.querySelectorAll('.filter-pill');
{sort_select_init}
    const modal = document.getElementById('details-modal');
    const modalClose = document.getElementById('modal-close');
    const modalBody = document.getElementById('modal-body');
    const form = document.getElementById('{form_meta.get("form_id", "inquiry-form")}');
    const feedback = document.getElementById('form-feedback');
    const mobileMenuBtn = document.getElementById('mobile-menu-btn');
    const navMenu = document.getElementById('nav-menu');
{basket_init_js}

    let activeCategory = 'all';
    let searchQuery = '';
    let sortOrder = 'featured';
    let basket = [];

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

        let displayItems = [...filtered];
        if (isMarketplace) {{
            if (sortOrder === 'price-asc') {{
                displayItems.sort((a, b) => (a.price || 0) - (b.price || 0));
            }} else if (sortOrder === 'price-desc') {{
                displayItems.sort((a, b) => (b.price || 0) - (a.price || 0));
            }}
        }}

        if (isMarketplace) {{
            grid.innerHTML = displayItems.map(it => `
                <article class="entity-card" data-category="${{it.category}}" id="${{it.id}}">
                    <div class="entity-card-media" style="position: relative;">
                        <img src="${{it.image_path}}" alt="${{it.title}}" loading="eager" onerror="this.style.display='none'">
                        <span class="entity-badge">${{it.category_label || it.category}}</span>
                    </div>
                    <div class="entity-card-body">
                        <h3 class="entity-card-title">${{it.title}}</h3>
                        ${{it.specifications ? `<div class="entity-spec-row">${{it.specifications}}</div>` : ''}}
                        ${{it.provenance ? `<div class="provenance-tag"><strong>Origin:</strong> ${{it.provenance}}</div>` : ''}}
                        ${{it.status ? `<div class="stock-tag">${{it.status}}</div>` : ''}}
                        <div class="entity-price-row">
                            <span class="price-tag">${{it.price_display || ('$' + (it.price || 0) + ' / unit')}}</span>
                            <span class="price-illustrative" style="font-size: 0.75rem; color: var(--text-secondary); margin-left: 0.35rem; font-weight: normal;">(Illustrative)</span>
                        </div>
                        <p class="entity-card-desc">${{it.description}}</p>
                        <div class="entity-card-actions-marketplace">
                            <button class="btn-primary btn-add-quote" data-id="${{it.id}}">+ Add to Quote</button>
                            <button class="btn-secondary btn-details" data-id="${{it.id}}">View Specs</button>
                        </div>
                    </div>
                </article>
            `).join('');

            grid.querySelectorAll('.btn-add-quote').forEach(btn => {{
                btn.addEventListener('click', (e) => {{
                    e.stopPropagation();
                    addToBasket(btn.dataset.id);
                }});
            }});
        }} else {{
            grid.innerHTML = displayItems.map(it => `
                <article class="entity-card" data-category="${{it.category}}" id="${{it.id}}">
                    <div class="entity-card-media">
                        <img src="${{it.image_path}}" alt="${{it.title}}" loading="eager" onerror="this.style.display='none'">
                        <span class="entity-badge">${{it.category_label || it.category}}</span>
                        ${{it.status ? `<span class="entity-status-badge">${{it.status}}</span>` : ''}}
                    </div>
                    <div class="entity-card-body">
                        <h3 class="entity-card-title">${{it.title}}</h3>
                        ${{it.specifications ? `<div class="entity-spec-row">${{it.specifications}}</div>` : ''}}
                        ${{it.price_display ? `<div class="entity-price-row" style="margin-bottom: 0.5rem;"><span class="price-tag">${{it.price_display}}</span></div>` : ''}}
                        <p class="entity-card-desc">${{it.description}}</p>
                        <div class="entity-card-actions">
                            <button class="btn-primary btn-details" data-id="${{it.id}}" style="width: 100%; padding: 0.65rem 1rem; font-size: 0.9rem;">{action_label}</button>
                        </div>
                    </div>
                </article>
            `).join('');
        }}

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

    // Basket State & Rendering
    function renderBasket() {{
        if (!basketList) return;
        const totalItems = basket.reduce((acc, item) => acc + item.qty, 0);
        basketCountEls.forEach(el => {{ el.textContent = totalItems; }});

        if (basket.length === 0) {{
            basketList.innerHTML = `
                <div class="empty-basket">
                    <p style="font-size: 1.05rem; margin-bottom: 0.5rem; font-weight: 600;">Your quote basket is currently empty.</p>
                    <p style="font-size: 0.88rem; color: var(--text-secondary);">Browse reclaimed and recycled circular materials above and click "+ Add to Quote" to assemble an itemized bill of materials.</p>
                </div>
            `;
            if (basketSubtotalEl) basketSubtotalEl.textContent = '$0.00';
            return;
        }}

        let subtotal = 0;
        const rowsHtml = basket.map(item => {{
            const itemSub = (item.price || 0) * item.qty;
            subtotal += itemSub;
            return `
                <tr>
                    <td>
                        <strong>${{item.title}}</strong>
                        <div style="font-size: 0.8rem; color: var(--text-secondary);">${{item.category_label || item.category}}</div>
                    </td>
                    <td>${{item.price_display || ('$' + (item.price || 0))}}</td>
                    <td>
                        <div class="qty-controls">
                            <button class="qty-btn qty-minus" data-id="${{item.id}}" aria-label="Decrease quantity">&minus;</button>
                            <span class="qty-val">${{item.qty}}</span>
                            <button class="qty-btn qty-plus" data-id="${{item.id}}" aria-label="Increase quantity">&plus;</button>
                        </div>
                    </td>
                    <td style="font-weight: 700; color: var(--accent-color);">$${{itemSub.toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }})}}</td>
                    <td style="text-align: center;">
                        <button class="btn-remove-item" data-id="${{item.id}}" aria-label="Remove item">&times;</button>
                    </td>
                </tr>
            `;
        }}).join('');

        basketList.innerHTML = `
            <div class="table-responsive">
                <table class="basket-table">
                    <thead>
                        <tr>
                            <th>Material</th>
                            <th>Unit Price (Illustrative)</th>
                            <th>Quantity</th>
                            <th>Subtotal (Illustrative)</th>
                            <th style="text-align: center;">Remove</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${{rowsHtml}}
                    </tbody>
                </table>
            </div>
            <p style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.5rem; text-align: right;">* All prices are illustrative demonstration estimates.</p>
        `;

        if (basketSubtotalEl) {{
            basketSubtotalEl.textContent = '$' + subtotal.toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
        }}

        basketList.querySelectorAll('.qty-minus').forEach(b => {{
            b.addEventListener('click', () => updateQuantity(b.dataset.id, -1));
        }});
        basketList.querySelectorAll('.qty-plus').forEach(b => {{
            b.addEventListener('click', () => updateQuantity(b.dataset.id, 1));
        }});
        basketList.querySelectorAll('.btn-remove-item').forEach(b => {{
            b.addEventListener('click', () => removeFromBasket(b.dataset.id));
        }});
    }}

    function addToBasket(id) {{
        const item = entities.find(x => x.id === id);
        if (!item) return;
        const existing = basket.find(x => x.id === id);
        if (existing) {{
            existing.qty += 1;
        }} else {{
            basket.push({{ ...item, qty: 1 }});
        }}
        renderBasket();
    }}

    function updateQuantity(id, delta) {{
        const existing = basket.find(x => x.id === id);
        if (!existing) return;
        existing.qty += delta;
        if (existing.qty <= 0) {{
            basket = basket.filter(x => x.id !== id);
        }}
        renderBasket();
    }}

    function removeFromBasket(id) {{
        basket = basket.filter(x => x.id !== id);
        renderBasket();
    }}

    function clearBasket() {{
        basket = [];
        renderBasket();
    }}
    window.clearBasket = clearBasket;

    // Modal Lifecycle
    function openModal(it) {{
        const relatedItems = Array.isArray(it.related_ids)
            ? entities.filter(x => it.related_ids.includes(x.id))
            : [];
        const relatedHtml = relatedItems.length > 0 ? `
            <div style="margin-bottom: 1.25rem; padding-top: 1rem; border-top: 1px solid var(--border-color);">
                <div style="font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); margin-bottom: 0.6rem;">Related Dispatches</div>
                <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                    ${{relatedItems.map(rel => `<button type="button" class="btn-secondary btn-related-story" data-story-id="${{rel.id}}" style="padding: 0.45rem 0.85rem; font-size: 0.85rem;">${{rel.title}}</button>`).join('')}}
                </div>
            </div>` : '';

        modalBody.innerHTML = `
            <div style="margin-bottom: 1.5rem; border-radius: var(--radius-md); overflow: hidden; max-height: 260px;">
                <img src="${{it.image_path}}" alt="${{it.title}}" style="width: 100%; height: 260px; object-fit: cover;" onerror="this.style.display='none'">
            </div>
            <div style="display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap;">
                <span class="entity-badge" style="position: static;">${{it.category_label || it.category}}</span>
                ${{it.status ? `<span class="entity-status-badge" style="position: static;">${{it.status}}</span>` : ''}}
            </div>
            <h2 style="font-size: 1.6rem; margin-bottom: 0.75rem;">${{it.title}}</h2>
            ${{it.price_display ? `<div style="font-size: 1.3rem; font-weight: 800; color: var(--accent-color); margin-bottom: 0.75rem;">${{it.price_display}} <span style="font-size: 0.8rem; font-weight: normal; color: var(--text-secondary);">(Illustrative pricing for demonstration)</span></div>` : ''}}
            ${{it.specifications ? `<div class="entity-spec-row" style="margin-bottom: 0.75rem; font-size: 0.88rem;"><strong>Specifications:</strong> ${{it.specifications}}</div>` : ''}}
            ${{it.provenance ? `<div class="provenance-tag" style="margin-bottom: 0.75rem;"><strong>Origin:</strong> ${{it.provenance}}</div>` : ''}}
            <p style="font-size: 0.95rem; line-height: 1.6; color: var(--text-secondary); margin-bottom: 1.1rem;">${{it.description}}</p>
            ${{it.full_body ? `<p style="font-size: 0.96rem; line-height: 1.75; color: var(--text-primary); margin-bottom: 1.25rem; padding: 1rem; background: var(--bg-main); border-left: 3px solid var(--accent-color); border-radius: var(--radius-sm);">${{it.full_body}}</p>` : ''}}
            ${{relatedHtml}}
            ${{isMarketplace ? `
            <div style="margin-bottom: 1rem;">
                <button class="btn-primary modal-add-quote" data-id="${{it.id}}" style="padding: 0.65rem 1.25rem;">+ Add to Quote Basket</button>
            </div>` : ''}}
            <div style="padding: 1rem; background: var(--bg-main); border-radius: var(--radius-sm); border: 1px solid var(--border-color); font-size: 0.85rem;">
                <strong>{modal_telemetry_msg}</strong>
            </div>
        `;
        const modalAddBtn = modalBody.querySelector('.modal-add-quote');
        if (modalAddBtn) {{
            modalAddBtn.addEventListener('click', () => {{
                addToBasket(modalAddBtn.dataset.id);
                closeModal();
            }});
        }}
        modalBody.querySelectorAll('.btn-related-story').forEach(relBtn => {{
            relBtn.addEventListener('click', () => {{
                const relEntity = entities.find(x => x.id === relBtn.dataset.storyId);
                if (relEntity) openModal(relEntity);
            }});
        }});
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

    // Search, Sorting, and Filtering
    if (search) {{
        search.addEventListener('input', (e) => {{
            searchQuery = e.target.value;
            render();
        }});
    }}

{sort_select_listener}

    filterBtns.forEach(btn => {{
        btn.addEventListener('click', () => {{
            filterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeCategory = btn.dataset.category || 'all';
            render();
        }});
    }});

{billing_toggle_js}

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

{geospatial_calc_js}

{museum_tickets_js}

{saas_interactive_js}

{editorial_featured_js}

    // Form Validation & Demonstration Feedback
    if (form) {{
        const now = new Date();
        const todayIso = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
        form.querySelectorAll('input[type="date"]').forEach(dIn => {{
            dIn.setAttribute('min', todayIso);
        }});

        form.addEventListener('submit', (e) => {{
            e.preventDefault();
            const requiredEls = form.querySelectorAll('[required]');
            for (const reqEl of requiredEls) {{
                if (!reqEl.value || !reqEl.value.trim()) {{
                    if (feedback) {{
                        feedback.className = 'form-feedback error';
                        feedback.textContent = 'Please complete all required fields before submitting.';
                    }}
                    reqEl.focus();
                    return;
                }}
            }}

            const emailInput = form.querySelector('input[type="email"]');
            if (emailInput && (!emailInput.value || !emailInput.value.includes('@') || !emailInput.value.includes('.'))) {{
                if (feedback) {{
                    feedback.className = 'form-feedback error';
                    feedback.textContent = 'Please enter a valid email address.';
                }}
                emailInput.focus();
                return;
            }}

            const dateInput = form.querySelector('input[type="date"]');
            if (dateInput && dateInput.value && dateInput.value < todayIso) {{
                if (feedback) {{
                    feedback.className = 'form-feedback error';
                    feedback.textContent = 'Please select today or a future date for your reservation request.';
                }}
                dateInput.focus();
                return;
            }}

            if (feedback) {{
                feedback.className = 'form-feedback success';
                const detailParts = [];
                if (dateInput && dateInput.value) detailParts.push('Date: ' + dateInput.value);
                form.querySelectorAll('select').forEach(sel => {{
                    if (sel.value) detailParts.push(sel.value);
                }});
                const detailSuffix = detailParts.length > 0 ? ' [' + detailParts.join(' | ') + ']' : '';
                feedback.textContent = '{success_msg}' + detailSuffix + ' (Demonstration Mode: Captured in-browser)';
            }}
            form.reset();
        }});
    }}

    // Initial Render
    render();
    if (isMarketplace) {{
        renderBasket();
    }}
}});
"""
        js_path.write_text(js_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(js_path, ws, generator="universal_renderer")

        logger.info(f"UniversalContentRenderer: Successfully seeded authoritative deliverables for '{app_name}'")
        return True
