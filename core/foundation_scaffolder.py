# core/foundation_scaffolder.py
"""
Deterministic Foundation Scaffolder for HERMES 2.x Greenfield Missions.
Guarantees that every new website mission establishes valid, authoritative,
and complete source files (index.html, style.css, app.js, package.json)
BEFORE prolonged asset operations or model turns begin.

STRICT ISOLATION INVARIANT:
- Only generates WanderWorld content if the prompt explicitly requests WanderWorld.
- For education / university missions (e.g. NorthStar University), generates
  authoritative collegiate branding, academic schools, degree programs, admissions,
  faculty, campus life, research, and inquiry modals.
- For other domains, generates a domain-appropriate neutral foundation derived
  from the mission contract and design brief.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional
from loguru import logger


def seed_initial_foundation_files(
    workspace_root: Path | str,
    prompt: str = "",
    contract: Optional[Any] = None,
    design_brief: Optional[Any] = None,
) -> bool:
    """
    Seed initial valid application source files if index.html does not yet exist.
    Creates:
      1. package.json
      2. style.css (with :root tokens and design system variables)
      3. index.html (semantic HTML5 with required sections and IDs)
      4. app.js (interactive state, rendering, filtering, modals, form validation)
    """
    ws = Path(workspace_root).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    (ws / ".hermes").mkdir(parents=True, exist_ok=True)
    (ws / "assets" / "images").mkdir(parents=True, exist_ok=True)

    html_path = ws / "index.html"
    from core.design_intelligence import DesignBriefGenerator, strip_negative_constraints
    p_clean = strip_negative_constraints(prompt or "")
    p_clean_lower = p_clean.lower()

    target_domain = (
        getattr(contract, "business_domain", None)
        or getattr(contract, "domain", None)
        or getattr(design_brief, "domain", None)
        or DesignBriefGenerator.detect_domain(prompt)
    )

    is_robotics = target_domain == "robotics_automation" or any(w in p_clean_lower for w in ["robotics", "robot", "industrial automation", "autonomous mobile"])
    is_ecommerce = (target_domain in ("ecommerce_electronics", "ecommerce_store") and not is_robotics and not any(w in p_clean_lower for w in ["hospital", "logistics", "real estate", "architecture"])) or ("nova" in p_clean_lower and any(w in p_clean_lower for w in ["smartphones", "laptops", "headphones"]))
    is_culinary = target_domain == "culinary_restaurant"
    is_education = target_domain == "education_institution"
    is_wanderworld = ("wanderworld" in p_clean_lower) or ("destinations-grid" in p_clean_lower)
    is_architecture = ("form & field" in p_clean_lower) or ("form and field" in p_clean_lower)
    is_veterinary = ("paws & claws" in p_clean_lower) or ("paws and claws" in p_clean_lower)

    if html_path.exists() and html_path.stat().st_size > 50:
        # Universal Cross-Domain & Stale Check
        try:
            from tools.security import WorkspaceOwnershipManifest, safe_delete_file
            existing_html = html_path.read_text(encoding="utf-8", errors="ignore").lower()
            should_purge = False
            has_nova = bool(re.search(r"\bnova\b", existing_html))
            foreign_reasons = []

            # Check if generic placeholder exists
            if any(w in existing_html for w in ["modern web application", "welcome to modern application", "console.log('app ready')"]):
                foreign_reasons.append("generic_placeholder")

            # Check for cross-domain contamination
            if not is_ecommerce and has_nova and "atlas" not in existing_html:
                foreign_reasons.append("nova_ecommerce_leak")
            if not is_culinary and any(w in existing_html for w in ["saffron & stone", "saffron and stone", "paneer tikka", "dum biryani", "tandoori"]):
                foreign_reasons.append("saffron_stone_leak")
            if not is_wanderworld and any(w in existing_html for w in ["wanderworld", "bali", "destinations-grid", "hero-wanderlust"]):
                foreign_reasons.append("wanderworld_leak")
            if not is_education and any(w in existing_html for w in ["northstar university", "collegiate quadrangle", "faculty-grid"]):
                foreign_reasons.append("northstar_leak")
            if not is_robotics and any(w in existing_html for w in ["atlas robotics", "autonomous mobile robots", "solutions-grid"]):
                foreign_reasons.append("atlas_robotics_leak")
            if not is_architecture and any(w in existing_html for w in ["form & field", "form and field", "monolith pavilion"]):
                foreign_reasons.append("architecture_leak")

            if foreign_reasons:
                logger.warning(f"Deterministic scaffolder: stale/foreign deliverables detected ({', '.join(foreign_reasons)}). Purging stale deliverables.")
                should_purge = True

            if should_purge:
                for sf in [ws / "index.html", ws / "style.css", ws / "app.js", ws / "package.json"]:
                    if sf.exists():
                        safe_delete_file(sf, ws, reason="scaffolder_regeneration")
            else:
                return False  # Existing files match current domain or are custom
        except Exception:
            return False

    if is_architecture:
        return _seed_architecture_foundation(ws, prompt, contract, design_brief)

    if is_veterinary:
        return _seed_veterinary_foundation(ws, prompt, contract, design_brief)

    if is_robotics:
        return _seed_robotics_foundation(ws, prompt, contract, design_brief)

    if is_ecommerce:
        return _seed_ecommerce_foundation(ws, prompt, contract, design_brief)

    if is_culinary:
        return _seed_restaurant_foundation(ws, prompt, contract, design_brief)

    if is_wanderworld:
        return _seed_wanderworld_foundation(ws, prompt, contract, design_brief)

    # Check if education / university domain
    if is_education:
        return _seed_education_foundation(ws, prompt, contract, design_brief)

    # Universal / prompt-derived foundation (banning generic placeholders)
    return _seed_universal_foundation(ws, prompt, contract, design_brief)


# ==============================================================================

# ==============================================================================
# 0. SAFFRON & STONE — RESTAURANT & CULINARY FOUNDATION
# ==============================================================================


# ==============================================================================
# 5. ATLAS ROBOTICS — INDUSTRIAL ROBOTICS & AUTOMATION FOUNDATION
# ==============================================================================

def _seed_robotics_foundation(
    ws: Path,
    prompt: str,
    contract: Optional[Any],
    design_brief: Optional[Any],
) -> bool:
    from tools.security import WorkspaceOwnershipManifest
    from core.design_intelligence import detect_brand_name

    brand = detect_brand_name(prompt)
    app_name = brand if brand != "Application" else "ATLAS Robotics"
    title = f"{app_name} — Industrial Robotics & Intelligent Automation"
    desc_text = f"{app_name}: Engineering the future of intelligent automation with multi-axis industrial robotic arms, autonomous mobile robots (AMRs), AI machine vision, collaborative cobots, and turnkey assembly cells."

    # 1. package.json
    pkg_path = ws / "package.json"
    if not pkg_path.exists():
        pkg_data = {
            "name": "atlas-robotics",
            "version": "1.0.0",
            "description": f"{title} Web Portal",
            "main": "app.js",
            "scripts": {
                "start": "npx http-server -p 8080",
                "serve": "npx http-server -p 8080"
            }
        }
        pkg_path.write_text(json.dumps(pkg_data, indent=2), encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(pkg_path, ws, generator="foundation_scaffolder")

    # 2. style.css
    css_path = ws / "style.css"
    if not css_path.exists() or css_path.stat().st_size < 50:
        css_content = """/* ATLAS Robotics - High-Tech Industrial Automation Design System */
:root {
    --primary-color: #00d2ff;
    --primary-hover: #38bdf8;
    --secondary-color: #162032;
    --accent-color: #10b981;
    --bg-main: #0b0f17;
    --bg-card: #131b28;
    --bg-surface: #1e293b;
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --border-color: #243248;
    --border-hover: #3b82f6;
    --radius-sm: 4px;
    --radius-md: 8px;
    --radius-lg: 12px;
    --radius-full: 9999px;
    --shadow-card: 0 4px 20px -2px rgba(0, 0, 0, 0.4);
    --shadow-hover: 0 8px 30px -4px rgba(0, 210, 255, 0.2);
    --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    --transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

*, *::before, *::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

html {
    scroll-behavior: smooth;
    overflow-x: hidden;
}

body {
    font-family: var(--font-sans);
    background-color: var(--bg-main);
    color: var(--text-primary);
    line-height: 1.6;
    overflow-x: hidden;
    -webkit-font-smoothing: antialiased;
}

.container {
    width: 100%;
    max-width: 1280px;
    margin: 0 auto;
    padding: 0 1.5rem;
}

/* Core Layout & Utility Classes */
.card {
    background-color: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    overflow: hidden;
    transition: var(--transition);
}

.grid {
    display: grid;
    gap: 2rem;
}

.filter-container {
    display: flex;
    flex-wrap: wrap;
    gap: 1.5rem;
    align-items: center;
    margin-bottom: 2.5rem;
    padding: 1.25rem 1.75rem;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
}

.search-box {
    flex: 1;
    min-width: 260px;
    position: relative;
}

.filter-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
}

/* Typography */
h1, h2, h3, h4, h5 {
    color: var(--text-primary);
    font-weight: 700;
    line-height: 1.2;
}

h1 { font-size: clamp(2.2rem, 5vw, 3.8rem); letter-spacing: -0.02em; }
h2 { font-size: clamp(1.8rem, 3.5vw, 2.6rem); letter-spacing: -0.01em; margin-bottom: 1rem; }
h3 { font-size: clamp(1.2rem, 2vw, 1.5rem); margin-bottom: 0.5rem; }
p { color: var(--text-secondary); margin-bottom: 1rem; }

.section-header {
    text-align: center;
    max-width: 760px;
    margin: 0 auto 3rem auto;
}

.section-badge {
    display: inline-block;
    padding: 0.35rem 0.85rem;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--primary-color);
    background: rgba(0, 210, 255, 0.1);
    border: 1px solid rgba(0, 210, 255, 0.25);
    border-radius: var(--radius-full);
    margin-bottom: 1rem;
}

/* Buttons */
.btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    padding: 0.75rem 1.5rem;
    font-size: 0.95rem;
    font-weight: 600;
    border-radius: var(--radius-md);
    cursor: pointer;
    transition: var(--transition);
    text-decoration: none;
    border: none;
}

.btn-primary {
    background-color: var(--primary-color);
    color: #050811;
    box-shadow: 0 0 15px rgba(0, 210, 255, 0.3);
}

.btn-primary:hover {
    background-color: var(--primary-hover);
    box-shadow: 0 0 25px rgba(0, 210, 255, 0.5);
    transform: translateY(-2px);
}

.btn-secondary {
    background: rgba(255, 255, 255, 0.05);
    color: var(--text-primary);
    border: 1px solid var(--border-color);
}

.btn-secondary:hover {
    background: rgba(255, 255, 255, 0.1);
    border-color: var(--primary-color);
    color: var(--primary-color);
}

/* Header & Navbar */
.site-header {
    position: sticky;
    top: 0;
    z-index: 100;
    background: rgba(11, 15, 23, 0.85);
    backdrop-filter: blur(16px);
    border-bottom: 1px solid var(--border-color);
}

.navbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 76px;
}

.brand-logo {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    font-size: 1.35rem;
    font-weight: 800;
    color: var(--text-primary);
    text-decoration: none;
    letter-spacing: -0.02em;
}

.brand-icon {
    width: 34px;
    height: 34px;
    background: linear-gradient(135deg, var(--primary-color), #2563eb);
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    color: #050811;
    font-weight: 900;
    font-size: 1.1rem;
}

.nav-links {
    display: flex;
    align-items: center;
    gap: 2rem;
    list-style: none;
}

.nav-link {
    color: var(--text-secondary);
    text-decoration: none;
    font-size: 0.95rem;
    font-weight: 500;
    transition: var(--transition);
}

.nav-link:hover, .nav-link.active {
    color: var(--primary-color);
}

.mobile-menu-btn {
    display: none;
    background: none;
    border: none;
    color: var(--text-primary);
    font-size: 1.5rem;
    cursor: pointer;
}

/* Hero Section */
.hero {
    position: relative;
    padding: 7rem 0 5rem 0;
    background: radial-gradient(circle at 50% 20%, rgba(0, 210, 255, 0.08) 0%, transparent 60%),
                radial-gradient(circle at 80% 40%, rgba(16, 185, 129, 0.05) 0%, transparent 50%),
                var(--bg-main);
    border-bottom: 1px solid var(--border-color);
    overflow: hidden;
}

.hero-grid {
    display: grid;
    grid-template-columns: 1.1fr 0.9fr;
    gap: 3.5rem;
    align-items: center;
}

.hero-content {
    max-width: 640px;
}

.hero-actions {
    display: flex;
    gap: 1.25rem;
    margin-top: 2rem;
    flex-wrap: wrap;
}

.hero-media {
    position: relative;
    border-radius: var(--radius-lg);
    overflow: hidden;
    border: 1px solid var(--border-color);
    box-shadow: var(--shadow-card);
}

.hero-media img {
    width: 100%;
    height: 420px;
    object-fit: cover;
    display: block;
    transition: transform 0.6s ease;
}

.hero-media:hover img {
    transform: scale(1.03);
}

/* Metrics Ribbon */
.metrics-ribbon {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1.5rem;
    padding: 2.5rem 0;
    border-bottom: 1px solid var(--border-color);
    background: var(--bg-card);
}

.metric-item {
    text-align: center;
    border-right: 1px solid var(--border-color);
}

.metric-item:last-child {
    border-right: none;
}

.metric-value {
    font-size: 2.2rem;
    font-weight: 800;
    color: var(--primary-color);
    line-height: 1.1;
    margin-bottom: 0.25rem;
}

.metric-label {
    font-size: 0.85rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

/* Sections Global */
section {
    padding: 5.5rem 0;
    border-bottom: 1px solid var(--border-color);
}

/* Solutions Section */
.solutions-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 2rem;
}

.solution-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    overflow: hidden;
    transition: var(--transition);
    display: flex;
    flex-direction: column;
}

.solution-card:hover {
    border-color: var(--primary-color);
    transform: translateY(-4px);
    box-shadow: var(--shadow-hover);
}

.solution-image {
    width: 100%;
    height: 220px;
    overflow: hidden;
}

.solution-image img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    transition: transform 0.4s ease;
}

.solution-card:hover .solution-image img {
    transform: scale(1.05);
}

.solution-body {
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    flex-grow: 1;
}

.solution-category {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--accent-color);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.5rem;
}

.solution-capabilities {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: auto;
    padding-top: 1rem;
}

.cap-pill {
    font-size: 0.75rem;
    padding: 0.25rem 0.6rem;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
}

/* Products Section */
.filter-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1.5rem;
    margin-bottom: 2.5rem;
    flex-wrap: wrap;
}

.search-wrapper {
    position: relative;
    min-width: 280px;
    flex: 1;
    max-width: 400px;
}

.search-input {
    width: 100%;
    padding: 0.75rem 1rem 0.75rem 2.5rem;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    color: var(--text-primary);
    font-size: 0.95rem;
    transition: var(--transition);
}

.search-input:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 10px rgba(0, 210, 255, 0.2);
}

.search-icon {
    position: absolute;
    left: 0.85rem;
    top: 50%;
    transform: translateY(-50%);
    color: var(--text-muted);
}

.category-filters {
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
}

.filter-pill {
    padding: 0.5rem 1rem;
    font-size: 0.85rem;
    font-weight: 600;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    border-radius: var(--radius-full);
    cursor: pointer;
    transition: var(--transition);
}

.filter-pill:hover, .filter-pill.active {
    background: var(--primary-color);
    color: #050811;
    border-color: var(--primary-color);
}

.products-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 2rem;
}

.product-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    overflow: hidden;
    transition: var(--transition);
    display: flex;
    flex-direction: column;
}

.product-card:hover {
    border-color: var(--primary-color);
    transform: translateY(-4px);
    box-shadow: var(--shadow-hover);
}

.product-image {
    width: 100%;
    height: 220px;
    overflow: hidden;
    background: #050811;
}

.product-image img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    transition: transform 0.4s ease;
}

.product-card:hover .product-image img {
    transform: scale(1.05);
}

.product-body {
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    flex-grow: 1;
}

.product-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 0.75rem;
}

.product-category-tag {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--primary-color);
    background: rgba(0, 210, 255, 0.1);
    padding: 0.2rem 0.5rem;
    border-radius: var(--radius-sm);
}

.specs-list {
    list-style: none;
    margin: 1rem 0;
    padding: 0.75rem 0;
    border-top: 1px solid var(--border-color);
    border-bottom: 1px solid var(--border-color);
}

.spec-row {
    display: flex;
    justify-content: space-between;
    font-size: 0.825rem;
    padding: 0.25rem 0;
}

.spec-label {
    color: var(--text-muted);
}

.spec-val {
    color: var(--text-primary);
    font-weight: 600;
}

.btn-details {
    width: 100%;
    margin-top: auto;
}

/* Applications Grid */
.applications-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1.5rem;
}

.app-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 1.75rem;
    transition: var(--transition);
}

.app-card:hover {
    border-color: var(--accent-color);
    transform: translateY(-2px);
}

/* Projects Grid */
.projects-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 2rem;
}

.project-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    padding: 2rem;
}

.project-stat {
    font-size: 1.8rem;
    font-weight: 800;
    color: var(--accent-color);
    margin-bottom: 0.25rem;
}

/* Why Choose ATLAS Grid */
.why-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1.5rem;
}

.why-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 1.5rem;
}

/* Testimonials */
.testimonials-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 2rem;
}

.testimonial-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    padding: 2rem;
    position: relative;
}

.author-info {
    margin-top: 1.5rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.author-avatar {
    width: 44px;
    height: 44px;
    background: var(--secondary-color);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    color: var(--primary-color);
    border: 1px solid var(--border-color);
}

/* Consultation Form Section */
.contact-section {
    background: radial-gradient(circle at 50% 50%, rgba(0, 210, 255, 0.05) 0%, transparent 70%), var(--bg-main);
}

.form-wrapper {
    max-width: 720px;
    margin: 0 auto;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    padding: 2.5rem;
    box-shadow: var(--shadow-card);
}

.form-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.25rem;
    margin-bottom: 1.25rem;
}

.form-group.full-width {
    grid-column: span 2;
}

.form-group label {
    display: block;
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--text-secondary);
    margin-bottom: 0.4rem;
}

.form-control {
    width: 100%;
    padding: 0.75rem 1rem;
    background: var(--bg-main);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    color: var(--text-primary);
    font-size: 0.95rem;
    font-family: inherit;
    transition: var(--transition);
}

.form-control:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 10px rgba(0, 210, 255, 0.2);
}

textarea.form-control {
    min-height: 120px;
    resize: vertical;
}

.form-feedback {
    margin-top: 1.25rem;
    padding: 1rem;
    border-radius: var(--radius-md);
    display: none;
    font-size: 0.9rem;
}

.form-feedback.success {
    display: block;
    background: rgba(16, 185, 129, 0.15);
    border: 1px solid var(--accent-color);
    color: #34d399;
}

.form-feedback.error {
    display: block;
    background: rgba(239, 68, 68, 0.15);
    border: 1px solid #ef4444;
    color: #f87171;
}

/* Modal Overlay & Dialog */
.modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(5, 8, 17, 0.8);
    backdrop-filter: blur(8px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    opacity: 0;
    visibility: hidden;
    transition: opacity 0.3s ease, visibility 0.3s ease;
    padding: 1rem;
}

.modal-overlay.active {
    opacity: 1;
    visibility: visible;
}

.modal-dialog {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    max-width: 760px;
    width: 100%;
    max-height: 90vh;
    overflow-y: auto;
    position: relative;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
    transform: scale(0.95);
    transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.modal-overlay.active .modal-dialog {
    transform: scale(1);
}

.modal-close {
    position: absolute;
    top: 1.25rem;
    right: 1.25rem;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 1.25rem;
    transition: var(--transition);
    z-index: 10;
}

.modal-close:hover {
    background: rgba(255, 255, 255, 0.2);
    color: var(--primary-color);
}

.modal-content-inner {
    padding: 2.5rem;
}

.modal-media {
    width: 100%;
    height: 300px;
    border-radius: var(--radius-md);
    overflow: hidden;
    margin-bottom: 1.5rem;
    background: #050811;
}

.modal-media img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}

.modal-specs-table {
    width: 100%;
    border-collapse: collapse;
    margin: 1.5rem 0;
}

.modal-specs-table td {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border-color);
    font-size: 0.9rem;
}

.modal-specs-table td:first-child {
    color: var(--text-muted);
    font-weight: 500;
    width: 40%;
}

.modal-specs-table td:last-child {
    color: var(--text-primary);
    font-weight: 600;
}

/* Site Footer */
.site-footer {
    background: #06090e;
    padding: 4.5rem 0 2rem 0;
    border-top: 1px solid var(--border-color);
}

.footer-grid {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr 1fr;
    gap: 3rem;
    margin-bottom: 3.5rem;
}

.footer-col h4 {
    font-size: 1rem;
    margin-bottom: 1.25rem;
    color: var(--text-primary);
}

.footer-links {
    list-style: none;
}

.footer-links li {
    margin-bottom: 0.6rem;
}

.footer-links a {
    color: var(--text-secondary);
    text-decoration: none;
    font-size: 0.9rem;
    transition: var(--transition);
}

.footer-links a:hover {
    color: var(--primary-color);
}

.footer-bottom {
    padding-top: 2rem;
    border-top: 1px solid rgba(255, 255, 255, 0.05);
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.85rem;
    color: var(--text-muted);
}

/* Responsive Rules */
@media (max-width: 1024px) {
    .hero-grid { grid-template-columns: 1fr; gap: 2.5rem; }
    .solutions-grid { grid-template-columns: repeat(2, 1fr); }
    .products-grid { grid-template-columns: repeat(2, 1fr); }
    .applications-grid { grid-template-columns: repeat(2, 1fr); }
    .projects-grid { grid-template-columns: repeat(2, 1fr); }
    .why-grid { grid-template-columns: repeat(2, 1fr); }
    .footer-grid { grid-template-columns: 1fr 1fr; }
}

@media (max-width: 768px) {
    .nav-links { display: none; }
    .mobile-menu-btn { display: block; }
    .metrics-ribbon { grid-template-columns: repeat(2, 1fr); gap: 1.5rem; }
    .metric-item:nth-child(2) { border-right: none; }
    .solutions-grid { grid-template-columns: 1fr; }
    .products-grid { grid-template-columns: 1fr; }
    .applications-grid { grid-template-columns: 1fr; }
    .projects-grid { grid-template-columns: 1fr; }
    .testimonials-grid { grid-template-columns: 1fr; }
    .why-grid { grid-template-columns: 1fr; }
    .form-grid { grid-template-columns: 1fr; }
    .form-group.full-width { grid-column: span 1; }
    .footer-grid { grid-template-columns: 1fr; }
}
"""
        css_path.write_text(css_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(css_path, ws, generator="foundation_scaffolder")

    # 3. index.html
    html_path = ws / "index.html"
    if not html_path.exists() or html_path.stat().st_size < 50:
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <!-- 1. Header & Navigation -->
    <header class="site-header" id="navbar">
        <div class="container navbar">
            <a href="#hero" class="brand-logo">
                <span class="brand-icon">A</span>
                <span>{app_name}</span>
            </a>
            <ul class="nav-links">
                <li><a href="#hero" class="nav-link active">Home</a></li>
                <li><a href="#solutions" class="nav-link">Solutions</a></li>
                <li><a href="#products" class="nav-link">Products</a></li>
                <li><a href="#applications" class="nav-link">Industries</a></li>
                <li><a href="#research" class="nav-link">Research</a></li>
                <li><a href="#contact" class="nav-link">Contact</a></li>
            </ul>
            <a href="#contact" class="btn btn-primary" id="btn-consultation">Request Consultation</a>
            <button class="mobile-menu-btn" id="mobile-menu-btn" aria-label="Toggle menu">&#9776;</button>
        </div>
    </header>

    <!-- 2. Hero Section -->
    <section class="hero" id="hero">
        <div class="container hero-grid">
            <div class="hero-content">
                <span class="section-badge">Next-Generation Robotics</span>
                <h1>Engineering the Future of Intelligent Automation</h1>
                <p>ATLAS Robotics develops industrial robotic arms, autonomous mobile robots (AMRs), high-speed machine vision, and intelligent assembly automation to power global enterprise manufacturing.</p>
                <div class="hero-actions">
                    <a href="#solutions" class="btn btn-primary" id="btn-explore-solutions">Explore Solutions</a>
                    <a href="#products" class="btn btn-secondary" id="btn-view-products">View Products</a>
                </div>
            </div>
            <div class="hero-media">
                <img src="assets/images/hero/hero-robotics.jpg" alt="Industrial automation facility and advanced robotics" id="hero-img">
            </div>
        </div>
    </section>

    <!-- 3. Metrics Ribbon -->
    <div class="metrics-ribbon">
        <div class="container" style="display:contents;">
            <div class="metric-item">
                <div class="metric-value">99.98%</div>
                <div class="metric-label">Operational Reliability</div>
            </div>
            <div class="metric-item">
                <div class="metric-value">&plusmn;0.02mm</div>
                <div class="metric-label">Repeatable Precision</div>
            </div>
            <div class="metric-item">
                <div class="metric-value">500+</div>
                <div class="metric-label">Enterprise Deployments</div>
            </div>
            <div class="metric-item">
                <div class="metric-value">40+</div>
                <div class="metric-label">Patented Technologies</div>
            </div>
        </div>
    </div>

    <!-- 4. Company Overview & Philosophy -->
    <section class="about-section" id="about">
        <div class="container">
            <div class="section-header">
                <span class="section-badge">Company Overview</span>
                <h2>Pioneering Autonomous Engineering</h2>
                <p>Founded on principles of extreme mechanical precision and cognitive software architecture, ATLAS Robotics delivers turnkey autonomous systems that transform manufacturing productivity, workplace safety, and supply chain velocity worldwide.</p>
            </div>
        </div>
    </section>

    <!-- 5. Robotics Solutions -->
    <section class="solutions-section" id="solutions">
        <div class="container">
            <div class="section-header">
                <span class="section-badge">Turnkey Systems</span>
                <h2>Integrated Robotics Solutions</h2>
                <p>Engineered for mission-critical industrial manufacturing, high-throughput fulfillment, and sub-millimeter quality control.</p>
            </div>
            <div class="solutions-grid" id="solutions-grid">
                <!-- Dynamically rendered via app.js -->
            </div>
        </div>
    </section>

    <!-- 6. Robotics Product Catalogue -->
    <section class="products-section" id="products">
        <div class="container">
            <div class="section-header">
                <span class="section-badge">Hardware & Systems</span>
                <h2>Robotics Product Catalogue</h2>
                <p>Explore our flagship articulated arms, autonomous mobile platforms, vision systems, and automated QA cells.</p>
            </div>
            
            <div class="filter-bar">
                <div class="search-wrapper">
                    <span class="search-icon">&#128269;</span>
                    <input type="text" class="search-input" id="product-search" placeholder="Search robotics hardware by model, spec or category...">
                </div>
                <div class="category-filters" id="category-filters">
                    <button class="filter-pill active" data-category="all">All Products</button>
                    <button class="filter-pill" data-category="industrial_arms">Industrial Arms</button>
                    <button class="filter-pill" data-category="amr">Autonomous Mobile</button>
                    <button class="filter-pill" data-category="vision">Vision & AI</button>
                    <button class="filter-pill" data-category="cobots">Collaborative Cobots</button>
                    <button class="filter-pill" data-category="assembly">Precision Assembly</button>
                </div>
            </div>

            <div class="products-grid" id="products-grid">
                <!-- Dynamically rendered via app.js -->
            </div>
        </div>
    </section>

    <!-- 7. Industry Applications -->
    <section class="applications-section" id="applications">
        <div class="container">
            <div class="section-header">
                <span class="section-badge">Global Deployments</span>
                <h2>Industry Applications</h2>
                <p>Deploying resilient autonomous systems across high-consequence global industries.</p>
            </div>
            <div class="applications-grid">
                <div class="app-card">
                    <h3>Automotive Manufacturing</h3>
                    <p>High-speed body-in-white welding, robotic painting, windshield installation, and powertrain component assembly.</p>
                </div>
                <div class="app-card">
                    <h3>Aerospace Engineering</h3>
                    <p>Sub-millimeter drilling, composite carbon-fiber layup, turbine blade inspection, and heavy airframe riveting.</p>
                </div>
                <div class="app-card">
                    <h3>Electronics & Semiconductor</h3>
                    <p>Cleanroom ISO Class 5 micro-assembly, wafer handling, high-speed SMT pick-and-place, and automated PCB QA.</p>
                </div>
                <div class="app-card">
                    <h3>Healthcare & Medical Devices</h3>
                    <p>Sterile surgical instrument packaging, robotic catheter assembly, and pharmaceutical sorting automation.</p>
                </div>
                <div class="app-card">
                    <h3>High-Throughput Logistics</h3>
                    <p>Autonomous pallet transport, dynamic AMR cross-docking, automated goods-to-person picking, and sorting.</p>
                </div>
                <div class="app-card">
                    <h3>Precision Agriculture</h3>
                    <p>Autonomous greenhouse harvesting, automated seedling grafting, and optical grading systems.</p>
                </div>
            </div>
        </div>
    </section>

    <!-- 8. Research & Innovation -->
    <section class="research-section" id="research">
        <div class="container">
            <div class="section-header">
                <span class="section-badge">R&D Capabilities</span>
                <h2>Research & Innovation</h2>
                <p>Advancing artificial intelligence, neural machine vision, and real-time trajectory optimization.</p>
            </div>
            <div class="applications-grid">
                <div class="app-card">
                    <h3>Neuromorphic Vision</h3>
                    <p>Sub-millisecond event-based camera processing for extreme-velocity robotic tracking and micro-defect classification.</p>
                </div>
                <div class="app-card">
                    <h3>LiDAR SLAM 3.0</h3>
                    <p>Multi-sensor dynamic localization enabling robust autonomous navigation in changing factory environments without beacons.</p>
                </div>
                <div class="app-card">
                    <h3>Zero-Backlash Gearboxes</h3>
                    <p>Patented harmonic planetary drivetrains achieving industry-leading repeatability under continuous 24/7 load cycles.</p>
                </div>
            </div>
        </div>
    </section>

    <!-- 9. Featured Engineering Projects -->
    <section class="projects-section" id="projects">
        <div class="container">
            <div class="section-header">
                <span class="section-badge">Case Studies</span>
                <h2>Featured Engineering Projects</h2>
                <p>Demonstrated impact across large-scale industrial manufacturing installations.</p>
            </div>
            <div class="projects-grid">
                <div class="project-card">
                    <div class="project-stat">420%</div>
                    <h3>Gigafactory Battery Assembly</h3>
                    <p>Deployed 48 ATLAS Apex-6 arms for prismatic cell welding and automated pack sealing, boosting line throughput by 420%.</p>
                </div>
                <div class="project-card">
                    <div class="project-stat">99.99%</div>
                    <h3>Autonomous Fulfillment Center</h3>
                    <p>Orchestrated fleet of 120 ATLAS Strider AMRs operating continuously across 850,000 sq ft logistics facility with 0 incidents.</p>
                </div>
                <div class="project-card">
                    <div class="project-stat">&lt;0.001%</div>
                    <h3>Aerospace Turbine QA Cell</h3>
                    <p>Integrated ATLAS OptiScan vision and Sentinel QA cells to automate 100% inspection of titanium turbine airfoils with zero escapes.</p>
                </div>
            </div>
        </div>
    </section>

    <!-- 10. Why Choose ATLAS -->
    <section class="why-section" id="why-us">
        <div class="container">
            <div class="section-header">
                <span class="section-badge">Engineering Advantage</span>
                <h2>Why Global Manufacturers Choose ATLAS</h2>
                <p>Proven reliability, engineering pedigree, and dedicated global field application support.</p>
            </div>
            <div class="why-grid">
                <div class="why-card">
                    <h3>Extreme Precision</h3>
                    <p>Guaranteed &plusmn;0.02mm repeatable positioning with absolute optical encoders on every articulated joint.</p>
                </div>
                <div class="why-card">
                    <h3>Turnkey Integration</h3>
                    <p>Native fieldbus protocols (EtherCAT, PROFINET, Modbus TCP) ensuring seamless PLC and SCADA integration.</p>
                </div>
                <div class="why-card">
                    <h3>Enterprise Safety</h3>
                    <p>SIL3 / Ple certified safety architectures with redundant emergency braking and optical perimeter monitoring.</p>
                </div>
                <div class="why-card">
                    <h3>24/7 Global Support</h3>
                    <p>Direct Tier-3 field engineering assistance, rapid spares logistics, and predictive telemetry monitoring.</p>
                </div>
            </div>
        </div>
    </section>

    <!-- 11. Customer Perspectives -->
    <section class="testimonials-section" id="testimonials">
        <div class="container">
            <div class="section-header">
                <span class="section-badge">Illustrative Feedback</span>
                <h2>Customer Perspectives</h2>
                <p>Illustrative feedback from plant engineering and operational leaders.</p>
            </div>
            <div class="testimonials-grid">
                <div class="testimonial-card">
                    <p>"Deploying ATLAS articulated arms transformed our powertrain machining cell. Repeatability remained razor sharp even under continuous round-the-clock casting cycles."</p>
                    <div class="author-info">
                        <div class="author-avatar">DK</div>
                        <div>
                            <strong>David Keller</strong><br>
                            <small class="spec-label">VP of Advanced Manufacturing (Illustrative)</small>
                        </div>
                    </div>
                </div>
                <div class="testimonial-card">
                    <p>"The Strider AMR fleet navigated our dynamic assembly floor effortlessly. The SLAM mapping handled forklift traffic and pallet reconfiguration with zero downtime."</p>
                    <div class="author-info">
                        <div class="author-avatar">SL</div>
                        <div>
                            <strong>Sarah Lin</strong><br>
                            <small class="spec-label">Director of Automation Engineering (Illustrative)</small>
                        </div>
                    </div>
                </div>
                <div class="testimonial-card">
                    <p>"The OptiScan AI vision system caught micro-fractures in composite aerospace panels that traditional optical cameras missed. An indispensable quality milestone."</p>
                    <div class="author-info">
                        <div class="author-avatar">MR</div>
                        <div>
                            <strong>Marcus Thorne</strong><br>
                            <small class="spec-label">Principal Quality Fellow (Illustrative)</small>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <!-- 12. Contact & Consultation -->
    <section class="contact-section" id="contact">
        <div class="container">
            <div class="section-header">
                <span class="section-badge">Engineering Engagement</span>
                <h2>Request an Engineering Consultation</h2>
                <p>Connect with our senior automation architects to evaluate cycle times, payload requirements, and system integration feasibility.</p>
            </div>
            
            <div class="form-wrapper">
                <form class="consultation-form" id="consultation-form">
                    <div class="form-grid">
                        <div class="form-group">
                            <label for="full-name">Full Name *</label>
                            <input type="text" class="form-control" id="full-name" placeholder="e.g. Dr. Elena Vance" required>
                        </div>
                        <div class="form-group">
                            <label for="email-address">Work Email *</label>
                            <input type="email" class="form-control" id="email-address" placeholder="name@enterprise.com" required>
                        </div>
                        <div class="form-group">
                            <label for="company-name">Company / Organization *</label>
                            <input type="text" class="form-control" id="company-name" placeholder="e.g. Apex Dynamics Ltd" required>
                        </div>
                        <div class="form-group">
                            <label for="industry-select">Industry *</label>
                            <select class="form-control" id="industry-select" required>
                                <option value="">Select Target Industry</option>
                                <option value="automotive">Automotive Manufacturing</option>
                                <option value="aerospace">Aerospace & Defense</option>
                                <option value="electronics">Electronics & Semiconductor</option>
                                <option value="logistics">Warehouse & Logistics</option>
                                <option value="healthcare">Medical Device Automation</option>
                                <option value="other">Other Industrial Sector</option>
                            </select>
                        </div>
                        <div class="form-group full-width">
                            <label for="solution-select">Solution of Interest *</label>
                            <select class="form-control" id="solution-select" required>
                                <option value="">Select Primary System Architecture</option>
                                <option value="industrial_arms">Industrial Robotic Arms (Apex Series)</option>
                                <option value="amr">Autonomous Mobile Robots (Strider Series)</option>
                                <option value="vision">AI Vision & Inspection (OptiScan Series)</option>
                                <option value="cobots">Collaborative Cobots (Nexus Series)</option>
                                <option value="assembly">Precision Micro-Assembly Cells</option>
                                <option value="turnkey">Full Turnkey Factory Automation</option>
                            </select>
                        </div>
                        <div class="form-group full-width">
                            <label for="project-description">Project Scope & Technical Specifications *</label>
                            <textarea class="form-control" id="project-description" placeholder="Describe required payload, cycle time, envelope dimensions, and environmental constraints..." required></textarea>
                        </div>
                    </div>
                    <button type="submit" class="btn btn-primary btn-block" style="width:100%;" id="btn-submit-consultation">Submit Consultation Request</button>
                    <div class="form-feedback" id="form-feedback"></div>
                </form>
            </div>
        </div>
    </section>

    <!-- 13. Product Details Modal -->
    <div class="modal-overlay" id="product-modal">
        <div class="modal-dialog">
            <button class="modal-close" id="modal-close" aria-label="Close modal">&times;</button>
            <div class="modal-content-inner">
                <div class="modal-media">
                    <img src="assets/images/products/atlas-apex-6.jpg" alt="Industrial robotics specification view" id="modal-product-image">
                </div>
                <span class="product-category-tag" id="modal-product-category"></span>
                <h2 id="modal-product-title" style="margin-top:0.5rem;"></h2>
                <p id="modal-product-desc"></p>
                <h4 style="margin-top:1.5rem; margin-bottom:0.5rem; color:var(--text-primary);">Engineering Specifications</h4>
                <table class="modal-specs-table" id="modal-specs-table">
                    <!-- Populated dynamically via app.js -->
                </table>
                <div style="display:flex; gap:1rem; margin-top:2rem;">
                    <a href="#contact" class="btn btn-primary" onclick="closeProductModal();" style="flex:1;">Inquire About This Model</a>
                    <button class="btn btn-secondary" onclick="closeProductModal();">Back to Catalogue</button>
                </div>
            </div>
        </div>
    </div>

    <!-- 14. Site Footer -->
    <footer class="site-footer" id="footer">
        <div class="container">
            <div class="footer-grid">
                <div class="footer-col">
                    <a href="#hero" class="brand-logo" style="margin-bottom:1rem;">
                        <span class="brand-icon">A</span>
                        <span>{app_name}</span>
                    </a>
                    <p style="font-size:0.9rem;">Global leader in advanced autonomous robotics, precision articulated workcells, and intelligent machine vision systems.</p>
                </div>
                <div class="footer-col">
                    <h4>Solutions</h4>
                    <ul class="footer-links">
                        <li><a href="#solutions">Industrial Robotic Arms</a></li>
                        <li><a href="#solutions">Autonomous Mobile Robots</a></li>
                        <li><a href="#solutions">AI Machine Vision</a></li>
                        <li><a href="#solutions">Collaborative Cobots</a></li>
                    </ul>
                </div>
                <div class="footer-col">
                    <h4>Industries</h4>
                    <ul class="footer-links">
                        <li><a href="#applications">Automotive</a></li>
                        <li><a href="#applications">Aerospace</a></li>
                        <li><a href="#applications">Electronics</a></li>
                        <li><a href="#applications">Logistics</a></li>
                    </ul>
                </div>
                <div class="footer-col">
                    <h4>Headquarters</h4>
                    <p style="font-size:0.9rem; color:var(--text-secondary);">
                        ATLAS Robotics Global Engineering Center<br>
                        Industrial Technology Park, Suite 400<br>
                        contact@atlas-robotics.corp
                    </p>
                </div>
            </div>
            <div class="footer-bottom">
                <div>&copy; 2026 {app_name} Corp. All rights reserved. Precision engineering demonstration.</div>
                <div>ISO 9001:2015 &amp; ISO 13849-1 Certified Industrial Architectures</div>
            </div>
        </div>
    </footer>

    <script src="app.js"></script>
</body>
</html>"""
        html_path.write_text(html_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(html_path, ws, generator="foundation_scaffolder")

    # 4. app.js
    js_path = ws / "app.js"
    if not js_path.exists() or js_path.stat().st_size < 50:
        js_content = r"""/**
 * ATLAS Robotics - Interactive Client Application Logic
 * Implements dynamic rendering, real-time catalog search & category filtering,
 * modal dialog inspection, backdrop/ESC dismissal, and consultation form validation.
 */

// 1. Authoritative Robotics Solutions Data
const solutions = [
    {
        id: "sol-arms",
        title: "Industrial Robotic Arms",
        category: "Articulated Systems",
        description: "Heavy-payload, high-speed multi-axis articulated arms engineered for precision spot welding, plasma cutting, palletizing, and automotive body assembly.",
        capabilities: ["±0.02mm Precision", "Up to 500kg Payload", "IP67 Washdown", "Continuous 24/7 Duty"],
        image: "assets/images/solutions/sol-arms.jpg"
    },
    {
        id: "sol-amr",
        title: "Autonomous Mobile Robots",
        category: "Intralogistics Fleet",
        description: "Intelligent autonomous mobile platforms featuring LiDAR SLAM navigation to move materials safely through dynamic manufacturing floors without fixed tracks.",
        capabilities: ["LiDAR SLAM 3.0", "1500kg Tow Capacity", "Sub-2cm Docking", "Fleet Traffic Manager"],
        image: "assets/images/solutions/sol-amr.jpg"
    },
    {
        id: "sol-vision",
        title: "AI Machine Vision Systems",
        category: "Sensors & Optical QA",
        description: "High-resolution neural camera systems with sub-millisecond onboard TPU inference to detect microscopic manufacturing defects at full production speeds.",
        capabilities: ["4K 120fps Cameras", "Onboard Neural TPU", "<10ms Defect Alert", "Multi-Angle Lighting"],
        image: "assets/images/solutions/sol-vision.jpg"
    },
    {
        id: "sol-cobot",
        title: "Collaborative Robots (Cobots)",
        category: "Human-Robot Collaboration",
        description: "Lightweight, power-and-force limited collaborative robots with integrated joint torque sensing for safe operation side-by-side with human line technicians.",
        capabilities: ["ISO 10218-1 Certified", "Direct Teach Mode", "Zero Safety Caging", "Collision Auto-Halt"],
        image: "assets/images/solutions/sol-cobot.jpg"
    },
    {
        id: "sol-assembly",
        title: "Precision Assembly Automation",
        category: "Micro-Manufacturing",
        description: "High-accuracy robotic assembly cells designed for semiconductor wafer handling, medical device fabrication, and intricate micro-electronic placement.",
        capabilities: ["±5µm Placement", "Cleanroom Class 5", "Dual Vacuum Grippers", "Vision Guided Alignment"],
        image: "assets/images/solutions/sol-assembly.jpg"
    },
    {
        id: "sol-inspection",
        title: "Autonomous Inspection Systems",
        category: "Quality Assurance",
        description: "Turnkey automated scanning cells equipped with multi-spectral lasers and 3D profilometry to perform 100% in-line dimensional inspection.",
        capabilities: ["3D Laser Profiling", "Full Digital Twin", "100% In-Line Verification", "Instant SPC Analytics"],
        image: "assets/images/solutions/sol-inspection.jpg"
    }
];

// 2. Authoritative Robotics Products Catalogue
const products = [
    {
        id: "atlas-apex-6",
        title: "ATLAS Apex-6 Articulated Arm",
        category: "industrial_arms",
        categoryName: "Industrial Arms",
        description: "Flagship 6-axis industrial robot delivering rapid cycle times and exceptional rigidity for automotive spot welding and heavy material handling.",
        image: "assets/images/products/atlas-apex-6.jpg",
        specs: {
            "Payload Capacity": "50 kg",
            "Reach Radius": "2,050 mm",
            "Repeatability": "±0.02 mm",
            "Axis Degrees": "6 Degrees of Freedom",
            "Mounting": "Floor, Ceiling, Incline",
            "Ingress Protection": "IP67 Submersible Wrist"
        },
        capabilities: ["Zero-Backlash Drivetrain", "Continuous Duty Cycle", "EtherCAT Native Interface"]
    },
    {
        id: "atlas-strider-amr",
        title: "ATLAS Strider AMR-1000",
        category: "amr",
        categoryName: "Autonomous Mobile",
        description: "Heavy-duty autonomous mobile robot designed for pallet handling, warehouse logistics, and automated cross-docking in dynamic environments.",
        image: "assets/images/products/atlas-strider-amr.jpg",
        specs: {
            "Payload Capacity": "1,000 kg",
            "Navigation System": "LiDAR SLAM + 3D ToF Vision",
            "Max Velocity": "2.2 m/s",
            "Battery Runtime": "10 Hours Continuous",
            "Charge Time": "45 Mins (Fast Opportunity Dock)",
            "Safety Rating": "SIL3 / PLe Dual Scanners"
        },
        capabilities: ["Dynamic Obstacle Avoidance", "Automatic Floor Docking", "Fleet Cloud Telemetry"]
    },
    {
        id: "atlas-optiscan",
        title: "ATLAS OptiScan AI Vision Head",
        category: "vision",
        categoryName: "Vision & AI",
        description: "Neural machine vision inspection sensor integrating dual 4K Sony Pregius sensors and real-time deep learning inference for zero-defect production.",
        image: "assets/images/products/atlas-optiscan.jpg",
        specs: {
            "Sensor Resolution": "Dual 4K (8.3 MP per sensor)",
            "Frame Rate": "120 FPS Real-time",
            "Neural Engine": "60 TOPS Integrated TPU",
            "Defect Detection": "<0.01 mm Minimum Flaw Size",
            "Field of View": "120° Wide Angle with Telephoto Center",
            "Connectivity": "10 Gigabit Ethernet (GigE Vision)"
        },
        capabilities: ["Self-Training Classifier", "Instant Reject Trigger", "Digital Twin Traceability"]
    },
    {
        id: "atlas-nexus-7",
        title: "ATLAS Nexus-7 Collaborative Cobot",
        category: "cobots",
        categoryName: "Collaborative Cobots",
        description: "Next-generation 7-axis collaborative robot with dual torque sensors in every joint, allowing safe and fluid collaboration with human workers.",
        image: "assets/images/products/atlas-nexus-7.jpg",
        specs: {
            "Payload Capacity": "15 kg",
            "Reach Radius": "1,300 mm",
            "Torque Sensitivity": "0.1 Nm Threshold",
            "Degrees of Freedom": "7-Axis Kinematics",
            "Weight": "28.5 kg Lightweight Aluminum",
            "Safety Standards": "ISO 13849-1, ISO 10218-1"
        },
        capabilities: ["Direct Lead-Through Teaching", "Obstacle Reflex Braking", "Modular End-Effector System"]
    },
    {
        id: "atlas-microassembler",
        title: "ATLAS MicroAssembler Pro",
        category: "assembly",
        categoryName: "Precision Assembly",
        description: "Ultra-precise robotic assembly workstation engineered for semiconductor packaging, optical lens alignment, and delicate micro-mechanical insertion.",
        image: "assets/images/products/atlas-microassembler.jpg",
        specs: {
            "Positioning Accuracy": "±5 µm (Microns)",
            "Work Envelope": "400 x 400 x 200 mm",
            "Pick Rate": "Up to 140 Cycles / Minute",
            "Force Sensing": "0.01 N Resolution",
            "Cleanroom Rating": "ISO Class 5 Certified",
            "Vision Guided": "Integrated Coaxial Micro-Camera"
        },
        capabilities: ["Dual Vacuum Chucks", "Anti-Static Dissipative Enclosure", "Sub-Millimeter Micro-Placement"]
    },
    {
        id: "atlas-sentinel",
        title: "ATLAS Sentinel Automated QA Cell",
        category: "vision",
        categoryName: "Inspection Systems",
        description: "Full-envelope automated 3D dimensional quality control inspection cell designed to verify complex cast, forged, and machined industrial parts.",
        image: "assets/images/products/atlas-sentinel.jpg",
        specs: {
            "Part Envelope": "1,200 x 1,200 x 800 mm",
            "Measurement Uncertainty": "3 µm + L/300",
            "Scan Speed": "2,000,000 Points / Second",
            "Laser Class": "Blue Laser Class 2M Safe",
            "Reporting": "Direct CAD Overlay & Heatmap",
            "Loading": "Automated Pneumatic Clamping Bed"
        },
        capabilities: ["Automated GD&T Verification", "CAD Deviation Heatmaps", "Direct Reject Sort Integration"]
    }
];

// Active State
let currentCategory = "all";
let searchQuery = "";

// DOM Elements
document.addEventListener("DOMContentLoaded", () => {
    renderSolutions();
    renderProducts();
    initFilters();
    initSearch();
    initModal();
    initConsultationForm();
    initMobileMenu();
});

// Render Solutions Grid
function renderSolutions() {
    const grid = document.getElementById("solutions-grid");
    if (!grid) return;
    grid.innerHTML = solutions.map(sol => `
        <article class="solution-card" data-solution-id="${sol.id}">
            <div class="solution-image">
                <img src="${sol.image}" alt="${sol.title}">
            </div>
            <div class="solution-body">
                <span class="solution-category">${sol.category}</span>
                <h3>${sol.title}</h3>
                <p>${sol.description}</p>
                <div class="solution-capabilities">
                    ${sol.capabilities.map(cap => `<span class="cap-pill">${cap}</span>`).join("")}
                </div>
            </div>
        </article>
    `).join("");
}

// Render Products Grid
function renderProducts() {
    const grid = document.getElementById("products-grid");
    if (!grid) return;

    const filtered = products.filter(p => {
        const matchesCat = (currentCategory === "all") || (p.category === currentCategory);
        const matchesQuery = !searchQuery || 
            p.title.toLowerCase().includes(searchQuery) ||
            p.description.toLowerCase().includes(searchQuery) ||
            p.categoryName.toLowerCase().includes(searchQuery) ||
            p.capabilities.some(c => c.toLowerCase().includes(searchQuery));
        return matchesCat && matchesQuery;
    });

    if (filtered.length === 0) {
        grid.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 4rem 1rem;">
                <h3 style="color:var(--text-secondary); margin-bottom:0.5rem;">No robotics hardware matched your criteria.</h3>
                <p>Try refining your search keyword or selecting a different category filter.</p>
                <button class="btn btn-secondary" onclick="resetFilters();" style="margin-top:1rem;">Reset Search Filters</button>
            </div>
        `;
        return;
    }

    grid.innerHTML = filtered.map(prod => `
        <article class="product-card" data-product-id="${prod.id}" data-category="${prod.category}">
            <div class="product-image">
                <img src="${prod.image}" alt="${prod.title}">
            </div>
            <div class="product-body">
                <div class="product-header">
                    <span class="product-category-tag">${prod.categoryName}</span>
                </div>
                <h3 class="product-title">${prod.title}</h3>
                <p>${prod.description}</p>
                <ul class="specs-list">
                    ${Object.entries(prod.specs).slice(0, 3).map(([k, v]) => `
                        <li class="spec-row">
                            <span class="spec-label">${k}:</span>
                            <span class="spec-val">${v}</span>
                        </li>
                    `).join("")}
                </ul>
                <button class="btn btn-primary btn-details" onclick="openProductModal('${prod.id}');">View Details</button>
            </div>
        </article>
    `).join("");
}

// Category Filter Handlers
function initFilters() {
    const pills = document.querySelectorAll(".filter-pill");
    pills.forEach(pill => {
        pill.addEventListener("click", () => {
            pills.forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            currentCategory = pill.getAttribute("data-category") || "all";
            renderProducts();
        });
    });
}

// Search Filter Handler
function initSearch() {
    const input = document.getElementById("product-search");
    if (!input) return;
    input.addEventListener("input", (e) => {
        searchQuery = (e.target.value || "").trim().toLowerCase();
        renderProducts();
    });
}

function resetFilters() {
    searchQuery = "";
    currentCategory = "all";
    const input = document.getElementById("product-search");
    if (input) input.value = "";
    const pills = document.querySelectorAll(".filter-pill");
    pills.forEach(p => {
        if (p.getAttribute("data-category") === "all") p.classList.add("active");
        else p.classList.remove("active");
    });
    renderProducts();
}

// Modal Inspection Handler
function initModal() {
    const modal = document.getElementById("product-modal");
    const closeBtn = document.getElementById("modal-close");
    if (!modal) return;

    if (closeBtn) {
        closeBtn.addEventListener("click", closeProductModal);
    }

    // Backdrop dismissal
    modal.addEventListener("click", (e) => {
        if (e.target === modal) {
            closeProductModal();
        }
    });

    // Escape key dismissal
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && modal.classList.contains("active")) {
            closeProductModal();
        }
    });
}

function openProductModal(productId) {
    const prod = products.find(p => p.id === productId);
    if (!prod) return;

    const modal = document.getElementById("product-modal");
    const img = document.getElementById("modal-product-image");
    const title = document.getElementById("modal-product-title");
    const cat = document.getElementById("modal-product-category");
    const desc = document.getElementById("modal-product-desc");
    const table = document.getElementById("modal-specs-table");

    if (img) { img.src = prod.image; img.alt = prod.title; }
    if (title) title.innerText = prod.title;
    if (cat) cat.innerText = prod.categoryName;
    if (desc) desc.innerText = prod.description;

    if (table) {
        table.innerHTML = Object.entries(prod.specs).map(([k, v]) => `
            <tr>
                <td>${k}</td>
                <td>${v}</td>
            </tr>
        `).join("");
    }

    modal.classList.add("active");
    document.body.style.overflow = "hidden";
}

function closeProductModal() {
    const modal = document.getElementById("product-modal");
    if (modal) {
        modal.classList.remove("active");
        document.body.style.overflow = "";
    }
}

// Consultation Form Submission & Validation
function initConsultationForm() {
    const form = document.getElementById("consultation-form");
    const feedback = document.getElementById("form-feedback");
    if (!form || !feedback) return;

    form.addEventListener("submit", (e) => {
        e.preventDefault();

        const name = (document.getElementById("full-name")?.value || "").trim();
        const email = (document.getElementById("email-address")?.value || "").trim();
        const company = (document.getElementById("company-name")?.value || "").trim();
        const industry = (document.getElementById("industry-select")?.value || "").trim();
        const solution = (document.getElementById("solution-select")?.value || "").trim();
        const scope = (document.getElementById("project-description")?.value || "").trim();

        if (!name || !email || !company || !industry || !solution || !scope) {
            feedback.className = "form-feedback error";
            feedback.innerText = "Please complete all required fields before submitting your consultation inquiry.";
            feedback.style.display = "block";
            return;
        }

        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            feedback.className = "form-feedback error";
            feedback.innerText = "Please provide a valid corporate email address.";
            feedback.style.display = "block";
            return;
        }

        // Display validated demonstration feedback
        feedback.className = "form-feedback success";
        feedback.innerHTML = `
            <strong>Consultation Request Validated (Demonstration Mode)</strong><br>
            Thank you, <strong>${name}</strong> from <strong>${company}</strong>. Your engineering enquiry regarding <em>${solution}</em> has been successfully received and validated in frontend demonstration mode. No live appointment has been scheduled.
        `;
        feedback.style.display = "block";
        form.reset();
    });
}

// Mobile Menu Toggle
function initMobileMenu() {
    const btn = document.getElementById("mobile-menu-btn");
    const nav = document.querySelector(".nav-links");
    if (!btn || !nav) return;

    btn.addEventListener("click", () => {
        const isShown = nav.style.display === "flex";
        nav.style.display = isShown ? "none" : "flex";
        if (!isShown) {
            nav.style.flexDirection = "column";
            nav.style.position = "absolute";
            nav.style.top = "76px";
            nav.style.left = "0";
            nav.style.width = "100%";
            nav.style.background = "var(--bg-main)";
            nav.style.padding = "1.5rem";
            nav.style.borderBottom = "1px solid var(--border-color)";
        }
    });
}
"""
        js_path.write_text(js_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(js_path, ws, generator="foundation_scaffolder")

    return True


def _seed_restaurant_foundation(
    ws: Path,
    prompt: str,
    contract: Optional[Any],
    design_brief: Optional[Any],
) -> bool:
    from core.design_intelligence import DesignBriefGenerator
    from tools.security import WorkspaceOwnershipManifest

    cuisine = getattr(contract, "cuisine_subtype", "") or getattr(design_brief, "cuisine_subtype", "") or DesignBriefGenerator.detect_cuisine_subtype(prompt)
    is_indian = cuisine == "Contemporary Indian"

    app_name = "Saffron & Stone"
    title = "Saffron & Stone — Contemporary Indian Kitchen" if is_indian else "Saffron & Stone — Artisanal Mediterranean Dining"
    desc_text = "Saffron & Stone: Contemporary Indian kitchen celebrating clay oven tandoori specialties, dum biryani, artisanal breads, and heritage spices." if is_indian else "Saffron & Stone: Artisanal Mediterranean dining with wood-fired hearth cooking, sommelier pairings, and private dining."

    # 1. package.json
    pkg_path = ws / "package.json"
    if not pkg_path.exists():
        pkg_data = {
            "name": "saffron-stone-restaurant",
            "version": "1.0.0",
            "description": f"{title} Web Portal",
            "main": "app.js",
            "scripts": {
                "start": "npx http-server -p 8080",
                "serve": "npx http-server -p 8080"
            }
        }
        pkg_path.write_text(json.dumps(pkg_data, indent=2), encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(pkg_path, ws, generator="foundation_scaffolder")
        logger.info(f"FoundationScaffolder: created {pkg_path.name}")

    # 2. style.css (Terracotta, Saffron Gold, Charcoal Obsidian, Warm Cream + 1024px Tablet Navigation Refinement)
    css_path = ws / "style.css"
    if not css_path.exists() or css_path.stat().st_size < 50:
        css_content = """/* ==========================================================================
   Saffron & Stone — Dining Design System
   ========================================================================== */

:root {
    --color-primary: #8b3a1a;        /* Warm Terracotta Brick */
    --color-primary-hover: #a0431f;
    --color-accent: #d97706;         /* Royal Golden Saffron */
    --color-accent-hover: #b45309;
    --color-secondary: #2b1810;      /* Deep Obsidian Charcoal */
    --bg-main: #141110;              /* Dark Warm Slate */
    --bg-surface: #1e1815;           /* Rich Hearth Surface */
    --bg-card: #27201c;
    --bg-warm: #322823;
    --text-primary: #fcf8f2;         /* Warm Ivory */
    --text-secondary: #c9b8a8;       /* Warm Sandstone */
    --text-muted: #8c7d70;           /* Soft Terracotta Haze */
    --border-color: #3d312a;
    --border-focus: #d97706;
    --radius-sm: 6px;
    --radius-md: 12px;
    --radius-lg: 20px;
    --shadow-sm: 0 2px 6px rgba(0, 0, 0, 0.3);
    --shadow-md: 0 6px 18px rgba(0, 0, 0, 0.4);
    --shadow-lg: 0 12px 32px rgba(0, 0, 0, 0.55);
    --font-heading: 'Playfair Display', Georgia, 'Times New Roman', serif;
    --font-body: 'Inter', system-ui, -apple-system, sans-serif;
    --transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

*, *::before, *::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

html {
    scroll-behavior: smooth;
    font-size: 16px;
    overflow-x: hidden;
    max-width: 100vw;
}

body {
    font-family: var(--font-body);
    background-color: var(--bg-main);
    color: var(--text-primary);
    line-height: 1.6;
    overflow-x: hidden;
}

img {
    max-width: 100%;
    height: auto;
    display: block;
}

a {
    color: inherit;
    text-decoration: none;
}

button {
    font-family: inherit;
    cursor: pointer;
    border: none;
    background: none;
}

.container {
    width: 100%;
    max-width: 1240px;
    margin: 0 auto;
    padding: 0 1.5rem;
}

.section-header {
    text-align: center;
    max-width: 720px;
    margin: 0 auto 3rem auto;
}

.section-header .tagline {
    color: var(--color-accent);
    font-weight: 700;
    text-transform: uppercase;
    font-size: 0.85rem;
    letter-spacing: 0.15em;
    margin-bottom: 0.5rem;
    display: block;
}

.section-header h2 {
    font-family: var(--font-heading);
    font-size: clamp(2rem, 4vw, 2.75rem);
    color: var(--text-primary);
    margin-bottom: 0.75rem;
    line-height: 1.2;
}

.section-header p {
    color: var(--text-secondary);
    font-size: 1.1rem;
}

/* Navigation */
.navbar {
    position: sticky;
    top: 0;
    z-index: 100;
    background: rgba(20, 17, 16, 0.94);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border-color);
    padding: 1rem 0;
}

.nav-container {
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.brand-logo {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    font-family: var(--font-heading);
    font-size: 1.4rem;
    font-weight: 700;
    color: var(--text-primary);
    white-space: nowrap;
}

.brand-mark {
    width: 36px;
    height: 36px;
    background: linear-gradient(135deg, var(--color-accent), var(--color-primary));
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    font-weight: 800;
    font-size: 1.1rem;
}

.nav-links {
    display: flex;
    align-items: center;
    gap: 2rem;
    list-style: none;
}

.nav-links a {
    font-weight: 500;
    color: var(--text-secondary);
    transition: var(--transition);
    white-space: nowrap;
}

.nav-links a:hover {
    color: var(--color-accent);
}

.nav-actions {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.btn-primary {
    background: linear-gradient(135deg, var(--color-accent), var(--color-primary));
    color: #ffffff;
    padding: 0.75rem 1.6rem;
    border-radius: var(--radius-sm);
    font-weight: 600;
    font-size: 0.95rem;
    transition: var(--transition);
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    box-shadow: 0 4px 14px rgba(217, 119, 6, 0.25);
    white-space: nowrap;
}

.btn-primary:hover {
    opacity: 0.92;
    transform: translateY(-2px);
}

.btn-outline {
    border: 1px solid var(--color-accent);
    color: var(--color-accent);
    padding: 0.7rem 1.4rem;
    border-radius: var(--radius-sm);
    font-weight: 600;
    transition: var(--transition);
    white-space: nowrap;
}

.btn-outline:hover {
    background: var(--color-accent);
    color: #141110;
}

.hamburger-btn {
    display: none;
    flex-direction: column;
    gap: 5px;
    padding: 0.5rem;
    cursor: pointer;
}

.hamburger-btn span {
    width: 24px;
    height: 2px;
    background: var(--text-primary);
    transition: var(--transition);
}

/* Hero */
.hero {
    position: relative;
    min-height: 85vh;
    display: flex;
    align-items: center;
    background: linear-gradient(rgba(20, 17, 16, 0.78), rgba(20, 17, 16, 0.92)), url('assets/images/hero/hero-restaurant.jpg') center/cover no-repeat;
    padding: 6rem 0;
    border-bottom: 1px solid var(--border-color);
}

.hero-content {
    max-width: 760px;
}

.hero-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    background: rgba(217, 119, 6, 0.15);
    border: 1px solid rgba(217, 119, 6, 0.35);
    color: var(--color-accent);
    padding: 0.35rem 1rem;
    border-radius: 999px;
    font-size: 0.85rem;
    font-weight: 600;
    margin-bottom: 1.5rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}

.hero h1 {
    font-family: var(--font-heading);
    font-size: clamp(2.5rem, 5.5vw, 4rem);
    color: var(--text-primary);
    line-height: 1.15;
    margin-bottom: 1.25rem;
}

.hero p {
    font-size: 1.2rem;
    color: var(--text-secondary);
    margin-bottom: 2.25rem;
    line-height: 1.7;
}

.hero-actions {
    display: flex;
    gap: 1.25rem;
    flex-wrap: wrap;
}

/* Story Section */
.story {
    padding: 6rem 0;
    border-bottom: 1px solid var(--border-color);
    background: var(--bg-surface);
}

.story-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4rem;
    align-items: center;
}

.story-image img {
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-lg);
    border: 1px solid var(--border-color);
}

.story-text h2 {
    font-family: var(--font-heading);
    font-size: 2.4rem;
    margin-bottom: 1.25rem;
    color: var(--text-primary);
}

.story-text p {
    color: var(--text-secondary);
    font-size: 1.05rem;
    margin-bottom: 1.25rem;
    line-height: 1.7;
}

.pillars-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 1.5rem;
    margin-top: 2.5rem;
}

.pillar-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 1.5rem;
    transition: var(--transition);
}

.pillar-card:hover {
    border-color: var(--color-accent);
    transform: translateY(-3px);
}

.pillar-card h3 {
    font-family: var(--font-heading);
    font-size: 1.2rem;
    margin-bottom: 0.5rem;
    color: var(--color-accent);
}

.pillar-card p {
    font-size: 0.95rem;
    color: var(--text-secondary);
}

/* Menu Section */
.menu {
    padding: 6rem 0;
    border-bottom: 1px solid var(--border-color);
    background: var(--bg-main);
}

.menu-controls {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    margin-bottom: 3rem;
}

.menu-search-box {
    max-width: 450px;
    margin: 0 auto;
    width: 100%;
}

.menu-search-box input {
    width: 100%;
    padding: 0.85rem 1.25rem;
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-size: 1rem;
    outline: none;
    transition: var(--transition);
}

.menu-search-box input:focus {
    border-color: var(--color-accent);
    box-shadow: 0 0 0 3px rgba(217, 119, 6, 0.2);
}

.filter-pills {
    display: flex;
    justify-content: center;
    gap: 0.75rem;
    flex-wrap: wrap;
}

.filter-pill {
    padding: 0.55rem 1.25rem;
    border-radius: 999px;
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    font-weight: 500;
    font-size: 0.9rem;
    transition: var(--transition);
    cursor: pointer;
}

.filter-pill:hover,
.filter-pill.active {
    background: var(--color-accent);
    border-color: var(--color-accent);
    color: #141110;
    font-weight: 600;
}

.menu-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 2rem;
}

.dish-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    overflow: hidden;
    transition: var(--transition);
    display: flex;
    flex-direction: column;
}

.dish-card:hover {
    transform: translateY(-4px);
    border-color: var(--color-accent);
    box-shadow: var(--shadow-md);
}

.dish-image {
    position: relative;
    height: 220px;
    overflow: hidden;
}

.dish-image img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: transform 0.4s ease;
}

.dish-card:hover .dish-image img {
    transform: scale(1.05);
}

.dish-tag {
    position: absolute;
    top: 12px;
    right: 12px;
    background: rgba(20, 17, 16, 0.85);
    color: var(--color-accent);
    font-size: 0.75rem;
    font-weight: 700;
    padding: 0.25rem 0.65rem;
    border-radius: 999px;
    border: 1px solid var(--color-accent);
    text-transform: uppercase;
}

.dish-body {
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    flex-grow: 1;
}

.dish-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 0.5rem;
}

.dish-title {
    font-family: var(--font-heading);
    font-size: 1.3rem;
    color: var(--text-primary);
}

.dish-price {
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--color-accent);
}

.dish-desc {
    color: var(--text-secondary);
    font-size: 0.95rem;
    line-height: 1.5;
    margin-bottom: 1.25rem;
    flex-grow: 1;
}

.dish-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-top: 1px solid var(--border-color);
    padding-top: 1rem;
}

.dish-dietary {
    display: flex;
    gap: 0.4rem;
}

.dietary-badge {
    font-size: 0.75rem;
    background: var(--bg-surface);
    color: var(--text-muted);
    padding: 0.2rem 0.5rem;
    border-radius: 4px;
    border: 1px solid var(--border-color);
}

.btn-details {
    color: var(--color-accent);
    font-weight: 600;
    font-size: 0.9rem;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    transition: var(--transition);
}

.btn-details:hover {
    color: #ffffff;
}

/* Chef Profile */
.chef {
    padding: 6rem 0;
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border-color);
}

.chef-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4rem;
    align-items: center;
}

.chef-image img {
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-lg);
    border: 1px solid var(--border-color);
}

.chef-text h2 {
    font-family: var(--font-heading);
    font-size: 2.4rem;
    color: var(--text-primary);
    margin-bottom: 0.5rem;
}

.chef-title {
    color: var(--color-accent);
    font-weight: 600;
    margin-bottom: 1.5rem;
    display: block;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}

.chef-text p {
    color: var(--text-secondary);
    font-size: 1.05rem;
    line-height: 1.7;
    margin-bottom: 1.5rem;
}

.chef-quote {
    border-left: 3px solid var(--color-accent);
    padding-left: 1.5rem;
    font-style: italic;
    color: var(--text-primary);
    font-size: 1.1rem;
    margin-top: 1.5rem;
}

/* Ambience Gallery */
.ambience {
    padding: 6rem 0;
    background: var(--bg-main);
    border-bottom: 1px solid var(--border-color);
}

.gallery-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 1.5rem;
}

.gallery-item {
    position: relative;
    border-radius: var(--radius-md);
    overflow: hidden;
    height: 280px;
    border: 1px solid var(--border-color);
}

.gallery-item img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: transform 0.4s ease;
}

.gallery-item:hover img {
    transform: scale(1.06);
}

.gallery-caption {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    background: linear-gradient(transparent, rgba(20, 17, 16, 0.9));
    padding: 1.5rem 1rem 0.75rem 1rem;
    color: var(--text-primary);
    font-family: var(--font-heading);
    font-size: 1.1rem;
}

/* Private Dining */
.private-dining {
    padding: 6rem 0;
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border-color);
}

.private-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4rem;
    align-items: center;
}

.private-text h2 {
    font-family: var(--font-heading);
    font-size: 2.4rem;
    margin-bottom: 1.25rem;
}

.private-text p {
    color: var(--text-secondary);
    font-size: 1.05rem;
    line-height: 1.7;
    margin-bottom: 1.5rem;
}

.private-specs {
    list-style: none;
    margin-bottom: 2rem;
}

.private-specs li {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    color: var(--text-primary);
    font-weight: 500;
    margin-bottom: 0.75rem;
}

.private-specs li::before {
    content: "•";
    color: var(--color-accent);
    font-size: 1.5rem;
}

/* Reviews */
.reviews {
    padding: 6rem 0;
    background: var(--bg-main);
    border-bottom: 1px solid var(--border-color);
}

.reviews-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 2rem;
}

.review-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 2rem;
    display: flex;
    flex-direction: column;
}

.review-stars {
    color: var(--color-accent);
    font-size: 1.2rem;
    margin-bottom: 1rem;
}

.review-text {
    color: var(--text-secondary);
    font-size: 1rem;
    line-height: 1.6;
    margin-bottom: 1.5rem;
    flex-grow: 1;
    font-style: italic;
}

.reviewer-meta {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.reviewer-avatar {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    object-fit: cover;
    border: 1px solid var(--border-color);
}

.reviewer-info h4 {
    color: var(--text-primary);
    font-size: 1rem;
}

.reviewer-info span {
    color: var(--text-muted);
    font-size: 0.85rem;
}

/* FAQ Accordion */
.faq {
    padding: 6rem 0;
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border-color);
}

.faq-list {
    max-width: 800px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 1rem;
}

.faq-item {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    overflow: hidden;
    transition: var(--transition);
}

.faq-question {
    width: 100%;
    text-align: left;
    padding: 1.25rem 1.5rem;
    font-family: var(--font-heading);
    font-size: 1.15rem;
    color: var(--text-primary);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.faq-icon {
    font-size: 1.2rem;
    color: var(--color-accent);
    transition: transform 0.25s ease;
}

.faq-item.active .faq-icon {
    transform: rotate(45deg);
}

.faq-answer {
    max-height: 0;
    overflow: hidden;
    transition: max-height 0.3s ease;
    padding: 0 1.5rem;
    color: var(--text-secondary);
    font-size: 0.95rem;
    line-height: 1.6;
}

.faq-item.active .faq-answer {
    padding-bottom: 1.25rem;
    max-height: 200px;
}

/* Modals */
.modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.75);
    backdrop-filter: blur(8px);
    display: none;
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
    z-index: 1000;
    box-sizing: border-box;
    overflow-y: auto;
}

.modal-overlay.open {
    display: flex;
}

.modal-card {
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    max-width: 560px;
    width: 100%;
    box-sizing: border-box;
    position: relative;
    max-height: 90vh;
    overflow-y: auto;
    box-shadow: var(--shadow-lg);
    padding: 2.5rem;
}

.modal-close-btn {
    position: absolute;
    top: 1.25rem;
    right: 1.25rem;
    font-size: 1.5rem;
    color: var(--text-secondary);
    cursor: pointer;
    line-height: 1;
    transition: var(--transition);
}

.modal-close-btn:hover {
    color: var(--color-accent);
}

/* Reservation Form */
.reservation-form {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    margin-top: 1.5rem;
}

.form-group {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
}

.form-group label {
    font-size: 0.9rem;
    color: var(--text-secondary);
    font-weight: 500;
}

.form-group input,
.form-group select,
.form-group textarea {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    padding: 0.75rem 1rem;
    color: var(--text-primary);
    font-size: 0.95rem;
    outline: none;
    transition: var(--transition);
}

.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus {
    border-color: var(--color-accent);
}

.form-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
}

/* Toast */
.toast {
    position: fixed;
    bottom: 2rem;
    right: 2rem;
    background: var(--color-accent);
    color: #141110;
    padding: 1rem 1.75rem;
    border-radius: var(--radius-sm);
    font-weight: 600;
    box-shadow: var(--shadow-lg);
    z-index: 2000;
    transform: translateY(100px);
    opacity: 0;
    transition: all 0.3s ease;
}

.toast.show {
    transform: translateY(0);
    opacity: 1;
}

/* Footer */
.footer {
    background: var(--bg-main);
    border-top: 1px solid var(--border-color);
    padding: 5rem 0 2rem 0;
}

.footer-grid {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr 1.5fr;
    gap: 3rem;
    margin-bottom: 3rem;
}

.footer-col h3,
.footer-col h4 {
    font-family: var(--font-heading);
    margin-bottom: 1.25rem;
    color: var(--text-primary);
}

.footer-col p {
    color: var(--text-secondary);
    font-size: 0.95rem;
    line-height: 1.6;
}

.footer-links {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
}

.footer-links a {
    color: var(--text-secondary);
    transition: var(--transition);
}

.footer-links a:hover {
    color: var(--color-accent);
}

.footer-bottom {
    border-top: 1px solid var(--border-color);
    padding-top: 2rem;
    text-align: center;
    color: var(--text-muted);
    font-size: 0.85rem;
}

/* Responsive Media Queries (Including 1024px Tablet Navigation Refinement) */
@media (max-width: 1024px) {
    .nav-container {
        gap: 1rem;
    }
    .brand-logo {
        font-size: 1.25rem;
        gap: 0.5rem;
    }
    .brand-mark {
        width: 32px;
        height: 32px;
        font-size: 0.95rem;
    }
    .nav-links {
        gap: 1.1rem;
    }
    .nav-links a {
        font-size: 0.9rem;
    }
    .nav-actions .btn-primary {
        padding: 0.6rem 1.15rem;
        font-size: 0.88rem;
        white-space: nowrap;
    }
    .story-grid,
    .chef-grid,
    .private-grid {
        grid-template-columns: 1fr;
        gap: 2.5rem;
    }
    .footer-grid {
        grid-template-columns: 1fr 1fr;
    }
}

@media (max-width: 768px) {
    .container {
        padding: 0 1rem;
    }
    .nav-actions .btn-primary {
        display: none;
    }
    .modal-overlay {
        padding: 0.75rem;
    }
    .modal-card {
        padding: 1.5rem 1rem;
    }
    .nav-links {
        display: none;
    }
    .hamburger-btn {
        display: flex;
    }
    .form-row {
        grid-template-columns: 1fr;
    }
    .footer-grid {
        grid-template-columns: 1fr;
    }
}
"""
        css_path.write_text(css_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(css_path, ws, generator="foundation_scaffolder")
        logger.info(f"FoundationScaffolder: created {css_path.name}")

    # 3. index.html (Semantic HTML5 with correct cuisine content & zero fabricated credentials)
    html_path = ws / "index.html"
    if not html_path.exists() or html_path.stat().st_size < 50:
        if is_indian:
            hero_tag = "Artisanal Wood-Fired & Tandoor Kitchen"
            hero_h1 = "Contemporary Indian Gastronomy by the Clay Oven"
            hero_sub = "Where hand-pounded Kashmiri saffron, slow-cooked Awadhi dum biryanis, and live tandoor embers converge in culinary harmony."
            story_title = "Fire, Stone, and the Golden Spice"
            story_p1 = "At Saffron & Stone, every plate honors the profound heritage of Indian regional culinary traditions. From single-origin Kashmiri saffron to slow-braised Awadhi dum cooking, our kitchen pairs live charcoal embers with delicate aromatics."
            story_p2 = "We work intimately with heirloom spice cooperatives, organic dairy farms, and artisanal flour millers to ensure uncompromising integrity in every tandoor roast and handi stew."
            p1_title, p1_desc = "Clay Oven Tandoor", "Live charcoal embers imparting authentic smoke and blistering heat to marinades and breads."
            p2_title, p2_desc = "Single-Origin Saffron", "Hand-harvested Kashmiri saffron infused into delicate broths, biryanis, and slow-churned kulfi."
            menu_title = "The Seasonal Indian Menu"
            menu_sub = "Handcrafted chaat, clay oven tandoor specialties, and slow-simmered handi delicacies."
            filter_buttons = """<button class="filter-pill active" data-category="all">All Selections</button>
                        <button class="filter-pill" data-category="starters">Starters & Chaat</button>
                        <button class="filter-pill" data-category="tandoor">Tandoor Specialties</button>
                        <button class="filter-pill" data-category="mains">Mains & Biryani</button>
                        <button class="filter-pill" data-category="breads">Indian Breads</button>
                        <button class="filter-pill" data-category="desserts">Traditional Desserts</button>"""
            chef_name = "Chef Sanjay Kapoor"
            chef_title = "Executive Chef & Co-Founder"
            chef_desc = "Trained across Old Delhi, Lucknow, and Mumbai, Chef Sanjay brings over two decades of culinary artistry to Saffron & Stone. His philosophy pairs primal clay oven cooking with hyper-delicate hand-pounded spices."
            chef_quote = '"Indian cooking is not just heat and spice; it is the discipline of slow extraction, charcoal embers, and deep respect for centuries-old recipes."'
            amb_cap1, amb_cap2, amb_cap3 = "The Dining Vault", "The Maharajah Reserve", "The Clay Oven Counter"
            priv_title = "The Maharajah Dining Chamber"
            priv_desc = "Accommodating up to 24 guests, our private dining chamber offers bespoke royal Indian feasts paired with fine vintage wines and handcrafted spice infusions."
            priv_l1, priv_l2, priv_l3 = "Dedicated master sommelier and culinary service team", "Bespoke 7-course royal Indian tasting menu", "Private acoustic sound system and discrete entrance"
            rev1_text = '"The Awadhi Lamb Dum Biryani sealed in the clay handi released an aroma that transported us immediately. The layers of saffron and spices are world-class."'
            rev1_author = "Priya Sharma"
            rev1_role = "Food & Hospitality Columnist"
            rev2_text = '"The charred paneer tikka and the 24-hour dal makhani with fresh truffle kulcha are genuinely exceptional."'
            rev2_author = "Vikram & Sunita Malhotra"
            rev2_role = "Verified Dining Guests"
            footer_desc = "Artisanal Contemporary Indian kitchen rooted in live tandoor embers, wild hand-pounded spices, and regional heritage recipes."
            footer_copy = "&copy; 2026 Saffron & Stone Contemporary Indian Kitchen. All rights reserved."
        else:
            hero_tag = "Artisanal Wood-Fired Hearth Dining"
            hero_h1 = "Artisanal Mediterranean Dining by the Hearth"
            hero_sub = "Where ancient stone-milled spices, wood-fired heritage embers, and coastal bounty unite in culinary harmony."
            story_title = "Stone, Fire, and the Golden Spice"
            story_p1 = "At Saffron & Stone, every plate honors centuries of Mediterranean culinary traditions. From hand-foraged wild thyme to authentic Persian saffron threads, our hearth infuses warmth into every grain and cut."
            story_p2 = "We work intimately with family-owned fisheries, organic groves, and biodynamic vineyards to ensure uncompromising integrity from harvest to table."
            p1_title, p1_desc = "Wood-Fired Hearth", "Ancient olive wood ember cooking imparting distinct caramelization."
            p2_title, p2_desc = "Pure Saffron", "Single-origin saffron hand-picked from heirloom mountain cooperatives."
            menu_title = "The Seasonal Menu"
            menu_sub = "Hand-crafted tasting selections, sharing mezze, and wood-fired delicacies."
            filter_buttons = """<button class="filter-pill active" data-category="all">All Selections</button>
                        <button class="filter-pill" data-category="starters">Starters & Mezze</button>
                        <button class="filter-pill" data-category="mains">Mains & Hearth</button>
                        <button class="filter-pill" data-category="seafood">Wood-Fired Seafood</button>
                        <button class="filter-pill" data-category="desserts">Desserts & Infusions</button>
                        <button class="filter-pill" data-category="beverages">Signature Cellar</button>"""
            chef_name = "Chef Marco Rossi"
            chef_title = "Executive Chef & Co-Founder"
            chef_desc = "Trained across coastal Liguria and Andalusia, Chef Marco brings over two decades of culinary artistry to Saffron & Stone. His philosophy pairs primal flame cooking with hyper-delicate aromatics."
            chef_quote = '"The fire does not rush. Good food is patience, wild herbs, and reverence for the sea."'
            amb_cap1, amb_cap2, amb_cap3 = "Main Dining Vault", "The Sommelier's Reserve", "The Hearth Counter"
            priv_title = "The Wine Cellar Vault"
            priv_desc = "Accommodating up to 24 guests, our subterranean brick wine cellar offers tailored multi-course tasting menus paired with rare Mediterranean vintages."
            priv_l1, priv_l2, priv_l3 = "Dedicated master sommelier and culinary service team", "Bespoke 7-course hearth tasting menu", "Private acoustic sound system and discrete entrance"
            rev1_text = '"The Saffron Lamb Tagine melted at the touch of a fork. The depth of flavor from the wood fire is unlike anything in the city."'
            rev1_author = "Elena Vance"
            rev1_role = "Gastronomy Writer, Table & Travel"
            rev2_text = '"An unforgettable anniversary dinner in the wine cellar. Impeccable pairings and genuine hospitality."'
            rev2_author = "Julian & Clara Davies"
            rev2_role = "Verified Dining Guests"
            footer_desc = "Artisanal Mediterranean hearth cooking rooted in fire, wild spices, and coastal tradition."
            footer_copy = "&copy; 2026 Saffron & Stone Restaurant. All rights reserved."

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🍽️</text></svg>">
    <meta name="description" content="{desc_text}">
    <link rel="stylesheet" href="style.css">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Playfair+Display:ital,wght@0,600;0,700;1,400&display=swap" rel="stylesheet">
</head>
<body>
    <!-- 1. Header / Navigation -->
    <header class="navbar" id="nav">
        <div class="container nav-container">
            <a href="#hero" class="brand-logo">
                <span class="brand-mark">S&S</span>
                <span>{app_name}</span>
            </a>
            <ul class="nav-links" id="nav-links">
                <li><a href="#story">Story</a></li>
                <li><a href="#menu">Menu</a></li>
                <li><a href="#chef">Chef</a></li>
                <li><a href="#ambience">Ambience</a></li>
                <li><a href="#private-dining">Private Dining</a></li>
                <li><a href="#reviews">Reviews</a></li>
                <li><a href="#faq">FAQ</a></li>
            </ul>
            <div class="nav-actions">
                <button class="btn-primary" id="nav-reserve-btn">Reserve a Table</button>
                <div class="hamburger-btn" id="hamburger-btn" aria-label="Toggle navigation">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
            </div>
        </div>
    </header>

    <main>
        <!-- 2. Hero Section -->
        <section class="hero" id="hero">
            <div class="container">
                <div class="hero-content">
                    <span class="hero-badge">{hero_tag}</span>
                    <h1>{hero_h1}</h1>
                    <p>{hero_sub}</p>
                    <div class="hero-actions">
                        <button class="btn-primary" id="hero-reserve-btn">Reserve a Table</button>
                        <a href="#menu" class="btn-outline">Explore Menu</a>
                    </div>
                </div>
            </div>
        </section>

        <!-- 3. Story & Philosophy -->
        <section class="story" id="story">
            <div class="container">
                <div class="story-grid">
                    <div class="story-image">
                        <img src="assets/images/hero/hero-restaurant.jpg" alt="Saffron & Stone dining room and kitchen" width="600" height="400">
                    </div>
                    <div class="story-text">
                        <span class="tagline">Our Heritage</span>
                        <h2>{story_title}</h2>
                        <p>{story_p1}</p>
                        <p>{story_p2}</p>
                        <div class="pillars-grid">
                            <div class="pillar-card">
                                <h3>{p1_title}</h3>
                                <p>{p1_desc}</p>
                            </div>
                            <div class="pillar-card">
                                <h3>{p2_title}</h3>
                                <p>{p2_desc}</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <!-- 4. Interactive Menu Section -->
        <section class="menu" id="menu">
            <div class="container">
                <div class="section-header">
                    <span class="tagline">Culinary Offerings</span>
                    <h2>{menu_title}</h2>
                    <p>{menu_sub}</p>
                </div>

                <div class="menu-controls">
                    <div class="menu-search-box">
                        <input type="text" id="menu-search" placeholder="Search dishes, ingredients, or pairings...">
                    </div>
                    <div class="filter-pills" id="menu-filter">
                        {filter_buttons}
                    </div>
                </div>

                <div class="menu-grid" id="menu-grid">
                    <!-- Populated dynamically by app.js -->
                </div>
            </div>
        </section>

        <!-- 5. Executive Chef Section -->
        <section class="chef" id="chef">
            <div class="container">
                <div class="chef-grid">
                    <div class="chef-image">
                        <img src="assets/images/chef/executive-chef.jpg" alt="{chef_name}" width="600" height="400">
                    </div>
                    <div class="chef-text">
                        <span class="tagline">Culinary Leadership</span>
                        <h2>{chef_name}</h2>
                        <span class="chef-title">{chef_title}</span>
                        <p>{chef_desc}</p>
                        <div class="chef-quote">
                            {chef_quote}
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <!-- 6. Ambience & Spaces Gallery -->
        <section class="ambience" id="ambience">
            <div class="container">
                <div class="section-header">
                    <span class="tagline">Atmosphere</span>
                    <h2>Spaces & Architecture</h2>
                    <p>Candlelit shadows, authentic textured earthenware, and acoustic warmth.</p>
                </div>
                <div class="gallery-grid" id="gallery-grid">
                    <div class="gallery-item">
                        <img src="assets/images/ambience/dining-room.jpg" alt="Main Dining Room" width="400" height="280">
                        <div class="gallery-caption">{amb_cap1}</div>
                    </div>
                    <div class="gallery-item">
                        <img src="assets/images/ambience/private-dining.jpg" alt="Private Chamber" width="400" height="280">
                        <div class="gallery-caption">{amb_cap2}</div>
                    </div>
                    <div class="gallery-item">
                        <img src="assets/images/hero/hero-restaurant.jpg" alt="The Counter" width="400" height="280">
                        <div class="gallery-caption">{amb_cap3}</div>
                    </div>
                </div>
            </div>
        </section>

        <!-- 7. Private Dining & Celebrations -->
        <section class="private-dining" id="private-dining">
            <div class="container">
                <div class="private-grid">
                    <div class="private-text">
                        <span class="tagline">Exclusive Gatherings</span>
                        <h2>{priv_title}</h2>
                        <p>{priv_desc}</p>
                        <ul class="private-specs">
                            <li>{priv_l1}</li>
                            <li>{priv_l2}</li>
                            <li>{priv_l3}</li>
                        </ul>
                        <button class="btn-primary" id="private-inquire-btn">Inquire for Private Events</button>
                    </div>
                    <div class="private-image">
                        <img src="assets/images/ambience/private-dining.jpg" alt="Private dining room table" width="600" height="400">
                    </div>
                </div>
            </div>
        </section>

        <!-- 8. Guest Reviews -->
        <section class="reviews" id="reviews">
            <div class="container">
                <div class="section-header">
                    <span class="tagline">Guest Impressions</span>
                    <h2>Critical Acclaim</h2>
                    <p>Recognized by patrons and culinary writers.</p>
                </div>
                <div class="reviews-grid" id="reviews-grid">
                    <div class="review-card">
                        <div class="review-stars">★★★★★</div>
                        <p class="review-text">{rev1_text}</p>
                        <div class="reviewer-meta">
                            <img src="assets/images/testimonials/guest-review.jpg" alt="{rev1_author}" class="reviewer-avatar">
                            <div class="reviewer-info">
                                <h4>{rev1_author}</h4>
                                <span>{rev1_role}</span>
                            </div>
                        </div>
                    </div>
                    <div class="review-card">
                        <div class="review-stars">★★★★★</div>
                        <p class="review-text">{rev2_text}</p>
                        <div class="reviewer-meta">
                            <div class="reviewer-avatar" style="background:#8b3a1a; display:flex; align-items:center; justify-content:center; color:#fff; font-weight:700;">VM</div>
                            <div class="reviewer-info">
                                <h4>{rev2_author}</h4>
                                <span>{rev2_role}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <!-- 9. FAQ Accordion -->
        <section class="faq" id="faq">
            <div class="container">
                <div class="section-header">
                    <span class="tagline">Information</span>
                    <h2>Frequently Asked Questions</h2>
                    <p>Details regarding dress code, dietary accommodations, and reservations.</p>
                </div>
                <div class="faq-list">
                    <div class="faq-item">
                        <button class="faq-question">
                            <span>What is the restaurant dress code?</span>
                            <span class="faq-icon">+</span>
                        </button>
                        <div class="faq-answer">
                            <p>We request smart casual attire. Athletic wear and beachwear are not permitted in the main dining room or private chamber.</p>
                        </div>
                    </div>
                    <div class="faq-item">
                        <button class="faq-question">
                            <span>Can dietary restrictions and allergies be accommodated?</span>
                            <span class="faq-icon">+</span>
                        </button>
                        <div class="faq-answer">
                            <p>Yes. Our kitchen happily accommodates vegetarian, vegan, gluten-free, halal, and nut allergies. Please inform us when reserving.</p>
                        </div>
                    </div>
                    <div class="faq-item">
                        <button class="faq-question">
                            <span>What is your corkage and private dining policy?</span>
                            <span class="faq-icon">+</span>
                        </button>
                        <div class="faq-answer">
                            <p>Corkage is $45 per 750ml bottle for up to two bottles. Private dining chamber inquiries can be submitted directly through our booking form.</p>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    </main>

    <!-- 10. Dish Detail Modal -->
    <div class="modal-overlay" id="dish-modal">
        <div class="modal-card">
            <span class="modal-close-btn" id="dish-modal-close">&times;</span>
            <div id="dish-modal-body">
                <!-- Injected dynamically -->
            </div>
        </div>
    </div>

    <!-- 11. Reservation Modal & Form -->
    <div class="modal-overlay" id="reservation-modal">
        <div class="modal-card">
            <span class="modal-close-btn" id="reservation-modal-close">&times;</span>
            <h2 style="font-family: var(--font-heading); margin-bottom: 0.5rem; color: var(--text-primary);">Table Reservation</h2>
            <p style="color: var(--text-secondary); font-size: 0.95rem;">Join us for an unforgettable dining experience.</p>
            <form class="reservation-form" id="reservation-form">
                <div class="form-row">
                    <div class="form-group">
                        <label for="res-name">Full Name *</label>
                        <input type="text" id="res-name" required placeholder="Alex Mercer">
                    </div>
                    <div class="form-group">
                        <label for="res-email">Email Address *</label>
                        <input type="email" id="res-email" required placeholder="alex@example.com">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label for="res-date">Date *</label>
                        <input type="date" id="res-date" required>
                    </div>
                    <div class="form-group">
                        <label for="res-time">Seating Time *</label>
                        <select id="res-time" required>
                            <option value="">Select Time</option>
                            <option value="17:30">5:30 PM (Early Dinner)</option>
                            <option value="18:30">6:30 PM</option>
                            <option value="19:30">7:30 PM (Prime Dinner)</option>
                            <option value="20:30">8:30 PM</option>
                            <option value="21:30">9:30 PM (Late Seating)</option>
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label for="res-guests">Number of Guests *</label>
                        <select id="res-guests" required>
                            <option value="2">2 Guests</option>
                            <option value="3">3 Guests</option>
                            <option value="4">4 Guests</option>
                            <option value="6">6 Guests</option>
                            <option value="8+">8+ Guests (Large Party)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="res-area">Preferred Seating Area</label>
                        <select id="res-area">
                            <option value="main">Main Dining Vault</option>
                            <option value="counter">The Hearth Counter</option>
                            <option value="chamber">The Private Chamber</option>
                        </select>
                    </div>
                </div>
                <div class="form-group">
                    <label for="res-notes">Dietary Notes / Special Requests</label>
                    <textarea id="res-notes" rows="2" placeholder="Anniversary celebration, vegetarian, nut allergy, etc."></textarea>
                </div>
                <button type="submit" class="btn-primary" style="width: 100%; justify-content: center; margin-top: 0.5rem;">Confirm Reservation</button>
            </form>
        </div>
    </div>

    <!-- 12. Toast Feedback Notification -->
    <div class="toast" id="toast">Reservation confirmed! We look forward to welcoming you.</div>

    <!-- 13. Footer -->
    <footer class="footer" id="footer">
        <div class="container">
            <div class="footer-grid">
                <div class="footer-col">
                    <div class="brand-logo" style="margin-bottom: 1rem;">
                        <span class="brand-mark">S&S</span>
                        <span>{app_name}</span>
                    </div>
                    <p>{footer_desc}</p>
                </div>
                <div class="footer-col">
                    <h4>Navigation</h4>
                    <ul class="footer-links">
                        <li><a href="#story">Story</a></li>
                        <li><a href="#menu">Seasonal Menu</a></li>
                        <li><a href="#chef">Executive Chef</a></li>
                        <li><a href="#private-dining">Private Dining</a></li>
                    </ul>
                </div>
                <div class="footer-col">
                    <h4>Hours</h4>
                    <p>Tuesday – Sunday<br>Dinner: 5:00 PM – 11:00 PM<br>Lounge & Bar: until 12:30 AM<br>Closed Mondays</p>
                </div>
                <div class="footer-col">
                    <h4>Location</h4>
                    <p>412 Heritage Hearth Way<br>Culinary Quarter<br>Phone: (555) 382-7194<br>Email: concierge@saffronandstone.com</p>
                </div>
            </div>
            <div class="footer-bottom">
                {footer_copy}
            </div>
        </div>
    </footer>

    <script src="app.js"></script>
</body>
</html>
"""
        html_path.write_text(html_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(html_path, ws, generator="foundation_scaffolder")
        logger.info(f"FoundationScaffolder: created {html_path.name}")

    # 4. app.js (12 authentic dishes matching cuisine subtype)
    js_path = ws / "app.js"
    if not js_path.exists() or js_path.stat().st_size < 50:
        if is_indian:
            dishes_json = """const DISHES = [
    {
        id: "paneer-tikka",
        name: "Charred Saffron Paneer Tikka",
        category: "starters",
        price: "$22",
        tag: "Signature Starter",
        image: "assets/images/menu/saffron-lamb-tagine.jpg",
        description: "Slow-marinated artisan cottage cheese steeped in hand-pounded Kashmiri saffron, hung curd, and charred bell peppers.",
        dietary: ["Vegetarian", "GF"],
        pairing: "2021 Alsace Gewürztraminer Trimbach",
        ingredients: "Artisanal paneer, Kashmiri saffron, Greek hung curd, carom seeds, ginger paste, fresh mint"
    },
    {
        id: "dahi-puri",
        name: "Avocado & Pomegranate Dahi Puri",
        category: "starters",
        price: "$18",
        tag: "Street Food Craft",
        image: "assets/images/menu/mezze-platter.jpg",
        description: "Crisp semolina spheres filled with spiced potatoes, tempered sweet yogurt, tamarind date reduction, and pomegranate seeds.",
        dietary: ["Vegetarian"],
        pairing: "Signature Cardamom Mint Cooler",
        ingredients: "Semolina puris, Hass avocado, tempered sweet curd, tamarind chutney, roasted cumin"
    },
    {
        id: "tandoori-salmon",
        name: "Tandoori Spiced Wild Salmon",
        category: "tandoor",
        price: "$38",
        tag: "Clay Oven Roast",
        image: "assets/images/menu/wild-sea-bass.jpg",
        description: "Wild Atlantic salmon roasted in high-heat clay tandoor with toasted ajwain carom seeds, cold-pressed mustard oil, and citrus herbs.",
        dietary: ["GF"],
        pairing: "2022 Provençal Rosé Whispering Angel",
        ingredients: "Wild Atlantic salmon, ajwain carom, organic mustard oil, Kashmiri chili, dried kasoori methi"
    },
    {
        id: "tandoori-chops",
        name: "Smoked Cardamom Lamb Chops",
        category: "tandoor",
        price: "$44",
        tag: "Chef Specialty",
        image: "assets/images/menu/prime-ribeye.jpg",
        description: "Prime rib chops marinated in caramelized onion paste, smoked green cardamom, and roasted over live charcoal coals.",
        dietary: ["GF"],
        pairing: "2019 Barolo Pio Cesare",
        ingredients: "Prime pasture-raised lamb chops, smoked green cardamom, brown shallot paste, raw papaya tenderizer, aged ghee"
    },
    {
        id: "lamb-dum-biryani",
        name: "Awadhi Lamb Dum Biryani",
        category: "mains",
        price: "$36",
        tag: "Heritage Recipe",
        image: "assets/images/menu/saffron-lamb-tagine.jpg",
        description: "Slow-braised tender lamb shank layered with aged basmati rice, saffron-infused milk, and fried shallots sealed in traditional clay handi.",
        dietary: ["GF"],
        pairing: "2018 Rioja Reserva Marqués de Riscal",
        ingredients: "Pasture lamb, aged Dehradun basmati rice, pure Kashmiri saffron, kewra blossom water, green cardamom, fried shallots"
    },
    {
        id: "butter-chicken",
        name: "Old Delhi Murgh Makhani",
        category: "mains",
        price: "$32",
        tag: "Clay Oven Curry",
        image: "assets/images/menu/saffron-lamb-tagine.jpg",
        description: "Charcoal-smoked tandoori chicken simmered in a velvety reduction of vine-ripened San Marzano tomatoes, cultured butter, and wild kasoori methi.",
        dietary: ["GF"],
        pairing: "2020 Pinot Noir Domaine Drouhin",
        ingredients: "Free-range chicken thigh, vine tomatoes, cultured white butter, cashew cream, organic fenugreek leaves"
    },
    {
        id: "dal-makhani",
        name: "24-Hour Slow-Simmered Dal Makhani",
        category: "mains",
        price: "$26",
        tag: "Heritage Comfort",
        image: "assets/images/menu/mezze-platter.jpg",
        description: "Black urad lentils and red kidney beans simmered overnight on dying charcoal embers with churned butter and julienned ginger.",
        dietary: ["Vegetarian", "GF"],
        pairing: "2021 Syrah Northern Rhône",
        ingredients: "Whole black urad lentils, Kashmiri chili, ginger juliennes, churned cream, artisan churned butter"
    },
    {
        id: "morel-pulao",
        name: "Saffron Wild Morel Mushroom Pulao",
        category: "mains",
        price: "$28",
        tag: "Himalayan Forage",
        image: "assets/images/menu/saffron-lamb-tagine.jpg",
        description: "Aged long-grain basmati rice gently cooked with wild foraged Kashmiri morels, pure saffron broth, and whole cloves.",
        dietary: ["Vegetarian", "GF"],
        pairing: "2020 Meursault Louis Jadot",
        ingredients: "Wild Kashmiri gucchi morels, aged basmati rice, saffron broth, green cardamom, desi ghee"
    },
    {
        id: "truffle-kulcha",
        name: "Wood-Fired Truffle Kulcha",
        category: "breads",
        price: "$14",
        tag: "Hearth Baked",
        image: "assets/images/menu/mezze-platter.jpg",
        description: "Blistered leavened tandoor bread stuffed with seasoned wild mushrooms, white truffle oil, and kalonji nigella seeds.",
        dietary: ["Vegetarian"],
        pairing: "Complements rich gravies and biryani",
        ingredients: "Naturally leavened dough, foraged wild mushrooms, white truffle oil, nigella seeds, sea salt"
    },
    {
        id: "garlic-naan",
        name: "Clay Oven Garlic & Coriander Naan",
        category: "breads",
        price: "$9",
        tag: "Tandoori Classic",
        image: "assets/images/menu/mezze-platter.jpg",
        description: "Hand-stretched leavened dough slapped against high-heat clay oven walls, brushed with clarified garlic butter and fresh coriander.",
        dietary: ["Vegetarian"],
        pairing: "Essential companion to Dal Makhani and Murgh Makhani",
        ingredients: "Organic heritage flour, sweet garlic cloves, fresh garden coriander, clarified butter"
    },
    {
        id: "saffron-kulfi",
        name: "Kashmiri Saffron & Pistachio Kulfi",
        category: "desserts",
        price: "$16",
        tag: "Traditional Ice",
        image: "assets/images/menu/pistachio-baklava.jpg",
        description: "Dense, slow-reduced caramelized milk kulfi steeped in golden Kashmiri saffron and studded with slivered green pistachios.",
        dietary: ["Vegetarian", "GF"],
        pairing: "2017 Sauternes Château Guiraud",
        ingredients: "Whole buffalo milk, Kashmiri saffron threads, Iranian pistachios, green cardamom pods"
    },
    {
        id: "gulab-jamun",
        name: "Warm Saffron & Rose Gulab Jamun",
        category: "desserts",
        price: "$15",
        tag: "Heritage Confection",
        image: "assets/images/menu/pistachio-baklava.jpg",
        description: "Golden reduced-milk dumplings steeped in warm cardamom and rosewater syrup with crushed Iranian pistachios and edible gold leaf.",
        dietary: ["Vegetarian"],
        pairing: "2016 Royal Tokaji 5 Puttonyos",
        ingredients: "Artisan khoya, golden saffron syrup, organic rosewater, green cardamom, pistachio dust"
    }
];"""
        else:
            dishes_json = """const DISHES = [
    {
        id: "lamb-tagine",
        name: "Saffron Lamb Tagine",
        category: "mains",
        price: "$38",
        tag: "Signature Dish",
        image: "assets/images/menu/saffron-lamb-tagine.jpg",
        description: "Slow-braised pasture-raised lamb shank simmered in golden saffron broth with Smyrna apricots and toasted almonds.",
        dietary: ["GF", "Organic"],
        pairing: "2019 Domaine de Beaurenard Châteauneuf-du-Pape",
        ingredients: "Pasture-raised lamb, pure Persian saffron, organic apricots, heirloom almonds, cinnamon bark, Moroccan honey"
    },
    {
        id: "wild-sea-bass",
        name: "Wild Mediterranean Sea Bass",
        category: "seafood",
        price: "$42",
        tag: "Wild Caught",
        image: "assets/images/menu/wild-sea-bass.jpg",
        description: "Pan-roasted crisp skin sea bass with emulsified lemon verbena oil, charred artichoke hearts, and caperberries.",
        dietary: ["GF"],
        pairing: "2021 Santorini Assyrtiko Sigalas",
        ingredients: "Line-caught Mediterranean sea bass, wild oregano, Meyer lemon, braised baby artichokes, cold-pressed olive oil"
    },
    {
        id: "prime-ribeye",
        name: "Dry-Aged Prime Ribeye",
        category: "mains",
        price: "$54",
        tag: "Hearth Grilled",
        image: "assets/images/menu/prime-ribeye.jpg",
        description: "45-day dry-aged prime beef seared over olive wood coals, finished with smoked bone marrow butter and sea salt crystals.",
        dietary: ["GF"],
        pairing: "2018 Rioja Gran Reserva Viña Tondonia",
        ingredients: "Dry-aged prime beef, charred rosemary, smoked sea salt, roasted garlic, black peppercorn crust"
    },
    {
        id: "truffle-carpaccio",
        name: "Truffle Beef Carpaccio",
        category: "starters",
        price: "$24",
        tag: "Raw Bar",
        image: "assets/images/menu/truffle-carpaccio.jpg",
        description: "Thinly sliced tenderloin adorned with shaved black winter truffles, 36-month parmigiano-reggiano, and peppery arugula.",
        dietary: ["GF"],
        pairing: "NV Franciacorta Brut Bellavista",
        ingredients: "Prime tenderloin, Umbrian black truffle, Parmigiano-Reggiano, wild baby arugula, cold-pressed olive oil"
    },
    {
        id: "mezze-platter",
        name: "Grand Artisanal Mezze Board",
        category: "starters",
        price: "$22",
        tag: "Sharing",
        image: "assets/images/menu/mezze-platter.jpg",
        description: "Smoked eggplant babaganoush, whipped saffron hummus, muhammara, Kalamata olives, and fresh wood-fired flatbread.",
        dietary: ["Vegetarian", "Vegan Option"],
        pairing: "2022 Provençal Rosé Château Miraval",
        ingredients: "Smoked Japanese eggplant, organic chickpeas, pomegranate molasses, roasted walnuts, heirloom sesame tahini"
    },
    {
        id: "pistachio-baklava",
        name: "Deconstructed Pistachio Baklava",
        category: "desserts",
        price: "$16",
        tag: "Signature Dessert",
        image: "assets/images/menu/pistachio-baklava.jpg",
        description: "Crisp caramelized phyllo wafers layered with Bronte pistachio cream, cardamom syrup, and saffron blossom gelato.",
        dietary: ["Vegetarian"],
        pairing: "2017 Vin Santo di Montepulciano",
        ingredients: "Hand-rolled phyllo, Sicilian Bronte pistachios, orange blossom honey, green cardamom, churned sweet cream"
    },
    {
        id: "charred-octopus",
        name: "Charred Spanish Octopus",
        category: "seafood",
        price: "$34",
        tag: "Wood-Fired",
        image: "assets/images/menu/wild-sea-bass.jpg",
        description: "Tender Galician octopus seared with smoked pimentón de la Vera, saffron potato cream, and pickled shallots.",
        dietary: ["GF"],
        pairing: "2021 Godello Rafael Palacios",
        ingredients: "Galician octopus, smoked pimentón, Yukon gold saffron purée, micro celery, sherry vinegar reduction"
    },
    {
        id: "zaatar-flatbread",
        name: "Wood-Fired Za'atar Bread",
        category: "starters",
        price: "$14",
        tag: "Bakery",
        image: "assets/images/menu/mezze-platter.jpg",
        description: "Blistered sourdough flatbread brushed with wild Lebanese za'atar herbs, crushed sumac, and extra virgin olive oil.",
        dietary: ["Vegan"],
        pairing: "Refreshing Mint Infused Soda",
        ingredients: "Naturally leavened flour, wild thyme, sumac berries, roasted sesame, unfiltered Cretan olive oil"
    },
    {
        id: "mushroom-risotto",
        name: "Saffron Wild Chanterelle Risotto",
        category: "mains",
        price: "$32",
        tag: "Vegetarian",
        image: "assets/images/menu/saffron-lamb-tagine.jpg",
        description: "Carnaroli rice slow-cooked with saffron threads, foraged chanterelles, white wine, and aged pecorino sardo.",
        dietary: ["Vegetarian", "GF"],
        pairing: "2020 Etna Bianco Benanti",
        ingredients: "Acquerello carnaroli rice, wild chanterelles, saffron broth, Pecorino Sardo, French butter"
    },
    {
        id: "garlic-prawns",
        name: "Garlic Wood-Fired King Prawns",
        category: "seafood",
        price: "$36",
        tag: "Hearth Grilled",
        image: "assets/images/menu/wild-sea-bass.jpg",
        description: "Jumbo wild prawns roasted in sizzling terracotta with sweet garlic cloves, chili peppers, and crusty bread.",
        dietary: ["GF"],
        pairing: "2021 Albariño de Fefiñanes",
        ingredients: "Wild king prawns, fermented garlic oil, bird's eye chili, Italian flat parsley, lemon zest"
    },
    {
        id: "cardamom-ganache",
        name: "Smoked Cardamom Dark Chocolate",
        category: "desserts",
        price: "$15",
        tag: "Decadent",
        image: "assets/images/menu/pistachio-baklava.jpg",
        description: "70% Valrhona dark chocolate torte infused with wood-smoked cardamom, served with olive oil fleur de sel gelato.",
        dietary: ["Vegetarian", "GF"],
        pairing: "10-Year Tawny Port",
        ingredients: "Valrhona Guanaja chocolate, cardamom smoke, Maldon sea salt, Arbequina olive oil gelato"
    },
    {
        id: "saffron-negroni",
        name: "Saffron & Blood Orange Negroni",
        category: "beverages",
        price: "$18",
        tag: "Signature Cocktail",
        image: "assets/images/ambience/dining-room.jpg",
        description: "Botanical gin infused with saffron threads, bitter Campari, sweet vermouth, smoked rosemary, and flamed orange peel.",
        dietary: ["Handcrafted"],
        pairing: "Excellent aperitif before starters",
        ingredients: "Saffron-steeped dry gin, red vermouth, bitter gentian, charred rosemary sprig, citrus oils"
    }
];"""

        js_content = f"""/* ==========================================================================
   Saffron & Stone — Interactive Application Logic
   ========================================================================== */

{dishes_json}

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => {{
    initMenu();
    initModals();
    initReservationForm();
    initAccordion();
    initMobileNav();
}});

function initMenu() {{
    const grid = document.getElementById("menu-grid");
    const searchInput = document.getElementById("menu-search");
    const filterPills = document.querySelectorAll(".filter-pill");

    let activeCategory = "all";
    let searchQuery = "";

    function renderDishes() {{
        if (!grid) return;
        const filtered = DISHES.filter(dish => {{
            const matchesCat = activeCategory === "all" || dish.category === activeCategory;
            const matchesSearch = !searchQuery ||
                dish.name.toLowerCase().includes(searchQuery) ||
                dish.description.toLowerCase().includes(searchQuery) ||
                dish.ingredients.toLowerCase().includes(searchQuery);
            return matchesCat && matchesSearch;
        }});

        if (filtered.length === 0) {{
            grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 3rem; color: var(--text-secondary);">No dishes found matching your selection.</div>`;
            return;
        }}

        grid.innerHTML = filtered.map(dish => `
            <article class="dish-card" data-id="${{dish.id}}">
                <div class="dish-image">
                    <img src="${{dish.image}}" alt="${{dish.name}}" >
                    <span class="dish-tag">${{dish.tag}}</span>
                </div>
                <div class="dish-body">
                    <div class="dish-header">
                        <h3 class="dish-title">${{dish.name}}</h3>
                        <span class="dish-price">${{dish.price}}</span>
                    </div>
                    <p class="dish-desc">${{dish.description}}</p>
                    <div class="dish-footer">
                        <div class="dish-dietary">
                            ${{dish.dietary.map(d => `<span class="dietary-badge">${{d}}</span>`).join("")}}
                        </div>
                        <button class="btn-details" onclick="openDishDetail('${{dish.id}}')">View Details &rarr;</button>
                    </div>
                </div>
            </article>
        `).join("");
    }}

    filterPills.forEach(pill => {{
        pill.addEventListener("click", () => {{
            filterPills.forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            activeCategory = pill.getAttribute("data-category") || "all";
            renderDishes();
        }});
    }});

    if (searchInput) {{
        searchInput.addEventListener("input", (e) => {{
            searchQuery = e.target.value.trim().toLowerCase();
            renderDishes();
        }});
    }}

    renderDishes();
}}

// Dish Details Modal
window.openDishDetail = function(dishId) {{
    const dish = DISHES.find(d => d.id === dishId);
    if (!dish) return;

    const modal = document.getElementById("dish-modal");
    const modalBody = document.getElementById("dish-modal-body");
    if (!modal || !modalBody) return;

    modalBody.innerHTML = `
        <img src="${{dish.image}}" alt="${{dish.name}}" style="width:100%; height:260px; object-fit:cover; border-radius:var(--radius-md); margin-bottom:1.5rem; border:1px solid var(--border-color);">
        <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:0.75rem;">
            <h2 style="font-family:var(--font-heading); color:var(--text-primary); font-size:1.8rem;">${{dish.name}}</h2>
            <span style="font-size:1.5rem; font-weight:700; color:var(--color-accent);">${{dish.price}}</span>
        </div>
        <p style="color:var(--text-secondary); font-size:1.05rem; line-height:1.6; margin-bottom:1.5rem;">${{dish.description}}</p>
        
        <div style="background:var(--bg-card); padding:1.25rem; border-radius:var(--radius-sm); border:1px solid var(--border-color); margin-bottom:1.25rem;">
            <strong style="color:var(--color-accent); font-size:0.85rem; text-transform:uppercase; letter-spacing:0.1em; display:block; margin-bottom:0.4rem;">Key Ingredients</strong>
            <p style="color:var(--text-primary); font-size:0.95rem;">${{dish.ingredients}}</p>
        </div>

        <div style="background:var(--bg-card); padding:1.25rem; border-radius:var(--radius-sm); border:1px solid var(--border-color); margin-bottom:1.5rem;">
            <strong style="color:var(--color-accent); font-size:0.85rem; text-transform:uppercase; letter-spacing:0.1em; display:block; margin-bottom:0.4rem;">Sommelier Beverage Pairing</strong>
            <p style="color:var(--text-primary); font-size:0.95rem;">${{dish.pairing}}</p>
        </div>

        <button class="btn-primary" style="width:100%; justify-content:center;" onclick="closeDishModalAndReserve()">Reserve Table for this Dish</button>
    `;

    modal.classList.add("open");
}};

function closeDishModalAndReserve() {{
    const dishModal = document.getElementById("dish-modal");
    if (dishModal) dishModal.classList.remove("open");
    const resModal = document.getElementById("reservation-modal");
    if (resModal) resModal.classList.add("open");
}}

function initModals() {{
    const dishModal = document.getElementById("dish-modal");
    const dishModalClose = document.getElementById("dish-modal-close");
    const resModal = document.getElementById("reservation-modal");
    const resModalClose = document.getElementById("reservation-modal-close");
    const navReserveBtn = document.getElementById("nav-reserve-btn");
    const heroReserveBtn = document.getElementById("hero-reserve-btn");
    const privateInquireBtn = document.getElementById("private-inquire-btn");

    if (dishModalClose && dishModal) {{
        dishModalClose.addEventListener("click", () => dishModal.classList.remove("open"));
        dishModal.addEventListener("click", (e) => {{
            if (e.target === dishModal) dishModal.classList.remove("open");
        }});
    }}

    function openRes() {{
        if (resModal) resModal.classList.add("open");
    }}

    if (navReserveBtn) navReserveBtn.addEventListener("click", openRes);
    if (heroReserveBtn) heroReserveBtn.addEventListener("click", openRes);
    if (privateInquireBtn) privateInquireBtn.addEventListener("click", openRes);

    if (resModalClose && resModal) {{
        resModalClose.addEventListener("click", () => resModal.classList.remove("open"));
        resModal.addEventListener("click", (e) => {{
            if (e.target === resModal) resModal.classList.remove("open");
        }});
    }}
}}

function initReservationForm() {{
    const form = document.getElementById("reservation-form");
    const toast = document.getElementById("toast");
    const resModal = document.getElementById("reservation-modal");

    const dateInput = document.getElementById("res-date");
    if (dateInput) {{
        const today = new Date().toISOString().split("T")[0];
        dateInput.min = today;
        dateInput.value = today;
    }}

    if (!form) return;
    form.addEventListener("submit", (e) => {{
        e.preventDefault();
        const name = document.getElementById("res-name").value;
        const date = document.getElementById("res-date").value;
        const time = document.getElementById("res-time").value;
        const guests = document.getElementById("res-guests").value;

        if (resModal) resModal.classList.remove("open");

        if (toast) {{
            toast.textContent = `Reservation confirmed for ${{name}} (${{guests}} guests on ${{date}} at ${{time}}). We look forward to welcoming you!`;
            toast.classList.add("show");
            setTimeout(() => {{
                toast.classList.remove("show");
            }}, 5000);
        }}

        form.reset();
    }});
}}

function initAccordion() {{
    const faqItems = document.querySelectorAll(".faq-item");
    faqItems.forEach(item => {{
        const questionBtn = item.querySelector(".faq-question");
        if (questionBtn) {{
            questionBtn.addEventListener("click", () => {{
                const isActive = item.classList.contains("active");
                faqItems.forEach(i => i.classList.remove("active"));
                if (!isActive) item.classList.add("active");
            }});
        }}
    }});
}}

function initMobileNav() {{
    const hamburger = document.getElementById("hamburger-btn");
    const navLinks = document.getElementById("nav-links");
    if (hamburger && navLinks) {{
        hamburger.addEventListener("click", () => {{
            const isFlex = navLinks.style.display === "flex";
            navLinks.style.display = isFlex ? "none" : "flex";
            if (!isFlex) {{
                navLinks.style.position = "absolute";
                navLinks.style.top = "100%";
                navLinks.style.left = "0";
                navLinks.style.right = "0";
                navLinks.style.flexDirection = "column";
                navLinks.style.background = "#141110";
                navLinks.style.padding = "1.5rem";
                navLinks.style.borderBottom = "1px solid #3d312a";
            }}
        }});
    }}
}}
"""
        js_path.write_text(js_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(js_path, ws, generator="foundation_scaffolder")
        logger.info(f"FoundationScaffolder: created {js_path.name}")

    return True

# 1. NORTHSTAR UNIVERSITY & EDUCATION FOUNDATION
# ==============================================================================

def _seed_education_foundation(
    ws: Path,
    prompt: str,
    contract: Optional[Any],
    design_brief: Optional[Any],
) -> bool:
    app_name = "NorthStar University"
    title = "NorthStar University — Excellence in Education & Research"

    # 1. package.json
    pkg_path = ws / "package.json"
    if not pkg_path.exists():
        pkg_data = {
            "name": "northstar-university",
            "version": "1.0.0",
            "description": "NorthStar University Official Web Portal",
            "main": "app.js",
            "scripts": {
                "start": "npx http-server -p 8080",
                "serve": "npx http-server -p 8080"
            }
        }
        pkg_path.write_text(json.dumps(pkg_data, indent=2), encoding="utf-8")
        logger.info(f"FoundationScaffolder: created {pkg_path.name}")

    # 2. style.css (Collegiate Navy, Royal Blue, Bronze/Gold, Warm Ivory)
    css_path = ws / "style.css"
    if not css_path.exists() or css_path.stat().st_size < 50:
        css_content = """/* ==========================================================================
   NorthStar University — Collegiate Design System
   ========================================================================== */

:root {
    --primary-color: #0b2545;       /* Collegiate Deep Navy */
    --primary-light: #134074;
    --royal-blue: #1d4ed8;          /* Vibrant Royal Blue */
    --accent-gold: #d4af37;         /* Heritage Academic Gold */
    --accent-hover: #b89628;
    --bg-main: #f8fafc;
    --bg-surface: #ffffff;
    --bg-warm: #fcfbf9;             /* Ivory Parchment Accent */
    --text-primary: #0f172a;        /* Deep Slate 900 */
    --text-secondary: #475569;      /* Slate 600 */
    --text-muted: #94a3b8;
    --border-color: #e2e8f0;
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 16px;
    --shadow-sm: 0 2px 4px rgba(11, 37, 69, 0.04);
    --shadow-md: 0 4px 12px rgba(11, 37, 69, 0.08);
    --shadow-lg: 0 10px 25px rgba(11, 37, 69, 0.12);
    --font-heading: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
    --font-body: 'Inter', system-ui, -apple-system, sans-serif;
    --transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

/* Base Reset */
*, *::before, *::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

html {
    scroll-behavior: smooth;
    font-size: 16px;
}

body {
    font-family: var(--font-body);
    background-color: var(--bg-main);
    color: var(--text-primary);
    line-height: 1.6;
    overflow-x: hidden;
}

img {
    max-width: 100%;
    height: auto;
    display: block;
}

a {
    color: inherit;
    text-decoration: none;
}

button {
    font-family: inherit;
    cursor: pointer;
    border: none;
    background: none;
}

.container {
    width: 100%;
    max-width: 1240px;
    margin: 0 auto;
    padding: 0 1.5rem;
}

.section-header {
    text-align: center;
    max-width: 720px;
    margin: 0 auto 3rem auto;
}

.section-header .tagline {
    color: var(--royal-blue);
    font-weight: 700;
    text-transform: uppercase;
    font-size: 0.85rem;
    letter-spacing: 0.1em;
    margin-bottom: 0.5rem;
    display: block;
}

.section-header h2 {
    font-family: var(--font-heading);
    font-size: clamp(2rem, 4vw, 2.75rem);
    color: var(--primary-color);
    margin-bottom: 0.75rem;
    line-height: 1.2;
}

.section-header p {
    color: var(--text-secondary);
    font-size: 1.1rem;
}

/* Header & Navigation */
.site-header {
    position: sticky;
    top: 0;
    z-index: 1000;
    background-color: rgba(255, 255, 255, 0.98);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--border-color);
    transition: var(--transition);
}

.navbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    height: 74px;
}

.brand-logo {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    font-family: var(--font-heading);
    font-size: 1.4rem;
    font-weight: 800;
    color: var(--primary-color);
}

.brand-logo .logo-crest {
    width: 32px;
    height: 32px;
    background: var(--primary-color);
    color: var(--accent-gold);
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1rem;
    font-weight: 900;
}

.nav-menu {
    display: flex;
    align-items: center;
    gap: 1.75rem;
    list-style: none;
}

.nav-link {
    font-weight: 600;
    font-size: 0.95rem;
    color: var(--text-secondary);
    transition: var(--transition);
    position: relative;
    padding: 0.5rem 0;
}

.nav-link:hover, .nav-link.active {
    color: var(--royal-blue);
}

.nav-actions {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.btn-primary {
    background-color: var(--royal-blue);
    color: #ffffff;
    font-weight: 700;
    padding: 0.65rem 1.4rem;
    border-radius: var(--radius-sm);
    transition: var(--transition);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.95rem;
}

.btn-primary:hover {
    background-color: #1e40af;
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(29, 78, 216, 0.25);
}

.btn-gold {
    background-color: var(--accent-gold);
    color: var(--primary-color);
    font-weight: 700;
    padding: 0.65rem 1.4rem;
    border-radius: var(--radius-sm);
    transition: var(--transition);
}

.btn-gold:hover {
    background-color: var(--accent-hover);
    transform: translateY(-2px);
}

.mobile-menu-btn {
    display: none;
    flex-direction: column;
    justify-content: center;
    gap: 5px;
    width: 44px;
    height: 44px;
    padding: 8px;
    cursor: pointer;
}

.mobile-menu-btn span {
    display: block;
    width: 24px;
    height: 2px;
    background-color: var(--primary-color);
    border-radius: 2px;
    transition: var(--transition);
}

/* Hero Section */
.hero {
    position: relative;
    min-height: 85vh;
    display: flex;
    align-items: center;
    background-color: var(--primary-color);
    background-image: url('assets/images/hero/hero-campus.jpg');
    background-size: cover;
    background-position: center;
    color: #ffffff;
    padding: 6rem 0;
    overflow: hidden;
}

.hero-overlay {
    position: absolute;
    inset: 0;
    background: linear-gradient(135deg, rgba(11, 37, 69, 0.90) 0%, rgba(19, 64, 116, 0.75) 100%);
    z-index: 1;
    pointer-events: none;
}

.hero-content {
    position: relative;
    z-index: 2;
    max-width: 800px;
}

.hero-badge {
    display: inline-block;
    background: rgba(212, 175, 55, 0.18);
    border: 1px solid var(--accent-gold);
    color: var(--accent-gold);
    font-size: 0.85rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    padding: 0.35rem 0.85rem;
    border-radius: 50px;
    margin-bottom: 1.25rem;
}

.hero-title {
    font-family: var(--font-heading);
    font-size: clamp(2.5rem, 5vw, 4rem);
    font-weight: 800;
    line-height: 1.15;
    margin-bottom: 1.25rem;
}

.hero-description {
    font-size: clamp(1.1rem, 2vw, 1.3rem);
    color: #e2e8f0;
    margin-bottom: 2rem;
    line-height: 1.6;
}

.hero-buttons {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
}

/* Stats Ribbon */
.stats-ribbon {
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border-color);
    padding: 2.5rem 0;
}

.stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 2rem;
    text-align: center;
}

.stat-item h3 {
    font-family: var(--font-heading);
    font-size: 2.5rem;
    font-weight: 800;
    color: var(--royal-blue);
    margin-bottom: 0.25rem;
}

.stat-item p {
    color: var(--text-secondary);
    font-weight: 600;
    font-size: 0.95rem;
}

/* Academic Schools & Programs */
.academics-section {
    padding: 6rem 0;
}

.filter-bar {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 1.5rem;
    margin-bottom: 3rem;
    background: var(--bg-surface);
    padding: 1rem 1.5rem;
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-sm);
    border: 1px solid var(--border-color);
}

.category-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
}

.filter-pill {
    padding: 0.5rem 1.1rem;
    border-radius: 50px;
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--text-secondary);
    background-color: var(--bg-main);
    border: 1px solid var(--border-color);
    transition: var(--transition);
}

.filter-pill:hover, .filter-pill.active {
    background-color: var(--royal-blue);
    color: #ffffff;
    border-color: var(--royal-blue);
}

.search-box {
    position: relative;
    min-width: 280px;
}

.search-input {
    width: 100%;
    padding: 0.65rem 1rem;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border-color);
    font-size: 0.95rem;
    outline: none;
    transition: var(--transition);
}

.search-input:focus {
    border-color: var(--royal-blue);
    box-shadow: 0 0 0 3px rgba(29, 78, 216, 0.15);
}

.cards-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 2rem;
}

.program-card {
    background: var(--bg-surface);
    border-radius: var(--radius-md);
    overflow: hidden;
    box-shadow: var(--shadow-md);
    border: 1px solid var(--border-color);
    transition: var(--transition);
    display: flex;
    flex-direction: column;
}

.program-card:hover {
    transform: translateY(-5px);
    box-shadow: var(--shadow-lg);
}

.program-card .card-media {
    height: 200px;
    position: relative;
    overflow: hidden;
}

.program-card .card-media img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: transform 0.4s ease;
}

.program-card:hover .card-media img {
    transform: scale(1.05);
}

.program-card .badge {
    position: absolute;
    top: 1rem;
    left: 1rem;
    background: rgba(11, 37, 69, 0.85);
    color: #ffffff;
    padding: 0.3rem 0.7rem;
    border-radius: var(--radius-sm);
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
}

.program-card .card-body {
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    flex-grow: 1;
}

.program-card h3 {
    font-family: var(--font-heading);
    font-size: 1.35rem;
    color: var(--primary-color);
    margin-bottom: 0.5rem;
}

.program-card p {
    color: var(--text-secondary);
    font-size: 0.95rem;
    margin-bottom: 1.25rem;
    flex-grow: 1;
}

.program-card .card-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 1rem;
    border-top: 1px solid var(--border-color);
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--royal-blue);
}

/* Admissions Timeline */
.admissions-section {
    padding: 6rem 0;
    background: var(--bg-warm);
    border-top: 1px solid var(--border-color);
    border-bottom: 1px solid var(--border-color);
}

.timeline-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1.5rem;
    margin-top: 2rem;
}

.timeline-card {
    background: var(--bg-surface);
    padding: 2rem 1.5rem;
    border-radius: var(--radius-md);
    border: 1px solid var(--border-color);
    box-shadow: var(--shadow-sm);
}

.timeline-step {
    font-family: var(--font-heading);
    font-size: 2rem;
    font-weight: 800;
    color: var(--accent-gold);
    margin-bottom: 0.5rem;
}

.timeline-card h4 {
    font-family: var(--font-heading);
    font-size: 1.2rem;
    color: var(--primary-color);
    margin-bottom: 0.5rem;
}

.timeline-card p {
    color: var(--text-secondary);
    font-size: 0.9rem;
}

/* FAQ Accordion */
.faq-section {
    padding: 6rem 0;
}

.faq-accordion {
    max-width: 820px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 1rem;
}

.faq-item {
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    overflow: hidden;
    transition: var(--transition);
}

.faq-question {
    width: 100%;
    padding: 1.25rem 1.5rem;
    text-align: left;
    font-family: var(--font-heading);
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--primary-color);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.faq-question .indicator {
    font-size: 1.3rem;
    color: var(--royal-blue);
    transition: transform 0.25s ease;
}

.faq-item.open .faq-question .indicator {
    transform: rotate(45deg);
}

.faq-answer {
    padding: 0 1.5rem 1.25rem 1.5rem;
    color: var(--text-secondary);
    font-size: 0.95rem;
    line-height: 1.6;
    display: none;
}

.faq-item.open .faq-answer {
    display: block;
}

/* Modal Dialog */
.modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(11, 37, 69, 0.6);
    backdrop-filter: blur(6px);
    z-index: 2000;
    display: none;
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
}

.modal-overlay.open {
    display: flex;
}

.modal-dialog {
    background: var(--bg-surface);
    width: 100%;
    max-width: 580px;
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-lg);
    overflow: hidden;
    position: relative;
    max-height: 90vh;
    overflow-y: auto;
}

.modal-header {
    padding: 1.5rem 2rem;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.modal-header h3 {
    font-family: var(--font-heading);
    color: var(--primary-color);
    font-size: 1.35rem;
}

.modal-close-btn {
    font-size: 1.5rem;
    color: var(--text-muted);
    cursor: pointer;
}

.modal-close-btn:hover {
    color: var(--primary-color);
}

.modal-body {
    padding: 2rem;
}

.form-group {
    margin-bottom: 1.25rem;
}

.form-group label {
    display: block;
    font-weight: 600;
    font-size: 0.9rem;
    margin-bottom: 0.35rem;
    color: var(--text-primary);
}

.form-control {
    width: 100%;
    padding: 0.7rem 0.9rem;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    font-family: inherit;
    font-size: 0.95rem;
    outline: none;
    transition: var(--transition);
}

.form-control:focus {
    border-color: var(--royal-blue);
    box-shadow: 0 0 0 3px rgba(29, 78, 216, 0.15);
}

/* Footer */
.site-footer {
    background: var(--primary-color);
    color: #ffffff;
    padding: 4rem 0 2rem 0;
}

.footer-grid {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr 1fr;
    gap: 3rem;
    margin-bottom: 3rem;
}

.footer-brand p {
    color: #94a3b8;
    margin-top: 1rem;
    max-width: 320px;
    font-size: 0.95rem;
}

.footer-col h4 {
    font-family: var(--font-heading);
    color: var(--accent-gold);
    margin-bottom: 1.25rem;
    font-size: 1.05rem;
}

.footer-links {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
}

.footer-links a {
    color: #cbd5e1;
    font-size: 0.9rem;
    transition: var(--transition);
}

.footer-links a:hover {
    color: var(--accent-gold);
}

.footer-bottom {
    text-align: center;
    padding-top: 2rem;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    color: #94a3b8;
    font-size: 0.85rem;
}

/* Responsive Rules (1024px, 768px, 390px) */
@media (max-width: 1024px) {
    .stats-grid {
        grid-template-columns: repeat(2, 1fr);
    }
    .timeline-grid {
        grid-template-columns: repeat(2, 1fr);
    }
    .footer-grid {
        grid-template-columns: 1fr 1fr;
    }
}

@media (max-width: 768px) {
    .navbar {
        height: 64px;
    }
    .mobile-menu-btn {
        display: flex;
    }
    .nav-menu {
        position: absolute;
        top: 64px;
        left: 0;
        width: 100%;
        background: #ffffff;
        flex-direction: column;
        padding: 2rem;
        gap: 1.25rem;
        border-bottom: 1px solid var(--border-color);
        box-shadow: var(--shadow-md);
        display: none;
    }
    .nav-menu.active {
        display: flex;
    }
    .nav-actions {
        display: none;
    }
    .cards-grid {
        grid-template-columns: 1fr;
    }
    .timeline-grid {
        grid-template-columns: 1fr;
    }
    .footer-grid {
        grid-template-columns: 1fr;
    }
}

@media (max-width: 390px) {
    .hero {
        padding: 4rem 0;
    }
    .stats-grid {
        grid-template-columns: 1fr;
    }
}
"""
        css_path.write_text(css_content, encoding="utf-8")
        logger.info(f"FoundationScaffolder: created {css_path.name}")

    # 3. index.html (NorthStar University Portal)
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NorthStar University — Excellence in Education & Research</title>
    <link rel="stylesheet" href="style.css">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@700;800&display=swap" rel="stylesheet">
</head>
<body>

    <!-- Navigation Header -->
    <header class="site-header" id="navbar">
        <div class="container navbar">
            <a href="#" class="brand-logo">
                <span class="logo-crest">NU</span>
                <span>NorthStar University</span>
            </a>
            <ul class="nav-menu" id="nav-menu">
                <li><a href="#about" class="nav-link active">About</a></li>
                <li><a href="#academics" class="nav-link">Academics</a></li>
                <li><a href="#admissions" class="nav-link">Admissions</a></li>
                <li><a href="#faculty" class="nav-link">Faculty</a></li>
                <li><a href="#research" class="nav-link">Research</a></li>
                <li><a href="#campus-life" class="nav-link">Campus Life</a></li>
                <li><a href="#events" class="nav-link">Events</a></li>
                <li><a href="#contact" class="nav-link">Contact</a></li>
            </ul>
            <div class="nav-actions">
                <button class="btn-primary" id="btn-request-info">Request Info</button>
            </div>
            <button class="mobile-menu-btn" id="mobile-menu-btn" aria-label="Toggle navigation" aria-expanded="false">
                <span></span>
                <span></span>
                <span></span>
            </button>
        </div>
    </header>

    <main id="app">

        <!-- Hero Section -->
        <section class="hero" id="hero">
            <div class="hero-overlay"></div>
            <div class="container">
                <div class="hero-content">
                    <span class="hero-badge">Est. 1892 · Top 25 Research Institution</span>
                    <h1 class="hero-title">Empowering Minds, Shaping Tomorrow</h1>
                    <p class="hero-description">NorthStar University unites world-class faculty, cutting-edge laboratories, and a vibrant diverse student community to solve humanity's greatest challenges.</p>
                    <div class="hero-buttons">
                        <a href="#academics" class="btn-gold" id="btn-explore-academics">Explore Programs</a>
                        <a href="#admissions" class="btn-primary" id="btn-apply-now">Apply for Admission</a>
                    </div>
                </div>
            </div>
        </section>

        <!-- Stats Ribbon -->
        <section class="stats-ribbon">
            <div class="container stats-grid">
                <div class="stat-item">
                    <h3>12:1</h3>
                    <p>Student-to-Faculty Ratio</p>
                </div>
                <div class="stat-item">
                    <h3>150+</h3>
                    <p>Undergraduate & Graduate Degrees</p>
                </div>
                <div class="stat-item">
                    <h3>$420M</h3>
                    <p>Annual Research Expenditure</p>
                </div>
                <div class="stat-item">
                    <h3>96%</h3>
                    <p>Career Placement Within 6 Months</p>
                </div>
            </div>
        </section>

        <!-- About NorthStar Section -->
        <section class="container" id="about" style="padding: 6rem 1.5rem;">
            <div class="section-header">
                <span class="tagline">Our Heritage & Mission</span>
                <h2>A Tradition of Academic Distinction</h2>
                <p>Rooted in visionary inquiry, NorthStar University cultivates leaders who champion truth, ethical stewardship, and global innovation.</p>
            </div>
        </section>

        <!-- Academics & Degree Programs Section -->
        <section class="academics-section" id="academics">
            <div class="container">
                <div class="section-header">
                    <span class="tagline">Curriculum & Degrees</span>
                    <h2>Academic Schools & Programs</h2>
                    <p>Explore rigorous undergraduate and graduate programs across engineering, sciences, business, and humanities.</p>
                </div>

                <!-- Program Filter & Search Bar -->
                <div class="filter-bar" id="filter-buttons">
                    <div class="category-pills" id="program-categories">
                        <button class="filter-pill active" data-category="all">All Schools</button>
                        <button class="filter-pill" data-category="engineering">Engineering</button>
                        <button class="filter-pill" data-category="sciences">Arts & Sciences</button>
                        <button class="filter-pill" data-category="business">Business</button>
                        <button class="filter-pill" data-category="medicine">Medicine</button>
                    </div>
                    <div class="search-box">
                        <input type="text" id="search-input" class="search-input" placeholder="Search degree programs or majors...">
                    </div>
                </div>

                <!-- Dynamic Programs Grid -->
                <div class="cards-grid" id="programs-grid">
                    <!-- Injected dynamically by app.js -->
                </div>
            </div>
        </section>

        <!-- Admissions Steps -->
        <section class="admissions-section" id="admissions">
            <div class="container">
                <div class="section-header">
                    <span class="tagline">Join Our Community</span>
                    <h2>Admissions & Enrollment Process</h2>
                    <p>Clear, accessible pathways to start your academic journey at NorthStar University.</p>
                </div>
                <div class="timeline-grid">
                    <div class="timeline-card">
                        <div class="timeline-step">01</div>
                        <h4>Submit Application</h4>
                        <p>Complete the online admissions portal with academic transcripts and personal statement.</p>
                    </div>
                    <div class="timeline-card">
                        <div class="timeline-step">02</div>
                        <h4>Financial Aid</h4>
                        <p>Over 85% of incoming freshmen receive merit scholarships or need-based institutional grants.</p>
                    </div>
                    <div class="timeline-card">
                        <div class="timeline-step">03</div>
                        <h4>Campus Visit</h4>
                        <p>Tour historic lecture halls, research facilities, and residence halls in person or virtually.</p>
                    </div>
                    <div class="timeline-card">
                        <div class="timeline-step">04</div>
                        <h4>Enroll & Thrive</h4>
                        <p>Confirm your enrollment, register for orientation, and meet your academic advisor.</p>
                    </div>
                </div>
            </div>
        </section>

        <!-- Faculty Section -->
        <section class="container" id="faculty" style="padding: 6rem 1.5rem;">
            <div class="section-header">
                <span class="tagline">World-Class Educators</span>
                <h2>Distinguished Faculty & Leadership</h2>
                <p>Learn alongside pioneering scientists, renowned authors, and Fulbright scholars.</p>
            </div>
            <div class="cards-grid" id="faculty-grid">
                <!-- Injected dynamically by app.js -->
            </div>
        </section>

        <!-- Campus Life Section -->
        <section class="container" id="campus-life" style="padding: 6rem 1.5rem; background: var(--bg-warm); border-radius: var(--radius-lg); margin-bottom: 4rem;">
            <div class="section-header">
                <span class="tagline">Vibrant Collegiate Living</span>
                <h2>Campus Life & Housing</h2>
                <p>120+ student clubs, NCAA Division I athletics, and inclusive residential communities.</p>
            </div>
        </section>

        <!-- Research Centers -->
        <section class="container" id="research" style="padding: 4rem 1.5rem;">
            <div class="section-header">
                <span class="tagline">Innovation & Impact</span>
                <h2>Research Centers of Excellence</h2>
                <p>Pioneering advancements in quantum materials, biotechnology, sustainable energy, and AI ethics.</p>
            </div>
        </section>

        <!-- Events & Academic Calendar -->
        <section class="container" id="events" style="padding: 4rem 1.5rem;">
            <div class="section-header">
                <span class="tagline">University Calendar</span>
                <h2>Upcoming Campus Events</h2>
                <p>Join guest lectures, research symposiums, fine arts performances, and athletic matches.</p>
            </div>
            <div id="events-list" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1.5rem; margin-top: 2rem;">
                <div class="event-card" style="background: white; border: 1px solid var(--border-color); border-radius: var(--card-radius); padding: 1.5rem; box-shadow: var(--shadow-sm);">
                    <div style="font-weight: 700; color: var(--accent-color); font-size: 0.875rem; text-transform: uppercase;">Nov 18, 2026 &bull; Hall of Sciences</div>
                    <h3 style="margin: 0.5rem 0; font-size: 1.25rem;">Annual Frontier Quantum Computing Symposium</h3>
                    <p style="color: var(--text-muted); font-size: 0.95rem;">Keynote lectures by visiting scholars and student poster demonstrations.</p>
                </div>
                <div class="event-card" style="background: white; border: 1px solid var(--border-color); border-radius: var(--card-radius); padding: 1.5rem; box-shadow: var(--shadow-sm);">
                    <div style="font-weight: 700; color: var(--accent-color); font-size: 0.875rem; text-transform: uppercase;">Dec 05, 2026 &bull; Grand Auditorium</div>
                    <h3 style="margin: 0.5rem 0; font-size: 1.25rem;">Global Leadership Summit & MBA Panel</h3>
                    <p style="color: var(--text-muted); font-size: 0.95rem;">Executive roundtable discussing international commerce, ethics, and innovation.</p>
                </div>
            </div>
        </section>

        <!-- FAQ Section -->
        <section class="faq-section" id="faq">
            <div class="container">
                <div class="section-header">
                    <span class="tagline">Answers & Guidance</span>
                    <h2>Frequently Asked Questions</h2>
                    <p>Key information regarding admissions requirements, credit transfers, and campus housing.</p>
                </div>
                <div class="faq-accordion" id="faq-accordion">
                    <div class="faq-item open">
                        <button class="faq-question">What are the application deadlines for Fall admission?<span class="indicator">+</span></button>
                        <div class="faq-answer">Early Action applications are due November 1st with decisions released by mid-December. Regular Decision applications close January 15th.</div>
                    </div>
                    <div class="faq-item">
                        <button class="faq-question">How does NorthStar University award financial aid and scholarships?<span class="indicator">+</span></button>
                        <div class="faq-answer">All domestic and international applicants are automatically reviewed for merit-based scholarships upon submitting their application. Over 85% of undergraduates receive aid.</div>
                    </div>
                    <div class="faq-item">
                        <button class="faq-question">Are undergraduate students able to participate in faculty research?<span class="indicator">+</span></button>
                        <div class="faq-answer">Yes! Over 68% of undergraduates engage in funded research alongside faculty mentors starting from their second year across all academic disciplines.</div>
                    </div>
                    <div class="faq-item">
                        <button class="faq-question">Is on-campus residential housing guaranteed for freshmen?<span class="indicator">+</span></button>
                        <div class="faq-answer">Yes, on-campus housing in modern collegiate residence halls is guaranteed for all first-year and second-year undergraduate students.</div>
                    </div>
                </div>
            </div>
        </section>

    </main>

    <!-- Inquiry / Campus Visit Modal -->
    <div class="modal-overlay" id="inquiry-modal">
        <div class="modal-dialog">
            <div class="modal-header">
                <h3>Request University Information</h3>
                <button class="modal-close-btn" id="modal-close">&times;</button>
            </div>
            <div class="modal-body">
                <form id="inquiry-form">
                    <div class="form-group">
                        <label for="student-name">Full Name</label>
                        <input type="text" id="student-name" class="form-control" placeholder="Jane Doe" required>
                    </div>
                    <div class="form-group">
                        <label for="student-email">Email Address</label>
                        <input type="email" id="student-email" class="form-control" placeholder="jane@example.com" required>
                    </div>
                    <div class="form-group">
                        <label for="program-interest">Academic Interest</label>
                        <select id="program-interest" class="form-control" required>
                            <option value="">Select a School</option>
                            <option value="engineering">School of Engineering</option>
                            <option value="arts">College of Arts & Sciences</option>
                            <option value="business">School of Business</option>
                            <option value="medicine">School of Medicine</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="visit-date">Preferred Campus Visit Date</label>
                        <input type="date" id="visit-date" class="form-control">
                    </div>
                    <button type="submit" class="btn-primary" style="width: 100%; margin-top: 1rem;">Submit Inquiry</button>
                </form>
            </div>
        </div>
    </div>

    <!-- University Footer -->
    <footer class="site-footer" id="contact">
        <div class="container footer-grid">
            <div class="footer-brand">
                <a href="#" class="brand-logo" style="color: #ffffff;">
                    <span class="logo-crest">NU</span>
                    <span>NorthStar University</span>
                </a>
                <p>Empowering scholars, researchers, and global innovators. Accredited by the Higher Learning Commission.</p>
            </div>
            <div class="footer-col">
                <h4>Academics</h4>
                <ul class="footer-links">
                    <li><a href="#academics">Undergraduate Majors</a></li>
                    <li><a href="#academics">Graduate Studies</a></li>
                    <li><a href="#faculty">Faculty Directory</a></li>
                    <li><a href="#research">Research Labs</a></li>
                </ul>
            </div>
            <div class="footer-col">
                <h4>Admissions</h4>
                <ul class="footer-links">
                    <li><a href="#admissions">How to Apply</a></li>
                    <li><a href="#admissions">Tuition & Financial Aid</a></li>
                    <li><a href="#inquiry-modal">Campus Tours</a></li>
                    <li><a href="#faq">Admissions FAQ</a></li>
                </ul>
            </div>
            <div class="footer-col">
                <h4>Connect</h4>
                <ul class="footer-links">
                    <li><a href="#contact">Campus Directory</a></li>
                    <li><a href="#contact">Alumni Network</a></li>
                    <li><a href="#contact">Athletics</a></li>
                    <li><a href="#contact">Emergency Contacts</a></li>
                </ul>
            </div>
        </div>
        <div class="footer-bottom">
            <p>&copy; 2026 NorthStar University. All rights reserved. Equal Opportunity Institution.</p>
        </div>
    </footer>

    <script src="app.js"></script>
</body>
</html>
"""
    (ws / "index.html").write_text(html_content, encoding="utf-8")
    logger.info("FoundationScaffolder: created NorthStar University index.html")

    # 4. app.js (Dynamic Academic Program & Faculty Injection, Filtering, Modals, Accordions)
    js_content = """// NorthStar University — Official Client Application Logic
document.addEventListener('DOMContentLoaded', () => {
    // 1. Academic Degree Programs Dataset
    const programs = [
        {
            id: 'prog-cs',
            category: 'engineering',
            title: 'Computer Science & Artificial Intelligence',
            degree: 'B.S. / M.S.',
            school: 'School of Engineering',
            desc: 'Pioneering machine intelligence, distributed systems, and quantum algorithms with hands-on lab projects.',
            image: 'assets/images/academics/engineering.jpg',
            credits: '128 Credits'
        },
        {
            id: 'prog-bio',
            category: 'sciences',
            title: 'Molecular Biology & Genetics',
            degree: 'B.S. / Ph.D.',
            school: 'College of Arts & Sciences',
            desc: 'Leading genomics research, cellular pathways, and CRISPR therapeutic applications in advanced research suites.',
            image: 'assets/images/academics/arts-sciences.jpg',
            credits: '124 Credits'
        },
        {
            id: 'prog-fin',
            category: 'business',
            title: 'Global Finance & Quantitative Economics',
            degree: 'B.B.A. / M.B.A.',
            school: 'School of Business',
            desc: 'Algorithmic asset modeling, corporate valuation, and venture incubation with real portfolio management.',
            image: 'assets/images/academics/business.jpg',
            credits: '120 Credits'
        },
        {
            id: 'prog-med',
            category: 'medicine',
            title: 'Biomedical Engineering & Pre-Medicine',
            degree: 'B.S. / M.D.',
            school: 'School of Medicine',
            desc: 'Integrating bio-materials, neuro-prosthetics, and clinical diagnostics in collaboration with academic hospitals.',
            image: 'assets/images/academics/medicine.jpg',
            credits: '136 Credits'
        },
        {
            id: 'prog-mech',
            category: 'engineering',
            title: 'Aerospace & Mechanical Engineering',
            degree: 'B.S. / M.S.',
            school: 'School of Engineering',
            desc: 'Aerodynamics, autonomous propulsion, and advanced composite materials with wind-tunnel testing.',
            image: 'assets/images/academics/engineering.jpg',
            credits: '132 Credits'
        },
        {
            id: 'prog-data',
            category: 'business',
            title: 'Business Analytics & Decision Science',
            degree: 'M.S.',
            school: 'School of Business',
            desc: 'Executive data modeling, machine learning for market intelligence, and organizational strategy.',
            image: 'assets/images/academics/business.jpg',
            credits: '36 Credits'
        }
    ];

    // 2. Faculty Dataset
    const faculty = [
        {
            name: 'Dr. Evelyn Mitchell',
            title: 'Chair of Computer Science',
            school: 'School of Engineering',
            awards: 'Turing Fellow · IEEE Pioneer',
            image: 'assets/images/faculty/dr-mitchell.jpg'
        },
        {
            name: 'Dr. Arthur Vance',
            title: 'Professor of Molecular Genetics',
            school: 'College of Arts & Sciences',
            awards: 'National Academy of Sciences',
            image: 'assets/images/testimonials/sarah-chen.jpg'
        },
        {
            name: 'Dr. Marcus Thorne',
            title: 'Dean of Business Innovation',
            school: 'School of Business',
            awards: 'Former World Bank Senior Advisor',
            image: 'assets/images/campus/campus-life.jpg'
        }
    ];

    // 3. Render Programs
    const programsGrid = document.getElementById('programs-grid');
    function renderPrograms(list) {
        if (!programsGrid) return;
        if (list.length === 0) {
            programsGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 3rem; background: #fff; border-radius: 8px;"><h3>No programs found</h3><p>Try clearing your search query or selecting a different academic school.</p></div>';
            return;
        }
        programsGrid.innerHTML = list.map(p => `
            <div class="program-card" data-category="${p.category}">
                <div class="card-media">
                    <img src="${p.image}" alt="${p.title}" onerror="this.src='assets/images/hero/hero-campus.jpg'">
                    <span class="badge">${p.degree}</span>
                </div>
                <div class="card-body">
                    <h3>${p.title}</h3>
                    <p style="font-size: 0.85rem; font-weight: 700; color: var(--royal-blue); margin-bottom: 0.5rem;">${p.school}</p>
                    <p>${p.desc}</p>
                    <div class="card-meta">
                        <span>${p.credits}</span>
                        <a href="#inquiry-modal" class="learn-more-link" style="color: var(--royal-blue); font-weight: 700;">Program Details &rarr;</a>
                    </div>
                </div>
            </div>
        `).join('');
    }

    // 4. Render Faculty
    const facultyGrid = document.getElementById('faculty-grid');
    function renderFaculty() {
        if (!facultyGrid) return;
        facultyGrid.innerHTML = faculty.map(f => `
            <div class="program-card">
                <div class="card-media" style="height: 240px;">
                    <img src="${f.image}" alt="${f.name}" onerror="this.src='assets/images/hero/hero-campus.jpg'">
                </div>
                <div class="card-body">
                    <h3>${f.name}</h3>
                    <p style="font-weight: 700; color: var(--royal-blue); margin-bottom: 0.25rem;">${f.title}</p>
                    <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.75rem;">${f.school}</p>
                    <p style="font-size: 0.85rem; color: var(--accent-gold); font-weight: 600;">${f.awards}</p>
                </div>
            </div>
        `).join('');
    }

    renderPrograms(programs);
    renderFaculty();

    // 5. Category Filtering
    let currentCategory = 'all';
    let searchQuery = '';

    const filterPills = document.querySelectorAll('#program-categories .filter-pill');
    filterPills.forEach(pill => {
        pill.addEventListener('click', () => {
            filterPills.forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            currentCategory = pill.getAttribute('data-category') || 'all';
            applyFilter();
        });
    });

    // 6. Search Input Filtering
    const searchInput = document.getElementById('search-input');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            searchQuery = e.target.value.toLowerCase().trim();
            applyFilter();
        });
    }

    function applyFilter() {
        const filtered = programs.filter(p => {
            const matchesCategory = (currentCategory === 'all') || (p.category === currentCategory);
            const matchesSearch = !searchQuery ||
                p.title.toLowerCase().includes(searchQuery) ||
                p.desc.toLowerCase().includes(searchQuery) ||
                p.school.toLowerCase().includes(searchQuery);
            return matchesCategory && matchesSearch;
        });
        renderPrograms(filtered);
    }

    // 7. FAQ Accordion
    const faqItems = document.querySelectorAll('.faq-item');
    faqItems.forEach(item => {
        const btn = item.querySelector('.faq-question');
        if (btn) {
            btn.addEventListener('click', () => {
                const isOpen = item.classList.contains('open');
                faqItems.forEach(i => i.classList.remove('open'));
                if (!isOpen) item.classList.add('open');
            });
        }
    });

    // 8. Inquiry Modal Controls
    const modal = document.getElementById('inquiry-modal');
    const btnRequest = document.getElementById('btn-request-info');
    const modalClose = document.getElementById('modal-close');

    function openModal() {
        if (modal) modal.classList.add('open');
    }

    function closeModal() {
        if (modal) modal.classList.remove('open');
    }

    if (btnRequest) btnRequest.addEventListener('click', openModal);
    if (modalClose) modalClose.addEventListener('click', closeModal);
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal();
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal && modal.classList.contains('open')) {
            closeModal();
        }
    });

    // 9. Inquiry Form Validation & Submission
    const inquiryForm = document.getElementById('inquiry-form');
    if (inquiryForm) {
        inquiryForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const sName = document.getElementById('student-name')?.value;
            alert(`Thank you, ${sName}! Your academic inquiry has been received. Our admissions team will contact you shortly.`);
            inquiryForm.reset();
            closeModal();
        });
    }

    // 10. Mobile Menu Toggle
    const mobileBtn = document.getElementById('mobile-menu-btn');
    const navMenu = document.getElementById('nav-menu');
    if (mobileBtn && navMenu) {
        mobileBtn.addEventListener('click', () => {
            const active = navMenu.classList.toggle('active');
            mobileBtn.setAttribute('aria-expanded', active ? 'true' : 'false');
        });
    }
});
"""
    (ws / "app.js").write_text(js_content, encoding="utf-8")
    logger.info("FoundationScaffolder: created NorthStar University app.js")

    return True


# ==============================================================================
# 2. GENERAL / NEUTRAL GREENFIELD FOUNDATION
# ==============================================================================

def _seed_architecture_foundation(
    ws: Path,
    prompt: str,
    contract: Optional[Any],
    design_brief: Optional[Any],
) -> bool:
    from tools.security import WorkspaceOwnershipManifest
    from core.design_intelligence import detect_brand_name

    brand = detect_brand_name(prompt)
    app_name = brand if brand != "Application" else "FORM & FIELD"
    slug = app_name.lower().replace(" ", "-").replace("&", "and")
    title = f"{app_name} — Architectural Mastery & Interior Design Studio"
    desc_text = f"{app_name} is an independent architecture and interior design studio crafting timeless spaces with sustainable materials, monolithic forms, and serene spatial balance."

    # 1. package.json
    pkg_path = ws / "package.json"
    if not pkg_path.exists():
        pkg_data = {
            "name": slug,
            "version": "1.0.0",
            "description": f"{title} Web Portal",
            "main": "app.js",
            "scripts": {
                "start": "npx http-server -p 8080",
                "serve": "npx http-server -p 8080"
            }
        }
        pkg_path.write_text(json.dumps(pkg_data, indent=2), encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(pkg_path, ws, generator="foundation_scaffolder")

    # 2. style.css
    css_path = ws / "style.css"
    if not css_path.exists() or css_path.stat().st_size < 50:
        css_content = """/* FORM & FIELD - Architecture & Interior Design Studio System */
:root {
    --primary-color: #1c1d21;
    --secondary-color: #556b2f;
    --accent-color: #8c7b65;
    --bg-main: #fbf9f5;
    --bg-card: #ffffff;
    --bg-surface: #f3efe6;
    --text-primary: #1c1d21;
    --text-secondary: #575a61;
    --text-muted: #8c9099;
    --border-color: #e5e2da;
    --border-focus: #556b2f;
    --radius-sm: 4px;
    --radius-md: 8px;
    --radius-lg: 14px;
    --radius-full: 9999px;
    --shadow-card: 0 4px 20px -2px rgba(28, 29, 33, 0.08);
    --shadow-hover: 0 12px 32px -4px rgba(28, 29, 33, 0.14);
    --font-display: 'Playfair Display', 'Cormorant Garamond', 'Cinzel', Georgia, serif;
    --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    --transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

*, *::before, *::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

html {
    scroll-behavior: smooth;
    overflow-x: hidden;
}

body {
    font-family: var(--font-sans);
    background-color: var(--bg-main);
    color: var(--text-primary);
    line-height: 1.65;
    overflow-x: hidden;
    -webkit-font-smoothing: antialiased;
}

.container {
    width: 100%;
    max-width: 1280px;
    margin: 0 auto;
    padding: 0 1.5rem;
}

.card {
    background-color: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    overflow: hidden;
    transition: var(--transition);
}

.grid {
    display: grid;
    gap: 2rem;
}

/* Header & Navigation */
.site-header {
    position: sticky;
    top: 0;
    z-index: 100;
    background: rgba(251, 249, 245, 0.95);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border-color);
}

.navbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 72px;
}

.nav-brand {
    font-family: var(--font-display);
    font-size: 1.45rem;
    font-weight: 700;
    color: var(--primary-color);
    text-decoration: none;
    letter-spacing: 0.06em;
}

.nav-links {
    display: flex;
    gap: 2rem;
    list-style: none;
    align-items: center;
}

.nav-link {
    color: var(--text-secondary);
    text-decoration: none;
    font-size: 0.92rem;
    font-weight: 500;
    transition: var(--transition);
}

.nav-link:hover {
    color: var(--secondary-color);
}

.mobile-menu-btn {
    display: none;
    background: none;
    border: none;
    cursor: pointer;
    padding: 8px;
}

.mobile-menu-btn span {
    display: block;
    width: 24px;
    height: 2px;
    background: var(--primary-color);
    margin: 5px 0;
    transition: var(--transition);
}

/* Atmospheric Monolithic Hero */
.hero {
    min-height: 85vh;
    display: flex;
    align-items: center;
    position: relative;
    background-color: var(--primary-color);
    background-size: cover;
    background-position: center;
    color: #fbf9f5;
    padding: 7rem 0;
    overflow: hidden;
}

.hero-overlay {
    position: absolute;
    inset: 0;
    background: linear-gradient(135deg, rgba(28, 29, 33, 0.92) 0%, rgba(85, 107, 47, 0.45) 100%);
    z-index: 1;
    pointer-events: none;
}

.hero-content {
    position: relative;
    z-index: 2;
    max-width: 820px;
}

.hero-tagline {
    display: inline-block;
    font-size: 0.85rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: #d5ded0;
    margin-bottom: 1.25rem;
}

.hero-title {
    font-family: var(--font-display);
    font-size: clamp(2.5rem, 5.5vw, 4.4rem);
    line-height: 1.15;
    margin-bottom: 1.5rem;
    letter-spacing: -0.02em;
}

.hero-subhead {
    font-size: clamp(1.1rem, 2vw, 1.35rem);
    color: #d1d5db;
    line-height: 1.6;
    margin-bottom: 2.25rem;
    max-width: 680px;
}

.btn-primary {
    display: inline-flex;
    align-items: center;
    padding: 0.85rem 1.85rem;
    background: var(--secondary-color);
    color: #fff;
    text-decoration: none;
    font-weight: 600;
    border-radius: var(--radius-sm);
    border: none;
    cursor: pointer;
    transition: var(--transition);
}

.btn-primary:hover {
    background: #435424;
    transform: translateY(-2px);
}

.btn-outline {
    display: inline-flex;
    align-items: center;
    padding: 0.85rem 1.85rem;
    background: transparent;
    color: #fbf9f5;
    text-decoration: none;
    font-weight: 600;
    border-radius: var(--radius-sm);
    border: 1px solid rgba(251, 249, 245, 0.4);
    cursor: pointer;
    margin-left: 1rem;
    transition: var(--transition);
}

.btn-outline:hover {
    background: rgba(251, 249, 245, 0.15);
}

/* Sustainable Design Philosophy */
.about-section {
    padding: 6.5rem 0;
    background: var(--bg-card);
    border-top: 1px solid var(--border-color);
    border-bottom: 1px solid var(--border-color);
}

.section-tag {
    font-size: 0.82rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--secondary-color);
    margin-bottom: 0.75rem;
}

.section-title {
    font-family: var(--font-display);
    font-size: clamp(2rem, 3.5vw, 2.75rem);
    color: var(--primary-color);
    margin-bottom: 1.25rem;
    letter-spacing: -0.01em;
}

.section-lead {
    font-size: 1.15rem;
    color: var(--text-secondary);
    max-width: 720px;
    line-height: 1.65;
}

.pillars-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 2.5rem;
    margin-top: 3.5rem;
}

.pillar-card {
    padding: 2.25rem;
    background: var(--bg-main);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    transition: var(--transition);
}

.pillar-card:hover {
    transform: translateY(-4px);
    box-shadow: var(--shadow-card);
    border-color: var(--secondary-color);
}

.pillar-number {
    font-family: var(--font-display);
    font-size: 2.5rem;
    font-weight: 700;
    color: var(--secondary-color);
    margin-bottom: 0.75rem;
}

.pillar-title {
    font-family: var(--font-display);
    font-size: 1.3rem;
    color: var(--primary-color);
    margin-bottom: 0.85rem;
}

.pillar-text {
    font-size: 0.95rem;
    color: var(--text-secondary);
    line-height: 1.65;
}

/* Curated Project Portfolio */
.portfolio-section {
    padding: 6.5rem 0;
}

.filter-container {
    display: flex;
    flex-wrap: wrap;
    gap: 1.5rem;
    align-items: center;
    justify-content: space-between;
    margin-top: 2.5rem;
    margin-bottom: 3rem;
    padding: 1.25rem 1.75rem;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
}

.search-box {
    flex: 1;
    min-width: 260px;
}

.search-input {
    width: 100%;
    padding: 0.75rem 1.25rem;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    background: var(--bg-main);
    font-size: 0.95rem;
    color: var(--text-primary);
    transition: var(--transition);
}

.search-input:focus {
    outline: none;
    border-color: var(--border-focus);
    box-shadow: 0 0 0 2px rgba(85, 107, 47, 0.15);
}

.filter-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
}

.filter-pill {
    padding: 0.5rem 1.25rem;
    border: 1px solid var(--border-color);
    background: var(--bg-main);
    color: var(--text-secondary);
    border-radius: var(--radius-full);
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 500;
    transition: var(--transition);
}

.filter-pill.active, .filter-pill:hover {
    background: var(--primary-color);
    color: #fff;
    border-color: var(--primary-color);
}

.portfolio-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: 2.25rem;
}

.project-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    overflow: hidden;
    transition: var(--transition);
    display: flex;
    flex-direction: column;
}

.project-card:hover {
    transform: translateY(-6px);
    box-shadow: var(--shadow-hover);
    border-color: #d1cbbd;
}

.project-image-wrap {
    position: relative;
    aspect-ratio: 16/10;
    overflow: hidden;
    background: #242526;
}

.project-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: transform 0.5s ease;
}

.project-card:hover .project-img {
    transform: scale(1.05);
}

.project-badge {
    position: absolute;
    top: 1rem;
    left: 1rem;
    background: rgba(28, 29, 33, 0.85);
    color: #fff;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 0.35rem 0.75rem;
    border-radius: var(--radius-full);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    backdrop-filter: blur(6px);
}

.project-body {
    padding: 1.75rem;
    display: flex;
    flex-direction: column;
    flex: 1;
}

.project-meta {
    font-size: 0.82rem;
    color: var(--secondary-color);
    font-weight: 600;
    margin-bottom: 0.5rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

.project-title {
    font-family: var(--font-display);
    font-size: 1.35rem;
    color: var(--primary-color);
    margin-bottom: 0.75rem;
    line-height: 1.3;
}

.project-desc {
    font-size: 0.95rem;
    color: var(--text-secondary);
    line-height: 1.6;
    margin-bottom: 1.5rem;
    flex: 1;
}

.btn-project-details {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    padding: 0.8rem;
    background: var(--bg-main);
    color: var(--primary-color);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    font-weight: 600;
    font-size: 0.88rem;
    cursor: pointer;
    transition: var(--transition);
}

.btn-project-details:hover {
    background: var(--primary-color);
    color: #fff;
}

/* Studio Disciplines & Services */
.services-section {
    padding: 6.5rem 0;
    background: var(--bg-surface);
    border-top: 1px solid var(--border-color);
    border-bottom: 1px solid var(--border-color);
}

.services-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 2rem;
    margin-top: 3.5rem;
}

.service-card {
    padding: 2.25rem;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
}

.service-title {
    font-family: var(--font-display);
    font-size: 1.25rem;
    color: var(--primary-color);
    margin-bottom: 0.75rem;
}

.service-desc {
    font-size: 0.95rem;
    color: var(--text-secondary);
    line-height: 1.6;
}

/* Consultation & Inquiries */
.contact-section {
    padding: 6.5rem 0;
}

.consultation-form {
    max-width: 720px;
    margin: 3rem auto 0;
    padding: 3rem;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-card);
}

.form-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem;
}

.form-group {
    margin-bottom: 1.5rem;
}

.form-label {
    display: block;
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--primary-color);
    margin-bottom: 0.5rem;
}

.form-control {
    width: 100%;
    padding: 0.8rem 1rem;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    font-size: 0.95rem;
    background: var(--bg-main);
    color: var(--text-primary);
    transition: var(--transition);
}

.form-control:focus {
    outline: none;
    border-color: var(--border-focus);
    box-shadow: 0 0 0 2px rgba(85, 107, 47, 0.15);
}

.form-feedback {
    display: none;
    padding: 1.25rem;
    border-radius: var(--radius-sm);
    margin-top: 1.5rem;
    font-size: 0.95rem;
    line-height: 1.6;
}

.form-feedback.success {
    display: block;
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    color: #166534;
}

.form-feedback.error {
    display: block;
    background: #fef2f2;
    border: 1px solid #fecaca;
    color: #991b1b;
}

/* Accessible Project Modal */
.modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.7);
    backdrop-filter: blur(8px);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    padding: 1.5rem;
}

.modal-overlay.open {
    display: flex;
}

.modal-dialog {
    background: var(--bg-card);
    max-width: 760px;
    width: 100%;
    max-height: 90vh;
    overflow-y: auto;
    border-radius: var(--radius-lg);
    border: 1px solid var(--border-color);
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.3);
    position: relative;
}

.modal-close {
    position: absolute;
    top: 1.25rem;
    right: 1.25rem;
    background: var(--bg-main);
    border: 1px solid var(--border-color);
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 1.25rem;
    z-index: 10;
    color: var(--primary-color);
    transition: var(--transition);
}

.modal-close:hover {
    background: var(--primary-color);
    color: #fff;
}

.modal-body {
    padding: 2.5rem;
}

/* Footer */
.site-footer {
    padding: 4.5rem 0 2.5rem;
    background: var(--primary-color);
    color: #fbf9f5;
    border-top: 1px solid #2e3038;
}

.footer-grid {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr;
    gap: 3rem;
    margin-bottom: 3.5rem;
}

.footer-brand {
    font-family: var(--font-display);
    font-size: 1.5rem;
    font-weight: 700;
    margin-bottom: 1rem;
}

.footer-desc {
    color: #9ca3af;
    font-size: 0.92rem;
    max-width: 400px;
    line-height: 1.6;
}

.footer-heading {
    font-size: 0.9rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 1.25rem;
    color: #d1d5db;
}

.footer-links {
    list-style: none;
}

.footer-links li {
    margin-bottom: 0.65rem;
}

.footer-links a {
    color: #9ca3af;
    text-decoration: none;
    font-size: 0.9rem;
    transition: var(--transition);
}

.footer-links a:hover {
    color: #fff;
}

.footer-bottom {
    padding-top: 2rem;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    justify-content: space-between;
    font-size: 0.85rem;
    color: #9ca3af;
}

/* Mobile & Tablet Breakpoints */
@media (max-width: 1024px) {
    .portfolio-grid {
        grid-template-columns: repeat(2, 1fr);
    }
    .footer-grid {
        grid-template-columns: 1fr 1fr;
    }
}

@media (max-width: 768px) {
    .mobile-menu-btn {
        display: block;
    }
    .nav-links {
        display: none;
        flex-direction: column;
        position: absolute;
        top: 72px;
        left: 0;
        right: 0;
        background: var(--bg-card);
        padding: 1.5rem;
        border-bottom: 1px solid var(--border-color);
        box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
    }
    .nav-links.active {
        display: flex;
    }
    .portfolio-grid {
        grid-template-columns: 1fr;
    }
    .form-row {
        grid-template-columns: 1fr;
    }
    .consultation-form {
        padding: 1.75rem;
    }
    .footer-grid {
        grid-template-columns: 1fr;
    }
    .footer-bottom {
        flex-direction: column;
        gap: 0.75rem;
    }
}
"""
        css_path.write_text(css_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(css_path, ws, generator="foundation_scaffolder")

    # 3. index.html
    html_path = ws / "index.html"
    if not html_path.exists() or html_path.stat().st_size < 50:
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{desc_text}">
    <title>{title}</title>
    <link rel="stylesheet" href="style.css">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;600;700&family=Inter:wght@400;500;600;700&family=Playfair+Display:ital,wght@0,500;0,700;1,400&display=swap" rel="stylesheet">
</head>
<body>
    <!-- Studio Header & Navigation -->
    <header id="navbar" class="site-header">
        <div class="container navbar">
            <a href="#hero" class="nav-brand">{app_name}</a>
            <ul class="nav-links" id="nav-menu">
                <li><a href="#hero" class="nav-link">Studio</a></li>
                <li><a href="#philosophy" class="nav-link">Philosophy</a></li>
                <li><a href="#portfolio" class="nav-link">Portfolio</a></li>
                <li><a href="#services" class="nav-link">Services</a></li>
                <li><a href="#contact" class="nav-link">Consultation</a></li>
                <li><a href="#contact" class="btn-primary" style="padding: 0.5rem 1.25rem;">Book Inquiry</a></li>
            </ul>
            <button class="mobile-menu-btn" id="mobile-menu-btn" aria-label="Toggle navigation" aria-expanded="false">
                <span></span>
                <span></span>
                <span></span>
            </button>
        </div>
    </header>

    <main>
        <!-- Atmospheric Hero Section -->
        <section id="hero" class="hero" style="background-image: url('assets/images/hero/hero-general.jpg');">
            <div class="hero-overlay"></div>
            <div class="container hero-content">
                <span class="hero-tagline">Architectural Mastery & Sustainable Design</span>
                <h1 class="hero-title">Shaping Timeless Spaces with Monolithic Materiality</h1>
                <p class="hero-subhead">{desc_text}</p>
                <div class="hero-actions">
                    <a href="#contact" class="btn-primary">Request Consultation</a>
                    <a href="#portfolio" class="btn-outline">Explore Selected Works</a>
                </div>
            </div>
        </section>

        <!-- Sustainable Design Philosophy Section -->
        <section id="philosophy" class="about-section">
            <div class="container">
                <span class="section-tag">Design Principles</span>
                <h2 class="section-title">Rooted in Place, Crafted for Permanence</h2>
                <p class="section-lead">Our architectural studio operates at the intersection of monolithic structural clarity, natural daylight integration, and regenerative materials engineering.</p>
                <div class="pillars-grid">
                    <article class="pillar-card">
                        <div class="pillar-number">01</div>
                        <h3 class="pillar-title">Tactile Materiality</h3>
                        <p class="pillar-text">We prioritize honest materials—rammed earth, reclaimed limestone, patinated bronze, and charred timber—that age with dignity and minimize embodied carbon.</p>
                    </article>
                    <article class="pillar-card">
                        <div class="pillar-number">02</div>
                        <h3 class="pillar-title">Biophilic & Solar Harmony</h3>
                        <p class="pillar-text">Every building orientation is tuned to seasonal solar geometry and prevailing microclimates, maximizing passive heating, cooling, and natural illumination.</p>
                    </article>
                    <article class="pillar-card">
                        <div class="pillar-number">03</div>
                        <h3 class="pillar-title">Monolithic Spatial Balance</h3>
                        <p class="pillar-text">Eliminating superfluous decoration allows uncompromised spatial proportions, sculptural volumes, and serene transitions between interior sanctuary and nature.</p>
                    </article>
                </div>
            </div>
        </section>

        <!-- Curated Project Portfolio Section -->
        <section id="portfolio" class="portfolio-section">
            <div class="container">
                <span class="section-tag">Selected Works</span>
                <h2 class="section-title">Architectural Portfolio</h2>
                <p class="section-lead">A collection of bespoke residential sanctuaries, cultural pavilions, and spatial interior transformations.</p>

                <div class="filter-container">
                    <div class="search-box">
                        <input type="text" id="project-search" class="search-input" placeholder="Search projects by title, materials, or location..." aria-label="Search projects">
                    </div>
                    <div class="filter-buttons" id="category-filters">
                        <button class="filter-pill active" data-category="all">All Projects</button>
                        <button class="filter-pill" data-category="residential">Residential</button>
                        <button class="filter-pill" data-category="cultural">Cultural</button>
                        <button class="filter-pill" data-category="interior">Interior</button>
                        <button class="filter-pill" data-category="sustainable">Sustainable</button>
                    </div>
                </div>

                <div class="portfolio-grid" id="portfolio-grid">
                    <!-- Populated dynamically via app.js -->
                </div>
            </div>
        </section>

        <!-- Studio Disciplines & Services -->
        <section id="services" class="services-section">
            <div class="container">
                <span class="section-tag">Disciplines</span>
                <h2 class="section-title">Comprehensive Architectural Practice</h2>
                <p class="section-lead">From conceptual schematic modeling to full on-site construction oversight and interior curation.</p>
                <div class="services-grid">
                    <div class="service-card">
                        <h3 class="service-title">Architectural Design</h3>
                        <p class="service-desc">Complete architectural design from site zoning and feasibility analysis to technical detailing, structural engineering integration, and permitting.</p>
                    </div>
                    <div class="service-card">
                        <h3 class="service-title">Interior Architecture</h3>
                        <p class="service-desc">Sculptural spatial planning, custom millwork engineering, integrated lighting design, and tactile material curation for bespoke living environments.</p>
                    </div>
                    <div class="service-card">
                        <h3 class="service-title">Sustainable Masterplanning</h3>
                        <p class="service-desc">Passive House envelope engineering, net-zero carbon lifecycle assessment, rainwater harvesting systems, and microclimate landscape harmony.</p>
                    </div>
                </div>
            </div>
        </section>

        <!-- Consultation & Inquiries Section -->
        <section id="contact" class="contact-section">
            <div class="container">
                <div style="text-align: center; max-width: 720px; margin: 0 auto;">
                    <span class="section-tag">Begin a Collaboration</span>
                    <h2 class="section-title">Schedule a Consultation</h2>
                    <p class="section-lead" style="margin: 0 auto;">Whether planning a private residence, cultural institution, or spatial renovation, our partners are ready to explore your vision.</p>
                </div>

                <form id="consultation-form" class="consultation-form" novalidate>
                    <div class="form-row">
                        <div class="form-group">
                            <label for="contact-name" class="form-label">Full Name *</label>
                            <input type="text" id="contact-name" class="form-control" placeholder="e.g. Eleanor Vance" required>
                        </div>
                        <div class="form-group">
                            <label for="contact-email" class="form-label">Email Address *</label>
                            <input type="email" id="contact-email" class="form-control" placeholder="e.g. eleanor@studio.com" required>
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label for="contact-type" class="form-label">Project Typology *</label>
                            <select id="contact-type" class="form-control" required>
                                <option value="" disabled selected>Select project type</option>
                                <option value="Private Residential Sanctuary">Private Residential Sanctuary</option>
                                <option value="Cultural / Commercial Pavilion">Cultural / Commercial Pavilion</option>
                                <option value="Bespoke Interior Architecture">Bespoke Interior Architecture</option>
                                <option value="Sustainable Eco-Development">Sustainable Eco-Development</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="contact-date" class="form-label">Target Consultation Date *</label>
                            <input type="date" id="contact-date" class="form-control" required>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="contact-message" class="form-label">Project Vision & Site Details</label>
                        <textarea id="contact-message" class="form-control" rows="4" placeholder="Briefly describe your site location, timeline, and architectural ambitions..."></textarea>
                    </div>
                    <button type="submit" class="btn-primary" style="width: 100%; justify-content: center; padding: 1rem;">Submit Consultation Request</button>
                    <div id="form-feedback" class="form-feedback" role="alert"></div>
                </form>
            </div>
        </section>
    </main>

    <!-- Project Inspection Modal -->
    <div id="project-modal" class="modal-overlay" role="dialog" aria-modal="true" aria-hidden="true" aria-labelledby="modal-title">
        <div class="modal-dialog">
            <button id="modal-close" class="modal-close" aria-label="Close dialog">&times;</button>
            <div id="modal-body" class="modal-body">
                <!-- Populated dynamically via app.js -->
            </div>
        </div>
    </div>

    <!-- Studio Footer -->
    <footer id="footer" class="site-footer">
        <div class="container">
            <div class="footer-grid">
                <div>
                    <div class="footer-brand">{app_name}</div>
                    <p class="footer-desc">Independent architecture and interior design studio committed to monolithic form, tactile materiality, and sustainable spatial excellence.</p>
                </div>
                <div>
                    <div class="footer-heading">Navigation</div>
                    <ul class="footer-links">
                        <li><a href="#hero">Studio Overview</a></li>
                        <li><a href="#philosophy">Design Philosophy</a></li>
                        <li><a href="#portfolio">Architectural Works</a></li>
                        <li><a href="#services">Disciplines</a></li>
                        <li><a href="#contact">Consultation</a></li>
                    </ul>
                </div>
                <div>
                    <div class="footer-heading">Studio Locations</div>
                    <ul class="footer-links">
                        <li>Zurich — Limmatquai 18</li>
                        <li>London — 42 Redchurch St</li>
                        <li>New York — 114 Franklin St</li>
                        <li>inquiries@{slug}.com</li>
                    </ul>
                </div>
            </div>
            <div class="footer-bottom">
                <p>&copy; 2026 {app_name}. All rights reserved.</p>
                <p>Architectural Demonstration Platform</p>
            </div>
        </div>
    </footer>

    <script src="app.js"></script>
</body>
</html>"""
        html_path.write_text(html_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(html_path, ws, generator="foundation_scaffolder")

    # 4. app.js
    js_path = ws / "app.js"
    if not js_path.exists() or js_path.stat().st_size < 50:
        js_content = f"""/**
 * {app_name} — Architectural Studio Application Logic
 * Interactive Project Catalog, Category Filtering, Live Search, Modal Inspection, and Form Validation
 */

document.addEventListener('DOMContentLoaded', () => {{
    // 1. Authoritative Architectural Projects Dataset (6 Curated Works)
    const projects = [
        {{
            id: 'monolith-pavilion',
            title: 'The Monolith Pavilion',
            category: 'cultural',
            location: 'Zurich, Switzerland',
            year: 2024,
            image: 'assets/images/projects/pavilion.jpg',
            fallbackImage: 'assets/images/hero/hero-general.jpg',
            summary: 'Cultural gallery and civic amphitheater crafted from continuous monolithic rammed earth and structural bronze.',
            materials: 'Rammed earth, patinated bronze, acoustic timber slats',
            sustainability: '100% net-zero operational carbon, geothermal heating loop',
            area: '1,850 sq.m'
        }},
        {{
            id: 'highland-sanctuary',
            title: 'Highland Minimalist Sanctuary',
            category: 'residential',
            location: 'Cairngorms, Scotland',
            year: 2023,
            image: 'assets/images/projects/sanctuary.jpg',
            fallbackImage: 'assets/images/hero/hero-general.jpg',
            summary: 'Private cliffside residence featuring charred larch cladding, triple-glazed solar facade, and panoramic loch views.',
            materials: 'Charred Scots pine, local granite, triple-pane structural glass',
            sustainability: 'Passive House certified, off-grid micro-hydro generation',
            area: '420 sq.m'
        }},
        {{
            id: 'olive-grove-villa',
            title: 'Olive Grove Villa',
            category: 'sustainable',
            location: 'Tuscany, Italy',
            year: 2024,
            image: 'assets/images/projects/villa.jpg',
            fallbackImage: 'assets/images/hero/hero-general.jpg',
            summary: 'Restorative landscape estate integrating historic dry-stone terracing with low-slung earthen living volumes.',
            materials: 'Reclaimed Tuscan limestone, lime plaster, untreated olive wood',
            sustainability: 'Closed-loop rainwater cisterns, biophilic shading pergolas',
            area: '610 sq.m'
        }},
        {{
            id: 'obsidian-urban-loft',
            title: 'Obsidian Urban Loft',
            category: 'interior',
            location: 'Tribeca, New York',
            year: 2023,
            image: 'assets/images/projects/loft.jpg',
            fallbackImage: 'assets/images/hero/hero-general.jpg',
            summary: 'Spatial interior transformation sculpting a cast-iron warehouse into an interconnected sequence of light and shadow.',
            materials: 'Honed black basalt, blackened steel, acoustic Portuguese cork',
            sustainability: 'Zero-VOC architectural coatings, circadian daylight mimicry',
            area: '340 sq.m'
        }},
        {{
            id: 'kyoto-timber-gallery',
            title: 'Kyoto Timber Gallery',
            category: 'cultural',
            location: 'Arashiyama, Kyoto',
            year: 2024,
            image: 'assets/images/projects/gallery.jpg',
            fallbackImage: 'assets/images/hero/hero-general.jpg',
            summary: 'Contemporary tea pavilion and ceramic art gallery employing traditional Japanese interlocking joinery without metal fasteners.',
            materials: 'Ancient Hinoki cedar, handmade washi screens, basalt pavers',
            sustainability: 'Sustainably harvested FSC-certified timber, natural gravity ventilation',
            area: '280 sq.m'
        }},
        {{
            id: 'dune-eco-residence',
            title: 'Dune Eco-Residence',
            category: 'residential',
            location: 'Skeleton Coast, Namibia',
            year: 2025,
            image: 'assets/images/projects/eco-residence.jpg',
            fallbackImage: 'assets/images/hero/hero-general.jpg',
            summary: 'Self-cooling desert sanctuary shaped by aerodynamic dune aerodynamics to deflect coastal winds and capture maritime fog.',
            materials: 'Compressed desert sand blocks, cast bronze anchors, tensioned sailcloth',
            sustainability: 'Atmospheric fog moisture harvesting, 100% solar PV storage',
            area: '510 sq.m'
        }}
    ];

    // State
    let activeFilter = 'all';
    let searchQuery = '';

    // DOM Elements
    const grid = document.getElementById('portfolio-grid');
    const searchInput = document.getElementById('project-search');
    const filterButtons = document.querySelectorAll('.filter-pill');
    const modal = document.getElementById('project-modal');
    const modalClose = document.getElementById('modal-close');
    const modalBody = document.getElementById('modal-body');
    const form = document.getElementById('consultation-form');
    const feedback = document.getElementById('form-feedback');
    const mobileMenuBtn = document.getElementById('mobile-menu-btn');
    const navMenu = document.getElementById('nav-menu');

    // 2. Render Projects Grid
    function renderProjects() {{
        if (!grid) return;
        const filtered = projects.filter(p => {{
            const matchesCat = activeFilter === 'all' || p.category === activeFilter;
            const q = searchQuery.toLowerCase();
            const matchesQuery = !q ||
                p.title.toLowerCase().includes(q) ||
                p.materials.toLowerCase().includes(q) ||
                p.location.toLowerCase().includes(q) ||
                p.summary.toLowerCase().includes(q);
            return matchesCat && matchesQuery;
        }});

        if (filtered.length === 0) {{
            grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 4rem 1rem; color: var(--text-secondary);">No architectural projects match your search criteria.</div>';
            return;
        }}

        grid.innerHTML = filtered.map(p => `
            <article class="project-card" data-category="${{p.category}}" data-project-id="${{p.id}}">
                <div class="project-image-wrap">
                    <img src="${{p.image}}" alt="${{p.title}} — ${{p.location}}" class="project-img" loading="eager" onerror="this.onerror=null; this.src='${{p.fallbackImage}}';">
                    <span class="project-badge">${{p.category}}</span>
                </div>
                <div class="project-body">
                    <div class="project-meta">${{p.location}} &bull; ${{p.year}}</div>
                    <h3 class="project-title">${{p.title}}</h3>
                    <p class="project-desc">${{p.summary}}</p>
                    <button class="btn-project-details" data-id="${{p.id}}" aria-label="Inspect details for ${{p.title}}">Inspect Project Specifications &rarr;</button>
                </div>
            </article>
        `).join('');

        // Attach modal triggers
        grid.querySelectorAll('.btn-project-details').forEach(btn => {{
            btn.addEventListener('click', () => {{
                const id = btn.getAttribute('data-id');
                openProjectModal(id);
            }});
        }});
    }}

    // 3. Category Filter
    filterButtons.forEach(btn => {{
        btn.addEventListener('click', () => {{
            filterButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeFilter = btn.getAttribute('data-category') || 'all';
            renderProjects();
        }});
    }});

    // 4. Live Search
    if (searchInput) {{
        searchInput.addEventListener('input', (e) => {{
            searchQuery = e.target.value.trim();
            renderProjects();
        }});
    }}

    // 5. Project Inspection Modal
    function openProjectModal(id) {{
        const p = projects.find(item => item.id === id);
        if (!p || !modal || !modalBody) return;

        modalBody.innerHTML = `
            <div style="margin-bottom: 1.5rem;">
                <span class="project-badge" style="position: static; display: inline-block; margin-bottom: 0.75rem;">${{p.category}}</span>
                <h2 id="modal-title" style="font-family: var(--font-display); font-size: 2rem; color: var(--primary-color); margin-bottom: 0.5rem;">${{p.title}}</h2>
                <p style="color: var(--secondary-color); font-weight: 600; text-transform: uppercase; font-size: 0.85rem; letter-spacing: 0.05em;">${{p.location}} &bull; Completed ${{p.year}}</p>
            </div>
            <div style="aspect-ratio: 16/9; overflow: hidden; border-radius: var(--radius-sm); margin-bottom: 1.5rem; background: #242526;">
                <img src="${{p.image}}" alt="${{p.title}}" style="width: 100%; height: 100%; object-fit: cover;" onerror="this.onerror=null; this.src='${{p.fallbackImage}}';">
            </div>
            <p style="font-size: 1.05rem; line-height: 1.7; color: var(--text-primary); margin-bottom: 1.75rem;">${{p.summary}}</p>
            <div style="background: var(--bg-main); border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: 1.5rem; display: grid; gap: 1rem;">
                <div><strong>Gross Built Area:</strong> ${{p.area}}</div>
                <div><strong>Primary Materiality:</strong> ${{p.materials}}</div>
                <div><strong>Sustainability Metric:</strong> ${{p.sustainability}}</div>
            </div>
            <div style="margin-top: 2rem; text-align: right;">
                <a href="#contact" class="btn-primary" onclick="document.getElementById('project-modal').classList.remove('open'); document.getElementById('project-modal').setAttribute('aria-hidden', 'true');">Discuss Similar Project</a>
            </div>
        `;

        modal.classList.add('open');
        modal.setAttribute('aria-hidden', 'false');
        if (modalClose) modalClose.focus();
    }}

    function closeProjectModal() {{
        if (!modal) return;
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden', 'true');
    }}

    if (modalClose) {{
        modalClose.addEventListener('click', closeProjectModal);
    }}

    if (modal) {{
        modal.addEventListener('click', (e) => {{
            if (e.target === modal) closeProjectModal();
        }});
    }}

    document.addEventListener('keydown', (e) => {{
        if (e.key === 'Escape' && modal && modal.classList.contains('open')) {{
            closeProjectModal();
        }}
    }});

    // 6. Consultation Booking Form Submission
    if (form && feedback) {{
        form.addEventListener('submit', (e) => {{
            e.preventDefault();
            const nameInput = document.getElementById('contact-name');
            const emailInput = document.getElementById('contact-email');
            const typeInput = document.getElementById('contact-type');
            const dateInput = document.getElementById('contact-date');

            const name = nameInput ? nameInput.value.trim() : '';
            const email = emailInput ? emailInput.value.trim() : '';
            const type = typeInput ? typeInput.value : '';
            const date = dateInput ? dateInput.value : '';

            if (!name || !email || !type || !date) {{
                feedback.className = 'form-feedback error';
                feedback.textContent = 'Please fill out all required fields marked with an asterisk (*).';
                return;
            }}

            // Validated demonstration feedback
            feedback.className = 'form-feedback success';
            feedback.textContent = `Thank you, ${{name}}. Your consultation inquiry for "${{type}}" on ${{date}} has been validated in demonstration mode. No actual appointment has been scheduled.`;
            form.reset();
        }});
    }}

    // 7. Mobile Navigation Toggle
    if (mobileMenuBtn && navMenu) {{
        mobileMenuBtn.addEventListener('click', () => {{
            const expanded = mobileMenuBtn.getAttribute('aria-expanded') === 'true';
            mobileMenuBtn.setAttribute('aria-expanded', !expanded);
            navMenu.classList.toggle('active');
        }});

        navMenu.querySelectorAll('.nav-link').forEach(link => {{
            link.addEventListener('click', () => {{
                mobileMenuBtn.setAttribute('aria-expanded', 'false');
                navMenu.classList.remove('active');
            }});
        }});
    }}

    // Initial Render
    renderProjects();
}});
"""
        js_path.write_text(js_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(js_path, ws, generator="foundation_scaffolder")

    return True


def _seed_veterinary_foundation(
    ws: Path,
    prompt: str,
    contract: Optional[Any],
    design_brief: Optional[Any],
) -> bool:
    from tools.security import WorkspaceOwnershipManifest
    from core.design_intelligence import detect_brand_name

    brand = detect_brand_name(prompt)
    app_name = brand if brand != "Application" else "Paws & Claws Veterinary Clinic"
    slug = app_name.lower().replace(" ", "-").replace("&", "and")
    title = f"{app_name} — Comprehensive Pet Care & Wellness Hospital"
    desc_text = f"{app_name} provides compassionate, state-of-the-art veterinary medicine, surgical expertise, preventive wellness, and emergency urgent care for companion animals."

    # 1. package.json
    pkg_path = ws / "package.json"
    if not pkg_path.exists():
        pkg_data = {
            "name": slug,
            "version": "1.0.0",
            "description": f"{title} Web Portal",
            "main": "app.js",
            "scripts": {
                "start": "npx http-server -p 8080",
                "serve": "npx http-server -p 8080"
            }
        }
        pkg_path.write_text(json.dumps(pkg_data, indent=2), encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(pkg_path, ws, generator="foundation_scaffolder")

    # 2. style.css
    css_path = ws / "style.css"
    if not css_path.exists() or css_path.stat().st_size < 50:
        css_content = """/* Veterinary Healthcare Design System */
:root {
    --primary-color: #0f766e;
    --primary-hover: #115e59;
    --secondary-color: #14b8a6;
    --accent-color: #d97706;
    --bg-main: #f0fdfa;
    --bg-card: #ffffff;
    --text-primary: #134e4a;
    --text-secondary: #475569;
    --border-color: #ccfbf1;
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 16px;
    --shadow-card: 0 4px 15px rgba(15, 118, 110, 0.08);
    --font-sans: 'Plus Jakarta Sans', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: var(--font-sans); background: var(--bg-main); color: var(--text-primary); line-height: 1.6; overflow-x: hidden; }
.container { max-width: 1240px; margin: 0 auto; padding: 0 1.5rem; }
.card { background-color: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md); overflow: hidden; }
.grid { display: grid; gap: 2rem; }
.site-header { position: sticky; top: 0; z-index: 100; background: rgba(255, 255, 255, 0.95); backdrop-filter: blur(8px); border-bottom: 1px solid var(--border-color); }
.navbar { display: flex; align-items: center; justify-content: space-between; height: 72px; }
.nav-brand { font-size: 1.35rem; font-weight: 700; color: var(--primary-color); text-decoration: none; }
.nav-links { display: flex; gap: 1.75rem; list-style: none; align-items: center; }
.nav-link { color: var(--text-secondary); text-decoration: none; font-weight: 500; font-size: 0.95rem; }
.mobile-menu-btn { display: none; background: none; border: none; cursor: pointer; padding: 8px; }
.hero { min-height: 80vh; display: flex; align-items: center; background: linear-gradient(135deg, rgba(15, 118, 110, 0.92) 0%, rgba(19, 78, 74, 0.95) 100%), url('assets/images/hero/hero-general.jpg') center/cover no-repeat; color: #fff; padding: 6rem 0; position: relative; }
.hero-content { position: relative; z-index: 2; max-width: 760px; }
.hero-title { font-size: clamp(2.2rem, 5vw, 3.8rem); line-height: 1.15; margin-bottom: 1.25rem; font-weight: 800; }
.hero-subhead { font-size: 1.2rem; color: #ccfbf1; margin-bottom: 2rem; }
.btn-primary { display: inline-flex; align-items: center; padding: 0.85rem 1.75rem; background: var(--accent-color); color: #fff; font-weight: 700; border-radius: var(--radius-sm); border: none; cursor: pointer; text-decoration: none; }
.btn-primary:hover { background: #b45309; }
.services-section { padding: 5rem 0; }
.filter-container { display: flex; flex-wrap: wrap; gap: 1.5rem; margin: 2rem 0; align-items: center; }
.search-input { flex: 1; min-width: 260px; padding: 0.75rem 1rem; border: 1px solid var(--border-color); border-radius: var(--radius-sm); }
.filter-pill { padding: 0.5rem 1.25rem; border: 1px solid var(--border-color); background: #fff; border-radius: 9999px; cursor: pointer; font-size: 0.88rem; }
.filter-pill.active { background: var(--primary-color); color: #fff; border-color: var(--primary-color); }
.services-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 2rem; }
.service-card { background: #fff; border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 1.5rem; box-shadow: var(--shadow-card); display: flex; flex-direction: column; }
.service-img-wrap { aspect-ratio: 16/10; overflow: hidden; border-radius: var(--radius-sm); margin-bottom: 1.25rem; background: #e2e8f0; }
.service-img { width: 100%; height: 100%; object-fit: cover; }
.contact-section { padding: 5rem 0; background: #fff; border-top: 1px solid var(--border-color); }
.appointment-form { max-width: 640px; margin: 2rem auto 0; padding: 2.5rem; background: var(--bg-main); border: 1px solid var(--border-color); border-radius: var(--radius-md); }
.form-group { margin-bottom: 1.25rem; }
.form-label { display: block; font-weight: 600; margin-bottom: 0.5rem; font-size: 0.9rem; }
.form-control { width: 100%; padding: 0.75rem 1rem; border: 1px solid var(--border-color); border-radius: var(--radius-sm); background: #fff; }
.form-feedback { display: none; padding: 1rem; border-radius: var(--radius-sm); margin-top: 1rem; }
.form-feedback.success { display: block; background: #dcfce7; color: #15803d; border: 1px solid #86efac; }
.form-feedback.error { display: block; background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: none; align-items: center; justify-content: center; z-index: 1000; padding: 1rem; }
.modal-overlay.open { display: flex; }
.modal-dialog { background: #fff; max-width: 620px; width: 100%; padding: 2rem; border-radius: var(--radius-md); position: relative; }
.modal-close { position: absolute; top: 1rem; right: 1rem; background: none; border: none; font-size: 1.5rem; cursor: pointer; color: var(--text-secondary); }
.site-footer { padding: 4rem 0 2rem; background: #134e4a; color: #ccfbf1; }
@media (max-width: 768px) { .mobile-menu-btn { display: block; } .nav-links { display: none; } .services-grid { grid-template-columns: 1fr; } }
"""
        css_path.write_text(css_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(css_path, ws, generator="foundation_scaffolder")

    # 3. index.html
    html_path = ws / "index.html"
    if not html_path.exists() or html_path.stat().st_size < 50:
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header id="navbar" class="site-header">
        <div class="container navbar">
            <a href="#hero" class="nav-brand">{app_name}</a>
            <ul class="nav-links" id="nav-menu">
                <li><a href="#hero" class="nav-link">Home</a></li>
                <li><a href="#about" class="nav-link">About</a></li>
                <li><a href="#services" class="nav-link">Care Services</a></li>
                <li><a href="#contact" class="nav-link">Appointments</a></li>
            </ul>
            <button class="mobile-menu-btn" id="mobile-menu-btn" aria-label="Toggle navigation"><span></span><span></span><span></span></button>
        </div>
    </header>
    <main>
        <section id="hero" class="hero">
            <div class="container hero-content">
                <h1 class="hero-title">Compassionate Healthcare for Your Beloved Pets</h1>
                <p class="hero-subhead">{desc_text}</p>
                <a href="#contact" class="btn-primary">Book an Appointment</a>
            </div>
        </section>
        <section id="about" class="container" style="padding: 4rem 1.5rem;">
            <h2>Expert Veterinary Medicine You Can Trust</h2>
            <p>Our dedicated veterinary hospital combines cutting-edge diagnostics with compassionate bedside care to ensure your companion animal lives a long, healthy life.</p>
        </section>
        <section id="services" class="container services-section">
            <h2>Clinical Specialties & Care Services</h2>
            <div class="filter-container">
                <input type="text" id="service-search" class="search-input" placeholder="Search veterinary services...">
                <div class="filter-buttons" id="category-filters">
                    <button class="filter-pill active" data-category="all">All Specialties</button>
                    <button class="filter-pill" data-category="preventive">Preventive</button>
                    <button class="filter-pill" data-category="surgery">Surgery</button>
                    <button class="filter-pill" data-category="diagnostics">Diagnostics</button>
                    <button class="filter-pill" data-category="urgent">Urgent Care</button>
                </div>
            </div>
            <div id="services-grid" class="services-grid"></div>
        </section>
        <section id="contact" class="contact-section">
            <div class="container">
                <h2 style="text-align: center;">Schedule a Pet Wellness Visit</h2>
                <form id="appointment-form" class="appointment-form" novalidate>
                    <div class="form-group"><label class="form-label" for="pet-name">Pet Name *</label><input type="text" id="pet-name" class="form-control" required placeholder="e.g. Barnaby"></div>
                    <div class="form-group"><label class="form-label" for="owner-email">Owner Email *</label><input type="email" id="owner-email" class="form-control" required placeholder="e.g. owner@example.com"></div>
                    <div class="form-group"><label class="form-label" for="service-type">Service Type *</label>
                        <select id="service-type" class="form-control" required>
                            <option value="" disabled selected>Select a clinical service</option>
                            <option value="Wellness Exam">Wellness Exam</option>
                            <option value="Advanced Surgery">Advanced Surgery</option>
                            <option value="Dental Healthcare">Dental Healthcare</option>
                            <option value="Digital Diagnostics">Digital Diagnostics</option>
                            <option value="Urgent Medical Care">Urgent Medical Care</option>
                            <option value="Physical Rehabilitation">Physical Rehabilitation</option>
                        </select>
                    </div>
                    <div class="form-group"><label class="form-label" for="appointment-date">Target Date *</label><input type="date" id="appointment-date" class="form-control" required></div>
                    <button type="submit" class="btn-primary" style="width: 100%; justify-content: center;">Submit Appointment Request</button>
                    <div id="form-feedback" class="form-feedback" role="alert"></div>
                </form>
            </div>
        </section>
    </main>
    <div id="care-modal" class="modal-overlay" role="dialog" aria-modal="true" aria-hidden="true">
        <div class="modal-dialog">
            <button id="modal-close" class="modal-close" aria-label="Close modal">&times;</button>
            <div id="modal-body"></div>
        </div>
    </div>
    <footer id="footer" class="site-footer">
        <div class="container"><p>&copy; 2026 {app_name}. Demonstration Mode.</p></div>
    </footer>
    <script src="app.js"></script>
</body>
</html>"""
        html_path.write_text(html_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(html_path, ws, generator="foundation_scaffolder")

    # 4. app.js
    js_path = ws / "app.js"
    if not js_path.exists() or js_path.stat().st_size < 50:
        js_content = f"""/**
 * {app_name} — Veterinary Clinic Application Logic
 */
document.addEventListener('DOMContentLoaded', () => {{
    const services = [
        {{
            id: 'wellness',
            title: 'Comprehensive Wellness Exams',
            category: 'preventive',
            image: 'assets/images/services/wellness.jpg',
            fallbackImage: 'assets/images/hero/hero-general.jpg',
            desc: 'Thorough head-to-tail physical examinations, customized vaccine schedules, and wellness blood panels.'
        }},
        {{
            id: 'surgery',
            title: 'Advanced Soft Tissue Surgery',
            category: 'surgery',
            image: 'assets/images/services/surgery.jpg',
            fallbackImage: 'assets/images/hero/hero-general.jpg',
            desc: 'State-of-the-art surgical suite with continuous multiparameter anesthetic monitoring and postoperative pain relief.'
        }},
        {{
            id: 'dental',
            title: 'Veterinary Dental Healthcare',
            category: 'preventive',
            image: 'assets/images/services/dental.jpg',
            fallbackImage: 'assets/images/hero/hero-general.jpg',
            desc: 'Ultrasonic scaling, dental digital radiography, subgingival polishing, and surgical extractions.'
        }},
        {{
            id: 'diagnostics',
            title: 'Digital Imaging & Ultrasound',
            category: 'diagnostics',
            image: 'assets/images/services/diagnostics.jpg',
            fallbackImage: 'assets/images/hero/hero-general.jpg',
            desc: 'High-resolution digital radiology, abdominal ultrasonography, and rapid in-house clinical pathology.'
        }},
        {{
            id: 'urgent',
            title: 'Emergency & Urgent Medical Care',
            category: 'urgent',
            image: 'assets/images/services/urgent.jpg',
            fallbackImage: 'assets/images/hero/hero-general.jpg',
            desc: 'Rapid triage, supplemental oxygen therapy, trauma stabilization, and intensive critical care.'
        }},
        {{
            id: 'rehab',
            title: 'Integrative Physical Rehabilitation',
            category: 'preventive',
            image: 'assets/images/services/rehab.jpg',
            fallbackImage: 'assets/images/hero/hero-general.jpg',
            desc: 'Companion therapeutic laser treatments, targeted hydrotherapy, and custom mobility restoration plans.'
        }}
    ];

    const grid = document.getElementById('services-grid');
    const search = document.getElementById('service-search');
    const filterBtns = document.querySelectorAll('.filter-pill');
    const modal = document.getElementById('care-modal');
    const modalClose = document.getElementById('modal-close');
    const modalBody = document.getElementById('modal-body');
    const form = document.getElementById('appointment-form');
    const feedback = document.getElementById('form-feedback');

    let activeCat = 'all';
    let q = '';

    function render() {{
        if (!grid) return;
        const filtered = services.filter(s => {{
            const mCat = activeCat === 'all' || s.category === activeCat;
            const mQ = !q || s.title.toLowerCase().includes(q) || s.desc.toLowerCase().includes(q);
            return mCat && mQ;
        }});
        grid.innerHTML = filtered.map(s => `
            <div class="service-card" data-category="${{s.category}}" data-service-id="${{s.id}}">
                <div class="service-img-wrap">
                    <img src="${{s.image}}" alt="${{s.title}}" class="service-img" loading="eager" onerror="this.onerror=null; this.src='${{s.fallbackImage}}';">
                </div>
                <h3 style="font-size: 1.25rem; margin-bottom: 0.5rem; color: var(--primary-color);">${{s.title}}</h3>
                <p style="margin: 0.5rem 0 1.25rem; color: var(--text-secondary); flex-grow: 1;">${{s.desc}}</p>
                <button class="btn-primary btn-service-details" data-id="${{s.id}}" style="padding: 0.5rem 1rem; font-size: 0.85rem; align-self: flex-start;">View Details</button>
            </div>
        `).join('');

        grid.querySelectorAll('.btn-service-details').forEach(btn => {{
            btn.addEventListener('click', () => {{
                const item = services.find(s => s.id === btn.dataset.id);
                if (item && modal && modalBody) {{
                    modalBody.innerHTML = `
                        <div style="aspect-ratio: 16/10; overflow: hidden; border-radius: var(--radius-sm); margin-bottom: 1.25rem;">
                            <img src="${{item.image}}" alt="${{item.title}}" style="width: 100%; height: 100%; object-fit: cover;" onerror="this.onerror=null; this.src='${{item.fallbackImage}}';">
                        </div>
                        <h2 id="modal-service-title" style="color: var(--primary-color); margin-bottom: 0.75rem;">${{item.title}}</h2>
                        <p style="margin: 1rem 0; color: var(--text-secondary);">${{item.desc}}</p>
                        <p><strong>Clinical Category:</strong> ${{item.category}}</p>
                    `;
                    modal.classList.add('open');
                    modal.setAttribute('aria-hidden', 'false');
                    if (modalClose) modalClose.focus();
                }}
            }});
        }});
    }}

    filterBtns.forEach(b => {{
        b.addEventListener('click', () => {{
            filterBtns.forEach(x => x.classList.remove('active'));
            b.classList.add('active');
            activeCat = b.dataset.category || 'all';
            render();
        }});
    }});

    if (search) {{
        search.addEventListener('input', (e) => {{
            q = e.target.value.toLowerCase().trim();
            render();
        }});
    }}

    function closeModal() {{
        if (!modal) return;
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden', 'true');
    }}

    if (modalClose) modalClose.addEventListener('click', closeModal);
    if (modal) modal.addEventListener('click', (e) => {{ if (e.target === modal) closeModal(); }});
    document.addEventListener('keydown', (e) => {{ if (e.key === 'Escape' && modal && modal.classList.contains('open')) closeModal(); }});

    if (form && feedback) {{
        form.addEventListener('submit', (e) => {{
            e.preventDefault();
            const petInput = document.getElementById('pet-name');
            const emailInput = document.getElementById('owner-email');
            const serviceInput = document.getElementById('service-type');
            const dateInput = document.getElementById('appointment-date');

            const pet = petInput ? petInput.value.trim() : '';
            const email = emailInput ? emailInput.value.trim() : '';
            const service = serviceInput ? serviceInput.value : '';
            const dt = dateInput ? dateInput.value : '';

            if (!pet || !email || !service || !dt) {{
                feedback.className = 'form-feedback error';
                feedback.textContent = 'Please fill out all required fields marked with an asterisk (*).';
                return;
            }}

            feedback.className = 'form-feedback success';
            feedback.textContent = `Thank you! Appointment request for ${{pet}} (${{service}}) on ${{dt}} has been validated in demonstration mode. No actual booking was made.`;
            form.reset();
        }});
    }}

    render();
}});
"""
        js_path.write_text(js_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_file(js_path, ws, generator="foundation_scaffolder")

    return True


def _seed_universal_foundation(
    ws: Path,
    prompt: str,
    contract: Optional[Any],
    design_brief: Optional[Any],
) -> bool:
    from core.mission_spec import MissionSpecification
    from core.universal_renderer import UniversalContentRenderer

    # Check if a persisted mission spec already exists in workspace
    spec = MissionSpecification.load_from_workspace(ws)
    if not spec:
        spec = MissionSpecification.from_prompt(prompt, ws, design_brief=design_brief)
        spec.persist(ws)

    return UniversalContentRenderer.render(ws, spec)


def _seed_wanderworld_foundation(
    ws: Path,
    prompt: str,
    contract: Optional[Any],
    design_brief: Optional[Any],
) -> bool:
    app_name = "WanderWorld"
    title = "WanderWorld — Premium Travel Agency"

    # package.json
    pkg_path = ws / "package.json"
    if not pkg_path.exists():
        pkg_data = {
            "name": "wanderworld",
            "version": "1.0.0",
            "description": "WanderWorld Travel Agency",
            "main": "app.js",
            "scripts": {
                "start": "npx http-server -p 8080",
                "serve": "npx http-server -p 8080"
            }
        }
        pkg_path.write_text(json.dumps(pkg_data, indent=2), encoding="utf-8")

    # style.css (WanderWorld Design System)
    css_path = ws / "style.css"
    if not css_path.exists() or css_path.stat().st_size < 50:
        css_content = """/* WanderWorld Design System */
:root {
    --primary-color: #0b1d33;
    --primary-light: #163256;
    --ocean-teal: #0d7a82;
    --teal-light: #e0f2f1;
    --gold-accent: #d4af37;
    --gold-hover: #b89628;
    --bg-main: #f8fafc;
    --card-bg: #ffffff;
    --text-primary: #0f172a;
    --text-secondary: #475569;
    --border-color: #e2e8f0;
    --radius-sm: 6px;
    --radius-md: 12px;
    --radius-lg: 18px;
    --shadow-sm: 0 2px 4px rgba(0, 0, 0, 0.05);
    --shadow-md: 0 4px 12px rgba(11, 29, 51, 0.08);
    --shadow-lg: 0 10px 25px rgba(11, 29, 51, 0.12);
    --font-heading: 'Plus Jakarta Sans', system-ui, sans-serif;
    --font-body: 'Inter', system-ui, sans-serif;
    --transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; font-size: 16px; }
body { font-family: var(--font-body); background-color: var(--bg-main); color: var(--text-primary); line-height: 1.6; overflow-x: hidden; }
img { max-width: 100%; height: auto; display: block; }
a { color: inherit; text-decoration: none; }
button { font-family: inherit; cursor: pointer; border: none; background: none; }
.container { width: 100%; max-width: 1280px; margin: 0 auto; padding: 0 1.5rem; }
.section-header { text-align: center; max-width: 680px; margin: 0 auto 3rem auto; }
.site-header { position: sticky; top: 0; z-index: 1000; background: rgba(255, 255, 255, 0.95); backdrop-filter: blur(10px); border-bottom: 1px solid var(--border-color); }
.navbar { display: flex; justify-content: space-between; align-items: center; height: 72px; }
.brand-logo { font-family: var(--font-heading); font-size: 1.5rem; font-weight: 800; color: var(--primary-color); }
.nav-menu { display: flex; align-items: center; gap: 2rem; list-style: none; }
.hero { position: relative; min-height: 85vh; display: flex; align-items: center; background: var(--primary-color) url('assets/images/hero/hero-wanderlust.jpg') center/cover; color: #fff; padding: 5rem 0; }
.hero-overlay { position: absolute; inset: 0; background: linear-gradient(135deg, rgba(11, 29, 51, 0.85) 0%, rgba(13, 122, 130, 0.65) 100%); z-index: 1; }
.hero-content { position: relative; z-index: 2; max-width: 760px; }
.hero-title { font-family: var(--font-heading); font-size: 3.5rem; font-weight: 800; margin-bottom: 1.25rem; }
.cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 2rem; }
.destination-card, .package-card { background: var(--card-bg); border-radius: var(--radius-md); overflow: hidden; box-shadow: var(--shadow-md); border: 1px solid var(--border-color); }
.site-footer { background: var(--primary-color); color: #fff; padding: 4rem 0 2rem 0; }
@media (max-width: 768px) { .nav-menu { display: none; } }
"""
        css_path.write_text(css_content, encoding="utf-8")

    # index.html
    html_path = ws / "index.html"
    if not html_path.exists() or html_path.stat().st_size < 50:
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="site-header"><div class="container navbar"><a href="#" class="brand-logo">WanderWorld</a><ul class="nav-menu"><li><a href="#destinations">Destinations</a></li><li><a href="#packages">Packages</a></li></ul></div></header>
    <main id="app">
        <section class="hero" id="home"><div class="hero-overlay"></div><div class="container"><div class="hero-content"><h1 class="hero-title">Discover Your Next Adventure</h1></div></div></section>
        <section class="container" id="destinations"><div class="cards-grid" id="destinations-grid"></div></section>
        <section class="container" id="packages"><div class="cards-grid" id="packages-grid"></div></section>
    </main>
    <footer class="site-footer"><div class="container"><p>&copy; 2026 WanderWorld.</p></div></footer>
    <script src="app.js"></script>
</body>
</html>"""
        html_path.write_text(html_content, encoding="utf-8")

    js_path = ws / "app.js"
    if not js_path.exists() or js_path.stat().st_size < 10:
        js_path.write_text("console.log('WanderWorld ready');", encoding="utf-8")

    return True


# ==============================================================================
# 00. NOVA — CONSUMER ELECTRONICS E-COMMERCE FOUNDATION
# ==============================================================================

def _seed_ecommerce_foundation(
    ws: Path,
    prompt: str,
    contract: Optional[Any],
    design_brief: Optional[Any],
) -> bool:
    """
    Deterministic foundation scaffolder for NOVA and consumer electronics e-commerce missions.
    Seeds index.html, style.css, app.js, and package.json with full e-commerce functionality:
    - 12 electronics products across 6 categories (Smartphones, Laptops, Headphones, Smartwatches, Gaming, Accessories)
    - Real-time search, category filtering, and price sorting
    - Product detail inspection modal
    - Interactive shopping cart with quantity adjustment, live subtotal, and localStorage persistence
    - Demonstration-only checkout and contact form with explicit disclaimers
    """
    from tools.security import WorkspaceOwnershipManifest

    app_name = "NOVA"
    title = "NOVA — Premium Consumer Electronics"
    desc_text = "Discover cutting-edge personal computing, mobile, audio, and gaming technology from NOVA."

    # 1. package.json
    pkg_path = ws / "package.json"
    if not pkg_path.exists():
        pkg_data = {
            "name": "nova-consumer-electronics",
            "version": "1.0.0",
            "description": f"{title} E-Commerce Web Portal",
            "main": "app.js",
            "scripts": {
                "start": "npx http-server -p 8080",
                "serve": "npx http-server -p 8080"
            }
        }
        pkg_path.write_text(json.dumps(pkg_data, indent=2), encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_files(ws, ["package.json"], source="foundation_scaffolder")

    # 2. style.css
    css_path = ws / "style.css"
    if not css_path.exists() or css_path.stat().st_size < 50:
        css_content = """/* ==========================================================================
   NOVA — Consumer Electronics Design System
   Color Palette: Deep Charcoal Obsidian, Electric Blue, Clean White, Silver
   ========================================================================== */

:root {
    --bg-dark: #0b0f17;
    --bg-card: #131b2e;
    --bg-surface: #1e293b;
    --primary-color: #0284c7;
    --primary-light: #38bdf8;
    --secondary-color: #0f172a;
    --accent-blue: #0ea5e9;
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --border-color: #334155;
    --border-subtle: #1e293b;
    --success-color: #10b981;
    --color-error: #ef4444;
    --radius-sm: 4px;
    --radius-md: 8px;
    --radius-lg: 12px;
    --radius-full: 9999px;
    --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.3);
    --shadow-md: 0 4px 20px -2px rgba(0, 0, 0, 0.4);
    --shadow-lg: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
    --transition-fast: 0.2s ease-in-out;
}

*, *::before, *::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

html {
    scroll-behavior: smooth;
    font-size: 16px;
}

body {
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background-color: var(--bg-dark);
    color: var(--text-primary);
    line-height: 1.6;
    overflow-x: hidden;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 1.5rem;
}

/* Header & Navigation */
.site-header {
    position: sticky;
    top: 0;
    z-index: 100;
    background: rgba(11, 15, 23, 0.92);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border-color);
}

.navbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 72px;
}

.brand-logo {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    text-decoration: none;
    color: var(--text-primary);
    font-size: 1.5rem;
    font-weight: 800;
    letter-spacing: 0.1em;
}

.brand-dot {
    color: var(--accent-blue);
}

.nav-links {
    display: flex;
    align-items: center;
    gap: 2rem;
    list-style: none;
}

.nav-links a {
    text-decoration: none;
    color: var(--text-secondary);
    font-weight: 500;
    font-size: 0.95rem;
    transition: color var(--transition-fast);
}

.nav-links a:hover,
.nav-links a.active {
    color: var(--accent-blue);
}

.nav-actions {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.cart-btn {
    position: relative;
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    padding: 0.6rem 1rem;
    border-radius: var(--radius-md);
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.95rem;
    font-weight: 600;
    transition: all var(--transition-fast);
}

.cart-btn:hover {
    border-color: var(--accent-blue);
    background: rgba(14, 165, 233, 0.1);
}

.cart-badge {
    background: var(--accent-blue);
    color: #ffffff;
    font-size: 0.75rem;
    font-weight: 700;
    padding: 0.15rem 0.5rem;
    border-radius: var(--radius-full);
}

.mobile-menu-btn {
    display: none;
    background: transparent;
    border: none;
    cursor: pointer;
    flex-direction: column;
    gap: 5px;
    padding: 0.5rem;
}

.mobile-menu-btn span {
    width: 24px;
    height: 2px;
    background: var(--text-primary);
    transition: var(--transition-fast);
}

/* Hero Section */
.hero {
    position: relative;
    min-height: 75vh;
    display: flex;
    align-items: center;
    padding: 5rem 0;
    background: radial-gradient(circle at 80% 20%, rgba(14, 165, 233, 0.15) 0%, transparent 60%),
                radial-gradient(circle at 20% 80%, rgba(2, 132, 199, 0.1) 0%, transparent 50%),
                var(--bg-dark);
    border-bottom: 1px solid var(--border-color);
}

.hero-grid {
    display: grid;
    grid-template-columns: 1.2fr 0.8fr;
    gap: 3rem;
    align-items: center;
}

.hero-badge {
    display: inline-block;
    padding: 0.35rem 1rem;
    background: rgba(14, 165, 233, 0.12);
    border: 1px solid rgba(14, 165, 233, 0.3);
    color: var(--primary-light);
    border-radius: var(--radius-full);
    font-size: 0.85rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    margin-bottom: 1.25rem;
}

.hero-title {
    font-size: 3.25rem;
    font-weight: 800;
    line-height: 1.15;
    margin-bottom: 1.25rem;
    letter-spacing: -0.02em;
}

.hero-title span {
    background: linear-gradient(135deg, var(--text-primary) 0%, var(--primary-light) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.hero-desc {
    font-size: 1.15rem;
    color: var(--text-secondary);
    margin-bottom: 2rem;
    max-width: 540px;
}

.hero-actions {
    display: flex;
    gap: 1rem;
}

.btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.75rem 1.75rem;
    border-radius: var(--radius-md);
    font-weight: 600;
    font-size: 0.95rem;
    text-decoration: none;
    cursor: pointer;
    transition: all var(--transition-fast);
}

.btn-primary {
    background: var(--accent-blue);
    color: #ffffff;
    border: 1px solid var(--accent-blue);
}

.btn-primary:hover {
    background: #0284c7;
    border-color: #0284c7;
    box-shadow: 0 0 20px rgba(14, 165, 233, 0.4);
}

.btn-secondary {
    background: var(--bg-surface);
    color: var(--text-primary);
    border: 1px solid var(--border-color);
}

.btn-secondary:hover {
    background: #27354f;
    border-color: var(--text-secondary);
}

.hero-image-wrap {
    position: relative;
    border-radius: var(--radius-lg);
    overflow: hidden;
    border: 1px solid var(--border-color);
    box-shadow: var(--shadow-lg);
}

.hero-image-wrap img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}

/* Category Filter & Controls */
.controls-section {
    padding: 3rem 0 1.5rem 0;
}

.section-header {
    text-align: center;
    margin-bottom: 2.5rem;
}

.section-tag {
    color: var(--accent-blue);
    font-size: 0.85rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 0.5rem;
}

.section-title {
    font-size: 2.25rem;
    font-weight: 800;
}

.category-filter-bar {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-wrap: wrap;
    gap: 0.6rem;
    margin-bottom: 2rem;
}

.category-btn {
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    padding: 0.55rem 1.25rem;
    border-radius: var(--radius-full);
    font-size: 0.9rem;
    font-weight: 600;
    cursor: pointer;
    transition: all var(--transition-fast);
}

.category-btn:hover {
    color: var(--text-primary);
    border-color: var(--accent-blue);
}

.category-btn.active {
    background: var(--accent-blue);
    color: #ffffff;
    border-color: var(--accent-blue);
}

.search-sort-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1.5rem;
    margin-bottom: 2.5rem;
    background: var(--bg-card);
    padding: 1rem 1.5rem;
    border-radius: var(--radius-md);
    border: 1px solid var(--border-color);
}

.search-box {
    position: relative;
    flex: 1;
    max-width: 450px;
}

.search-box input {
    width: 100%;
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    padding: 0.65rem 1rem;
    border-radius: var(--radius-md);
    font-size: 0.95rem;
    outline: none;
    transition: border-color var(--transition-fast);
}

.search-box input:focus {
    border-color: var(--accent-blue);
}

.sort-box {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.sort-box label {
    font-size: 0.9rem;
    color: var(--text-secondary);
    font-weight: 500;
}

.sort-box select {
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    padding: 0.65rem 1rem;
    border-radius: var(--radius-md);
    font-size: 0.9rem;
    cursor: pointer;
    outline: none;
}

/* Products Grid */
.products-section {
    padding: 0 0 5rem 0;
}

.products-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
    gap: 1.75rem;
}

.product-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    overflow: hidden;
    display: flex;
    flex-direction: column;
    transition: transform var(--transition-fast), border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.product-card:hover {
    transform: translateY(-4px);
    border-color: var(--accent-blue);
    box-shadow: 0 12px 30px -10px rgba(14, 165, 233, 0.25);
}

.product-image-wrap {
    position: relative;
    width: 100%;
    aspect-ratio: 4 / 3;
    overflow: hidden;
    background: #0f172a;
}

.product-image-wrap img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: transform 0.3s ease;
}

.product-card:hover .product-image-wrap img {
    transform: scale(1.04);
}

.product-category-tag {
    position: absolute;
    top: 0.75rem;
    left: 0.75rem;
    background: rgba(15, 23, 42, 0.85);
    backdrop-filter: blur(4px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: var(--primary-light);
    font-size: 0.75rem;
    font-weight: 600;
    padding: 0.2rem 0.6rem;
    border-radius: var(--radius-sm);
}

.product-body {
    padding: 1.25rem;
    display: flex;
    flex-direction: column;
    flex-grow: 1;
}

.product-title {
    font-size: 1.15rem;
    font-weight: 700;
    margin-bottom: 0.5rem;
    color: var(--text-primary);
}

.product-desc {
    color: var(--text-secondary);
    font-size: 0.88rem;
    line-height: 1.5;
    margin-bottom: 1rem;
    flex-grow: 1;
}

.product-meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.25rem;
}

.product-price-wrap {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
}

.product-price {
    font-size: 1.25rem;
    font-weight: 800;
    color: var(--text-primary);
}

.product-original-price {
    font-size: 0.9rem;
    color: var(--text-muted);
    text-decoration: line-through;
}

.product-rating {
    font-size: 0.8rem;
    color: #fbbf24;
}

.product-rating-label {
    font-size: 0.7rem;
    color: var(--text-muted);
    margin-left: 0.25rem;
}

.product-card-actions {
    display: flex;
    gap: 0.6rem;
}

.btn-card {
    flex: 1;
    padding: 0.6rem 0.75rem;
    font-size: 0.85rem;
    border-radius: var(--radius-sm);
}

/* Feature Highlights */
.features-section {
    padding: 4rem 0;
    background: var(--bg-card);
    border-top: 1px solid var(--border-color);
    border-bottom: 1px solid var(--border-color);
}

.features-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 2rem;
}

.feature-item {
    display: flex;
    gap: 1.25rem;
    align-items: flex-start;
}

.feature-icon {
    font-size: 2rem;
    line-height: 1;
    color: var(--accent-blue);
}

.feature-item h4 {
    font-size: 1.1rem;
    margin-bottom: 0.35rem;
    color: var(--text-primary);
}

.feature-item p {
    color: var(--text-secondary);
    font-size: 0.9rem;
}

/* About Section */
.about-section {
    padding: 5rem 0;
}

.about-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 3.5rem;
    align-items: center;
}

.about-text h3 {
    font-size: 2.25rem;
    font-weight: 800;
    margin-bottom: 1.25rem;
}

.about-text p {
    color: var(--text-secondary);
    font-size: 1rem;
    margin-bottom: 1rem;
    line-height: 1.7;
}

.about-stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1.5rem;
    margin-top: 2rem;
}

.stat-box {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    padding: 1.25rem;
    border-radius: var(--radius-md);
    text-align: center;
}

.stat-number {
    font-size: 1.75rem;
    font-weight: 800;
    color: var(--accent-blue);
}

.stat-label {
    font-size: 0.8rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 0.25rem;
}

/* Contact Section */
.contact-section {
    padding: 5rem 0;
    background: var(--bg-card);
    border-top: 1px solid var(--border-color);
}

.contact-wrap {
    max-width: 680px;
    margin: 0 auto;
}

.contact-form {
    background: var(--bg-dark);
    border: 1px solid var(--border-color);
    padding: 2.5rem;
    border-radius: var(--radius-lg);
}

.form-group {
    margin-bottom: 1.5rem;
}

.form-group label {
    display: block;
    font-size: 0.9rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
    color: var(--text-primary);
}

.form-group input,
.form-group select,
.form-group textarea {
    width: 100%;
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    padding: 0.75rem 1rem;
    border-radius: var(--radius-md);
    font-size: 0.95rem;
    outline: none;
    font-family: inherit;
    transition: border-color var(--transition-fast);
}

.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus {
    border-color: var(--accent-blue);
}

.field-error {
    display: none;
    color: var(--color-error);
    font-size: 0.8rem;
    margin-top: 0.35rem;
}

.field-error:not(:empty) {
    display: block;
}

.form-feedback {
    display: none;
    padding: 1rem 1.25rem;
    border-radius: var(--radius-md);
    margin-bottom: 1.5rem;
    font-size: 0.9rem;
}

.form-feedback.success {
    background: rgba(16, 185, 129, 0.15);
    border: 1px solid rgba(16, 185, 129, 0.4);
    color: #6ee7b7;
}

/* Footer */
.site-footer {
    background: var(--bg-dark);
    border-top: 1px solid var(--border-color);
    padding: 4rem 0 2rem 0;
}

.footer-grid {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr 1.5fr;
    gap: 3rem;
    margin-bottom: 3rem;
}

.footer-col h4 {
    color: var(--text-primary);
    font-size: 1rem;
    margin-bottom: 1.25rem;
    font-weight: 700;
}

.footer-col p {
    color: var(--text-secondary);
    font-size: 0.9rem;
    line-height: 1.6;
}

.footer-col ul {
    list-style: none;
}

.footer-col ul li {
    margin-bottom: 0.6rem;
}

.footer-col ul a {
    color: var(--text-secondary);
    text-decoration: none;
    font-size: 0.9rem;
    transition: color var(--transition-fast);
}

.footer-col ul a:hover {
    color: var(--accent-blue);
}

.footer-bottom {
    padding-top: 2rem;
    border-top: 1px solid var(--border-subtle);
    display: flex;
    justify-content: space-between;
    align-items: center;
    color: var(--text-muted);
    font-size: 0.85rem;
    flex-wrap: wrap;
    gap: 1rem;
}

/* Modals */
.modal-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(11, 15, 23, 0.8);
    backdrop-filter: blur(8px);
    z-index: 1000;
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
}

.modal-overlay.open {
    display: flex;
}

.modal-dialog {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    width: 100%;
    max-width: 650px;
    max-height: 90vh;
    overflow-y: auto;
    position: relative;
    padding: 2rem;
    box-shadow: var(--shadow-lg);
}

.modal-close {
    position: absolute;
    top: 1.25rem;
    right: 1.25rem;
    background: transparent;
    border: none;
    color: var(--text-secondary);
    font-size: 1.5rem;
    line-height: 1;
    cursor: pointer;
    transition: color var(--transition-fast);
}

.modal-close:hover {
    color: var(--text-primary);
}

/* Cart Modal Specific */
.cart-modal-dialog {
    max-width: 550px;
}

.cart-items-list {
    margin: 1.5rem 0;
    max-height: 380px;
    overflow-y: auto;
}

.cart-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 1rem 0;
    border-bottom: 1px solid var(--border-subtle);
}

.cart-item-img {
    width: 60px;
    height: 60px;
    border-radius: var(--radius-sm);
    object-fit: cover;
    background: #0f172a;
}

.cart-item-info {
    flex-grow: 1;
}

.cart-item-title {
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--text-primary);
}

.cart-item-price {
    font-size: 0.85rem;
    color: var(--accent-blue);
    font-weight: 600;
}

.cart-qty-ctrl {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.qty-btn {
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    width: 28px;
    height: 28px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
}

.cart-summary {
    padding-top: 1.5rem;
    border-top: 1px solid var(--border-color);
}

.summary-row {
    display: flex;
    justify-content: space-between;
    font-size: 1.15rem;
    font-weight: 800;
    margin-bottom: 1.5rem;
}

/* Toast Notifications */
.toast-container {
    position: fixed;
    bottom: 2rem;
    right: 2rem;
    z-index: 2000;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    max-width: 420px;
}

.toast {
    background: var(--bg-surface);
    border: 1px solid var(--accent-blue);
    color: var(--text-primary);
    padding: 1rem 1.25rem;
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-lg);
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
    animation: slideIn 0.3s ease;
}

@keyframes slideIn {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
}

/* Responsive Media Queries */
/* ==========================================================================
   Testimonials Section (Illustrative)
   ========================================================================== */
.testimonials-section {
    padding: 6rem 0;
    background: var(--secondary-color);
}

.testimonials-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 2rem;
    margin-top: 3rem;
}

.testimonial-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    padding: 2.25rem 2rem;
    position: relative;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    transition: transform var(--transition-normal), border-color var(--transition-normal);
}

.testimonial-card:hover {
    transform: translateY(-4px);
    border-color: var(--primary-light);
}

.testimonial-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.25rem;
}

.testimonial-rating {
    color: #f59e0b;
    font-size: 1.15rem;
    letter-spacing: 2px;
}

.testimonial-illustrative-tag {
    font-size: 0.75rem;
    color: var(--text-muted);
    background: rgba(148, 163, 184, 0.1);
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-radius: 9999px;
    padding: 0.2rem 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
}

.testimonial-quote {
    color: var(--text-primary);
    font-size: 1.05rem;
    line-height: 1.7;
    margin: 0 0 1.75rem 0;
    font-style: italic;
}

.testimonial-author {
    display: flex;
    align-items: center;
    gap: 1rem;
    border-top: 1px solid var(--border-color);
    padding-top: 1.25rem;
}

.testimonial-avatar {
    width: 44px;
    height: 44px;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--primary-color), var(--primary-light));
    color: white;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1rem;
    letter-spacing: 0.5px;
    flex-shrink: 0;
}

.testimonial-author-info h4 {
    color: var(--text-primary);
    font-size: 1rem;
    margin: 0 0 0.25rem 0;
}

.testimonial-author-info p {
    color: var(--text-secondary);
    font-size: 0.85rem;
    margin: 0;
}

@media (max-width: 1024px) {
    .hero-grid { grid-template-columns: 1fr; gap: 2.5rem; }
    .about-grid { grid-template-columns: 1fr; gap: 2.5rem; }
    .footer-grid { grid-template-columns: 1fr 1fr; gap: 2rem; }
}

@media (max-width: 768px) {
    .nav-links { display: none; }
    .mobile-menu-btn { display: flex; }
    .hero-title { font-size: 2.5rem; }
    .search-sort-bar { flex-direction: column; align-items: stretch; }
    .search-box { max-width: 100%; }
    .products-grid { grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
    .about-stats { grid-template-columns: 1fr; gap: 1rem; }
    .testimonials-grid { grid-template-columns: 1fr; }
    .footer-grid { grid-template-columns: 1fr; gap: 2rem; }
}
"""
        css_path.write_text(css_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_files(ws, ["style.css"], source="foundation_scaffolder")

    # 3. index.html
    html_path = ws / "index.html"
    if not html_path.exists() or html_path.stat().st_size < 50:
        html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>⚡</text></svg>">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NOVA — Premium Consumer Electronics</title>
    <meta name="description" content="Discover cutting-edge personal computing, mobile, audio, and gaming technology from NOVA.">
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <!-- Navigation -->
    <header class="site-header" id="navbar">
        <div class="container navbar">
            <a href="#" class="brand-logo">NOVA<span class="brand-dot">.</span></a>
            <ul class="nav-links">
                <li><a href="#hero" class="active">Home</a></li>
                <li><a href="#products">Products</a></li>
                <li><a href="#categories">Categories</a></li>
                <li><a href="#about">About</a></li>
                <li><a href="#testimonials">Reviews</a></li>
                <li><a href="#contact">Contact</a></li>
            </ul>
            <div class="nav-actions">
                <button type="button" class="cart-btn" id="cart-btn" aria-label="View shopping cart">
                    <span class="cart-icon">🛒</span>
                    <span>Cart</span>
                    <span class="cart-badge" id="cart-count">0</span>
                </button>
                <button type="button" class="mobile-menu-btn" id="mobile-menu-btn" aria-label="Toggle navigation">
                    <span></span><span></span><span></span>
                </button>
            </div>
        </div>
    </header>

    <main>
        <!-- Hero Section -->
        <section class="hero" id="hero">
            <div class="container hero-grid">
                <div class="hero-content">
                    <span class="hero-badge">Next-Generation Engineering</span>
                    <h1 class="hero-title">Technology That <span>Moves You Forward</span></h1>
                    <p class="hero-desc">Explore NOVA's curated ecosystem of precision personal computing, audiophile wireless sound, and high-performance mobile devices.</p>
                    <div class="hero-actions">
                        <a href="#products" class="btn btn-primary">Shop Now</a>
                        <a href="#categories" class="btn btn-secondary">Explore Categories</a>
                    </div>
                </div>
                <div class="hero-image-wrap">
                    <img src="assets/images/hero/hero-electronics.jpg" alt="NOVA flagship electronics hardware showcase" loading="eager">
                </div>
            </div>
        </section>

        <!-- Categories Section -->
        <section class="controls-section" id="categories">
            <div class="container">
                <div class="section-header">
                    <span class="section-tag">Ecosystem</span>
                    <h2 class="section-title">Featured Hardware Categories</h2>
                </div>
                <div class="category-filter-bar" id="filters">
                    <button type="button" class="category-btn active" data-category="all">All Products</button>
                    <button type="button" class="category-btn" data-category="smartphones">Smartphones</button>
                    <button type="button" class="category-btn" data-category="laptops">Laptops</button>
                    <button type="button" class="category-btn" data-category="headphones">Headphones</button>
                    <button type="button" class="category-btn" data-category="smartwatches">Smartwatches</button>
                    <button type="button" class="category-btn" data-category="gaming">Gaming</button>
                    <button type="button" class="category-btn" data-category="accessories">Accessories</button>
                </div>
                <div class="search-sort-bar">
                    <div class="search-box">
                        <input type="text" id="product-search" placeholder="Search devices, specifications, or categories..." aria-label="Search products">
                    </div>
                    <div class="sort-box">
                        <label for="price-sort">Sort By:</label>
                        <select id="price-sort">
                            <option value="featured">Featured</option>
                            <option value="low-to-high">Price: Low to High</option>
                            <option value="high-to-low">Price: High to Low</option>
                        </select>
                    </div>
                </div>
            </div>
        </section>

        <!-- Products Section -->
        <section class="products-section" id="products">
            <div class="container">
                <div class="products-grid" id="products-grid">
                    <!-- Populated dynamically by app.js -->
                </div>
            </div>
        </section>

        <!-- Features Section -->
        <section class="features-section" id="features">
            <div class="container features-grid">
                <div class="feature-item">
                    <div class="feature-icon">⚡</div>
                    <div>
                        <h4>Precision Performance</h4>
                        <p>Custom silicon architecture engineered for maximum efficiency and extreme speed.</p>
                    </div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">🛡️</div>
                    <div>
                        <h4>2-Year Full Warranty</h4>
                        <p>Comprehensive hardware coverage and accidental damage support included with every purchase.</p>
                    </div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">🌐</div>
                    <div>
                        <h4>Free Global Delivery</h4>
                        <p>Express courier dispatch with carbon-neutral transit to over 140 countries worldwide.</p>
                    </div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">💬</div>
                    <div>
                        <h4>24/7 Tech Concierge</h4>
                        <p>Direct priority access to certified NOVA hardware specialists and engineers.</p>
                    </div>
                </div>
            </div>
        </section>

        <!-- About Section -->
        <section class="about-section" id="about">
            <div class="container about-grid">
                <div class="about-text">
                    <span class="section-tag">Brand Philosophy</span>
                    <h3>Engineered for What Comes Next</h3>
                    <p>At NOVA, we design consumer electronics at the intersection of aerospace-grade materials, minimalist industrial design, and intuitive human interface software.</p>
                    <p>Every curved edge, tactile switch, and OLED panel is calibrated to enhance your daily workflow, creativity, and gaming performance.</p>
                    <div class="about-stats">
                        <div class="stat-box">
                            <div class="stat-number">99.8%</div>
                            <div class="stat-label">Hardware Reliability</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-number">100%</div>
                            <div class="stat-label">Recycled Aluminum</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-number">4.9/5</div>
                            <div class="stat-label">Customer Satisfaction</div>
                        </div>
                    </div>
                </div>
                <div class="about-image-wrap hero-image-wrap">
                    <img src="assets/images/hero/hero-electronics.jpg" alt="NOVA advanced design engineering laboratory">
                </div>
            </div>
        </section>

<!-- Testimonials Section (Illustrative) -->
        <section class="testimonials-section" id="testimonials">
            <div class="container">
                <div class="section-header">
                    <span class="section-tag">User Perspectives</span>
                    <h2>Engineered for High Performers</h2>
                    <p class="section-subtitle">Illustrative impressions from creators, engineers, and audio professionals utilizing NOVA hardware in production.</p>
                </div>
                <div class="testimonials-grid">
                    <article class="testimonial-card">
                        <div class="testimonial-card-header">
                            <div class="testimonial-rating" aria-label="5 out of 5 stars">★★★★★</div>
                            <span class="testimonial-illustrative-tag">Illustrative</span>
                        </div>
                        <blockquote class="testimonial-quote">
                            "The NOVA Studio 16 handled our multi-track 8K ProRes render passes without thermal throttling. The sustained computing headroom is genuinely best-in-class."
                        </blockquote>
                        <div class="testimonial-author">
                            <div class="testimonial-avatar">ER</div>
                            <div class="testimonial-author-info">
                                <h4>Dr. Elena Rostova</h4>
                                <p>Lead Acoustic Architect, Apex Dynamics</p>
                            </div>
                        </div>
                    </article>
                    <article class="testimonial-card">
                        <div class="testimonial-card-header">
                            <div class="testimonial-rating" aria-label="5 out of 5 stars">★★★★★</div>
                            <span class="testimonial-illustrative-tag">Illustrative</span>
                        </div>
                        <blockquote class="testimonial-quote">
                            "The Sonic ANC headphones provide reference-flat neutrality essential for mastering complex spatial stems on international flights."
                        </blockquote>
                        <div class="testimonial-author">
                            <div class="testimonial-avatar">MV</div>
                            <div class="testimonial-author-info">
                                <h4>Marcus Vance</h4>
                                <p>Mastering Director, Neuralis Systems</p>
                            </div>
                        </div>
                    </article>
                    <article class="testimonial-card">
                        <div class="testimonial-card-header">
                            <div class="testimonial-rating" aria-label="5 out of 5 stars">★★★★★</div>
                            <span class="testimonial-illustrative-tag">Illustrative</span>
                        </div>
                        <blockquote class="testimonial-quote">
                            "Deploying the NOVA Reflex Keyboard across our hardware design lab gave us the tactile precision and latency ceiling we required."
                        </blockquote>
                        <div class="testimonial-author">
                            <div class="testimonial-avatar">SP</div>
                            <div class="testimonial-author-info">
                                <h4>Sophia Patel</h4>
                                <p>Robotics Systems Lead, Horizon Labs</p>
                            </div>
                        </div>
                    </article>
                </div>
            </div>
        </section>

                <!-- Contact Section -->
        <section class="contact-section" id="contact">
            <div class="container contact-wrap">
                <div class="section-header">
                    <span class="section-tag">Support</span>
                    <h2 class="section-title">Connect with NOVA Concierge</h2>
                </div>
                <div class="contact-form">
                    <div class="form-feedback" id="contact-feedback" style="display: none;"></div>
                    <form id="contact-form" novalidate>
                        <div class="form-group">
                            <label for="contact-name">Full Name</label>
                            <input type="text" id="contact-name" name="name" placeholder="Enter your full name" required>
                            <span class="field-error" id="contact-name-error"></span>
                        </div>
                        <div class="form-group">
                            <label for="contact-email">Email Address</label>
                            <input type="email" id="contact-email" name="email" placeholder="name@example.com" required>
                            <span class="field-error" id="contact-email-error"></span>
                        </div>
                        <div class="form-group">
                            <label for="contact-subject">Topic</label>
                            <select id="contact-subject" name="subject" required>
                                <option value="">Select an inquiry topic...</option>
                                <option value="sales">Product Consultation & Enterprise Sales</option>
                                <option value="support">Technical Support & Warranty</option>
                                <option value="shipping">Global Shipping & Logistics</option>
                                <option value="general">General Question</option>
                            </select>
                            <span class="field-error" id="contact-subject-error"></span>
                        </div>
                        <div class="form-group">
                            <label for="contact-message">Message</label>
                            <textarea id="contact-message" name="message" rows="4" placeholder="How may our technology specialists assist you?" required></textarea>
                            <span class="field-error" id="contact-message-error"></span>
                        </div>
                        <button type="submit" class="btn btn-primary" style="width: 100%;">Transmit Message</button>
                    </form>
                </div>
            </div>
        </section>
    </main>

    <!-- Footer -->
    <footer class="site-footer" id="footer">
        <div class="container">
            <div class="footer-grid">
                <div class="footer-col">
                    <a href="#" class="brand-logo" style="margin-bottom: 1rem;">NOVA<span class="brand-dot">.</span></a>
                    <p>Next-generation consumer hardware, mobile computing, and spatial gaming audio crafted with obsessive precision.</p>
                </div>
                <div class="footer-col">
                    <h4>Categories</h4>
                    <ul>
                        <li><a href="#products">Smartphones</a></li>
                        <li><a href="#products">Laptops</a></li>
                        <li><a href="#products">Headphones</a></li>
                        <li><a href="#products">Smartwatches</a></li>
                        <li><a href="#products">Gaming Gear</a></li>
                    </ul>
                </div>
                <div class="footer-col">
                    <h4>Company</h4>
                    <ul>
                        <li><a href="#about">About NOVA</a></li>
                        <li><a href="#features">Engineering & Materials</a></li>
                        <li><a href="#features">Warranty Policy</a></li>
                        <li><a href="#contact">Contact Support</a></li>
                    </ul>
                </div>
                <div class="footer-col">
                    <h4>Contact & Inquiries</h4>
                    <p>
                        <strong>Illustrative Sample Address:</strong><br>
                        800 Innovation Parkway, Suite 400<br>
                        San Francisco, CA 94107
                    </p>
                    <p style="margin-top: 0.5rem;">
                        <strong>Sample Demonstration Phone:</strong><br>
                        (Optional) e.g. +1 555-0100
                    </p>
                    <p style="margin-top: 0.5rem;">
                        <strong>Sample Demonstration Email:</strong><br>
                        support@nova.example
                    </p>
                    <p style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.75rem; font-style: italic;">
                        All contact details shown are illustrative and do not represent an operating company.
                    </p>
                </div>
            </div>
            <div class="footer-bottom">
                <div>&copy; 2026 NOVA Technologies Inc. All contact details shown are illustrative and do not represent an operating company.</div>
                <div>Demonstration E-Commerce Portal</div>
            </div>
        </div>
    </footer>

    <!-- Product Details Modal -->
    <div class="modal-overlay" id="product-modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <div class="modal-dialog">
            <button type="button" class="modal-close" id="product-modal-close" aria-label="Close modal">&times;</button>
            <div id="product-modal-body">
                <!-- Dynamically rendered by app.js -->
            </div>
        </div>
    </div>

    <!-- Shopping Cart Modal -->
    <div class="modal-overlay" id="cart-modal" role="dialog" aria-modal="true" aria-labelledby="cart-modal-title">
        <div class="modal-dialog cart-modal-dialog">
            <button type="button" class="modal-close" id="cart-modal-close" aria-label="Close cart">&times;</button>
            <h3 id="cart-modal-title" style="font-size: 1.5rem; font-weight: 800; margin-bottom: 1rem;">Your Cart</h3>
            <div class="cart-items-list" id="cart-items">
                <!-- Dynamically rendered by app.js -->
            </div>
            <div class="cart-summary">
                <div class="summary-row">
                    <span>Subtotal:</span>
                    <span id="cart-subtotal">$0.00</span>
                </div>
                <button type="button" class="btn btn-primary" id="checkout-btn" style="width: 100%;">Proceed to Demonstration Checkout</button>
            </div>
        </div>
    </div>

    <!-- Demonstration Checkout Modal -->
    <div class="modal-overlay" id="checkout-modal" role="dialog" aria-modal="true" aria-labelledby="checkout-title">
        <div class="modal-dialog">
            <button type="button" class="modal-close" id="checkout-modal-close" aria-label="Close checkout">&times;</button>
            <h3 id="checkout-title" style="font-size: 1.5rem; font-weight: 800; margin-bottom: 0.5rem;">Demonstration Checkout</h3>
            <p style="color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 1.5rem;">This checkout is a frontend demonstration experience. No real payment or order will be processed.</p>
            <div class="form-feedback success" style="display: block; margin-bottom: 1.5rem;">
                <strong>Demonstration Mode:</strong> Your checkout request has been validated in demonstration mode. No actual payment or order has been created.
            </div>
            <div style="background: var(--bg-surface); padding: 1.25rem; border-radius: var(--radius-md); border: 1px solid var(--border-color); margin-bottom: 1.5rem;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                    <span style="color: var(--text-secondary);">Simulated Items:</span>
                    <span id="checkout-items-count">0 items</span>
                </div>
                <div style="display: flex; justify-content: space-between; font-weight: 700; font-size: 1.1rem;">
                    <span>Total Amount:</span>
                    <span id="checkout-total-amount">$0.00</span>
                </div>
            </div>
            <button type="button" class="btn btn-secondary" id="checkout-done-btn" style="width: 100%;">Return to Store</button>
        </div>
    </div>

    <!-- Toast Notifications Container -->
    <div class="toast-container" id="toast-container"></div>

    <script src="app.js"></script>
</body>
</html>"""
        html_path.write_text(html_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_files(ws, ["index.html"], source="foundation_scaffolder")

    # 4. app.js
    js_path = ws / "app.js"
    if not js_path.exists() or js_path.stat().st_size < 50:
        js_content = r"""/* ==========================================================================
   NOVA — Consumer Electronics Interactive Application Logic
   ========================================================================== */

const PRODUCTS = [
    {
        id: "nova-apex-pro",
        name: "NOVA Apex Pro 5G",
        category: "smartphones",
        price: 1099,
        originalPrice: 1199,
        image: "assets/images/products/nova-apex-pro.jpg",
        description: "Flagship titanium smartphone powered by custom 3nm neural silicon with 120Hz ProMotion OLED and periscope telephoto optics.",
        specs: ["Titanium Frame", "6.7-inch Super Retina OLED", "3nm Neural Engine", "50MP Triple Camera", "512GB Storage"],
        rating: 4.9,
        inStock: true
    },
    {
        id: "nova-pulse-mini",
        name: "NOVA Pulse Mini 5G",
        category: "smartphones",
        price: 749,
        originalPrice: null,
        image: "assets/images/products/nova-pulse-mini.jpg",
        description: "Compact high-performance smartphone engineered for one-handed mastery with edge-to-edge Ceramic Shield display.",
        specs: ["Aerospace Aluminum", "5.8-inch OLED", "All-day Battery", "Dual 48MP Optics", "256GB Storage"],
        rating: 4.8,
        inStock: true
    },
    {
        id: "nova-book-15",
        name: "NOVA Book Ultralight 15",
        category: "laptops",
        price: 1399,
        originalPrice: null,
        image: "assets/images/products/nova-book-15.jpg",
        description: "Featherweight 15-inch magnesium-alloy laptop with 22-hour battery life and Liquid Retina XDR color-accurate display.",
        specs: ["1.1kg Magnesium Body", "15.3-inch Retina XDR", "12-Core CPU / 18-Core GPU", "32GB Unified Memory", "1TB Gen4 NVMe"],
        rating: 4.9,
        inStock: true
    },
    {
        id: "nova-studio-16",
        name: "NOVA Studio Pro 16",
        category: "laptops",
        price: 2299,
        originalPrice: 2499,
        image: "assets/images/products/nova-studio-16.jpg",
        description: "Uncompromised workstation laptop for 3D creators, video editors, and engineers with high-wattage ray tracing graphics.",
        specs: ["Dual Vapor Chamber Cooling", "16.2-inch Mini-LED 165Hz", "64GB High-Bandwidth RAM", "Dedicated 16GB VRAM", "2TB NVMe SSD"],
        rating: 5.0,
        inStock: true
    },
    {
        id: "nova-sonic-anc",
        name: "NOVA Sonic ANC Wireless",
        category: "headphones",
        price: 349,
        originalPrice: null,
        image: "assets/images/products/nova-sonic-anc.jpg",
        description: "Studio-grade wireless over-ear headphones featuring hybrid active noise cancellation, custom beryllium drivers, and spatial audio.",
        specs: ["Hybrid Adaptive ANC", "45-Hour Battery", "Beryllium Acoustic Drivers", "Lossless Bluetooth 5.4", "Memory Foam Ear Cushions"],
        rating: 4.9,
        inStock: true
    },
    {
        id: "nova-soundbuds-pro",
        name: "NOVA SoundBuds Pro",
        category: "headphones",
        price: 199,
        originalPrice: null,
        image: "assets/images/products/nova-soundbuds-pro.jpg",
        description: "True wireless in-ear earbuds with dynamic head-tracking spatial audio, IPX7 water resistance, and wireless charging case.",
        specs: ["Spatial Audio Head Tracking", "IPX7 Waterproof", "32 Hours Total Playtime", "Transparency Audio Mode", "Quad Microphones"],
        rating: 4.7,
        inStock: true
    },
    {
        id: "nova-chrono-steel",
        name: "NOVA Chrono Precision Steel",
        category: "smartwatches",
        price: 429,
        originalPrice: null,
        image: "assets/images/products/nova-chrono-steel.jpg",
        description: "Hand-polished 316L stainless steel smartwatch combining luxury horological aesthetics with continuous ECG and health metrics.",
        specs: ["316L Surgical Steel", "Always-on Sapphire Crystal", "Continuous ECG & SpO2", "7-Day Battery", "50M Water Resistance"],
        rating: 4.8,
        inStock: true
    },
    {
        id: "nova-fit-active",
        name: "NOVA Fit Active Titanium",
        category: "smartwatches",
        price: 279,
        originalPrice: null,
        image: "assets/images/products/nova-fit-active.jpg",
        description: "Ultra-durable sport smartwatch built from grade-5 titanium with dual-frequency GPS navigation and triathlon workout telemetry.",
        specs: ["Grade 5 Titanium Bezel", "Dual-Frequency GPS", "100+ Sport Modes", "Offline Topo Maps", "14-Day Adventure Battery"],
        rating: 4.8,
        inStock: true
    },
    {
        id: "nova-horizon-vr",
        name: "NOVA Horizon VR Spatial Headset",
        category: "gaming",
        price: 899,
        originalPrice: 999,
        image: "assets/images/products/nova-horizon-vr.jpg",
        description: "Standalone spatial computing headset delivering 4K micro-OLED resolution per eye with sub-millimeter inside-out tracking.",
        specs: ["Dual 4K Micro-OLED", "120Hz Refresh Rate", "LiDAR Space Mapping", "Spatial Audio Array", "Wi-Fi 7 Ultra-Low Latency"],
        rating: 4.9,
        inStock: true
    },
    {
        id: "nova-reflex-keyboard",
        name: "NOVA Reflex Mechanical Gaming Keyboard",
        category: "gaming",
        price: 179,
        originalPrice: null,
        image: "assets/images/products/nova-reflex-keyboard.jpg",
        description: "CNC aluminum hot-swappable mechanical keyboard with magnetic analog optical switches, 8000Hz polling rate, and PBT keycaps.",
        specs: ["Hot-Swappable Switches", "8000Hz Hyper-Polling", "Anodized Aluminum Case", "Sound-Dampening Gaskets", "Custom Per-Key RGB"],
        rating: 4.8,
        inStock: true
    },
    {
        id: "nova-gan-charger",
        name: "NOVA PowerMatrix 100W GaN Charger",
        category: "accessories",
        price: 69,
        originalPrice: null,
        image: "assets/images/products/nova-gan-charger.jpg",
        description: "Ultra-compact Gallium Nitride multi-port power adapter capable of fast-charging laptops, smartphones, and tablets simultaneously.",
        specs: ["100W Max Power Delivery", "3x USB-C + 1x USB-A", "Gallium Nitride Gen3", "Intelligent Power Allocation", "Foldable Travel Prongs"],
        rating: 4.9,
        inStock: true
    },
    {
        id: "nova-magnetic-stand",
        name: "NOVA Magnetic 3-in-1 Charging Stand",
        category: "accessories",
        price: 119,
        originalPrice: null,
        image: "assets/images/products/nova-magnetic-stand.jpg",
        description: "Sculpted weighted aluminum desk stand for simultaneous magnetic wireless charging of your smartphone, smartwatch, and earbuds.",
        specs: ["15W Qi2 Fast Wireless", "Precision MagAlignment", "Solid Billet Aluminum Base", "Adjustable Viewing Angle", "Integrated Ambient LED"],
        rating: 4.8,
        inStock: true
    }
];

// App State
let cart = [];
let currentCategory = "all";
let searchQuery = "";
let sortBy = "featured";

// Initialize App
document.addEventListener("DOMContentLoaded", () => {
    loadCartFromStorage();
    renderProducts();
    initFilterControls();
    initSearchAndSort();
    initModals();
    initContactForm();
    initMobileNav();
    updateCartBadge();
});

// Load & Save Cart
function loadCartFromStorage() {
    try {
        const stored = localStorage.getItem("nova_cart_items");
        if (stored) {
            cart = JSON.parse(stored);
        }
    } catch (e) {
        cart = [];
    }
}

function saveCartToStorage() {
    try {
        localStorage.setItem("nova_cart_items", JSON.stringify(cart));
    } catch (e) {}
}

// Render Products Grid
function renderProducts() {
    const grid = document.getElementById("products-grid");
    if (!grid) return;

    let filtered = PRODUCTS.filter(p => {
        const matchCat = currentCategory === "all" || p.category === currentCategory;
        const matchSearch = !searchQuery || 
            p.name.toLowerCase().includes(searchQuery) ||
            p.description.toLowerCase().includes(searchQuery) ||
            p.category.toLowerCase().includes(searchQuery);
        return matchCat && matchSearch;
    });

    if (sortBy === "low-to-high") {
        filtered.sort((a, b) => a.price - b.price);
    } else if (sortBy === "high-to-low") {
        filtered.sort((a, b) => b.price - a.price);
    }

    if (filtered.length === 0) {
        grid.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 4rem 1rem; color: var(--text-secondary);">
                <p style="font-size: 1.25rem; font-weight: 600; margin-bottom: 0.5rem;">No products match your criteria</p>
                <p style="font-size: 0.95rem;">Try modifying your search term or switching to another category.</p>
            </div>
        `;
        return;
    }

    grid.innerHTML = filtered.map(p => `
        <article class="product-card" data-category="${p.category}" data-product-id="${p.id}">
            <div class="product-image-wrap">
                <img src="${p.image}" alt="${p.name}" >
                <span class="product-category-tag">${p.category.toUpperCase()}</span>
            </div>
            <div class="product-body">
                <h3 class="product-title">${p.name}</h3>
                <p class="product-desc">${p.description}</p>
                <div class="product-meta">
                    <div class="product-price-wrap">
                        <span class="product-price">$${p.price.toLocaleString()}</span>
                        ${p.originalPrice ? `<span class="product-original-price">$${p.originalPrice.toLocaleString()}</span>` : ""}
                    </div>
                    <div class="product-rating">
                        <span>★ ${p.rating}</span>
                        <span class="product-rating-label">(Illustrative)</span>
                    </div>
                </div>
                <div class="product-card-actions">
                    <button type="button" class="btn btn-secondary btn-card view-details-btn" data-id="${p.id}">Details</button>
                    <button type="button" class="btn btn-primary btn-card add-cart-btn" data-id="${p.id}">Add to Cart</button>
                </div>
            </div>
        </article>
    `).join("");

    // Attach card button listeners
    grid.querySelectorAll(".view-details-btn").forEach(btn => {
        btn.addEventListener("click", () => openProductModal(btn.getAttribute("data-id")));
    });
    grid.querySelectorAll(".add-cart-btn").forEach(btn => {
        btn.addEventListener("click", () => addToCart(btn.getAttribute("data-id")));
    });
}

// Category & Controls
function initFilterControls() {
    const filterBtns = document.querySelectorAll(".category-btn");
    filterBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            filterBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentCategory = btn.getAttribute("data-category") || "all";
            renderProducts();
        });
    });
}

function initSearchAndSort() {
    const searchInput = document.getElementById("product-search");
    if (searchInput) {
        searchInput.addEventListener("input", (e) => {
            searchQuery = e.target.value.trim().toLowerCase();
            renderProducts();
        });
    }

    const sortSelect = document.getElementById("price-sort");
    if (sortSelect) {
        sortSelect.addEventListener("change", (e) => {
            sortBy = e.target.value;
            renderProducts();
        });
    }
}

// Cart Operations
function addToCart(productId) {
    const product = PRODUCTS.find(p => p.id === productId);
    if (!product) return;

    const existing = cart.find(item => item.id === productId);
    if (existing) {
        existing.quantity += 1;
    } else {
        cart.push({
            id: product.id,
            name: product.name,
            price: product.price,
            image: product.image,
            quantity: 1
        });
    }

    saveCartToStorage();
    updateCartBadge();
    showToast(`Added ${product.name} to your cart.`);
}

function updateCartQuantity(productId, delta) {
    const item = cart.find(i => i.id === productId);
    if (!item) return;

    item.quantity += delta;
    if (item.quantity <= 0) {
        cart = cart.filter(i => i.id !== productId);
    }

    saveCartToStorage();
    updateCartBadge();
    renderCartModalItems();
}

function removeFromCart(productId) {
    cart = cart.filter(i => i.id !== productId);
    saveCartToStorage();
    updateCartBadge();
    renderCartModalItems();
}

function calculateSubtotal() {
    return cart.reduce((sum, item) => sum + (item.price * item.quantity), 0);
}

function updateCartBadge() {
    const countEl = document.getElementById("cart-count");
    if (countEl) {
        const totalItems = cart.reduce((sum, item) => sum + item.quantity, 0);
        countEl.textContent = totalItems.toString();
    }
}

// Modals Handling
function initModals() {
    // Cart Modal
    const cartBtn = document.getElementById("cart-btn");
    const cartModal = document.getElementById("cart-modal");
    const cartClose = document.getElementById("cart-modal-close");
    const checkoutBtn = document.getElementById("checkout-btn");

    if (cartBtn && cartModal) {
        cartBtn.addEventListener("click", () => {
            renderCartModalItems();
            cartModal.classList.add("open");
        });
    }
    if (cartClose && cartModal) {
        cartClose.addEventListener("click", () => cartModal.classList.remove("open"));
    }

    // Checkout Modal
    const checkoutModal = document.getElementById("checkout-modal");
    const checkoutClose = document.getElementById("checkout-modal-close");
    const checkoutDone = document.getElementById("checkout-done-btn");

    if (checkoutBtn && checkoutModal && cartModal) {
        checkoutBtn.addEventListener("click", () => {
            if (cart.length === 0) {
                showToast("Your cart is empty.");
                return;
            }
            cartModal.classList.remove("open");
            const countEl = document.getElementById("checkout-items-count");
            const totalEl = document.getElementById("checkout-total-amount");
            const totalItems = cart.reduce((sum, item) => sum + item.quantity, 0);
            if (countEl) countEl.textContent = `${totalItems} item${totalItems === 1 ? "" : "s"}`;
            if (totalEl) totalEl.textContent = `$${calculateSubtotal().toLocaleString()}`;
            checkoutModal.classList.add("open");
        });
    }
    if (checkoutClose && checkoutModal) {
        checkoutClose.addEventListener("click", () => checkoutModal.classList.remove("open"));
    }
    if (checkoutDone && checkoutModal) {
        checkoutDone.addEventListener("click", () => checkoutModal.classList.remove("open"));
    }

    // Product Modal
    const productModal = document.getElementById("product-modal");
    const productClose = document.getElementById("product-modal-close");
    if (productClose && productModal) {
        productClose.addEventListener("click", () => productModal.classList.remove("open"));
    }

    // Close on backdrop click & Escape key
    window.addEventListener("click", (e) => {
        if (e.target.classList.contains("modal-overlay")) {
            e.target.classList.remove("open");
        }
    });
    window.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            document.querySelectorAll(".modal-overlay.open").forEach(m => m.classList.remove("open"));
        }
    });
}

function openProductModal(productId) {
    const product = PRODUCTS.find(p => p.id === productId);
    if (!product) return;

    const modalBody = document.getElementById("product-modal-body");
    const productModal = document.getElementById("product-modal");
    if (!modalBody || !productModal) return;

    modalBody.innerHTML = `
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; align-items: start;">
            <div style="border-radius: var(--radius-md); overflow: hidden; background: #0f172a; border: 1px solid var(--border-color);">
                <img src="${product.image}" alt="${product.name}" style="width: 100%; display: block; aspect-ratio: 4/3; object-fit: cover;">
            </div>
            <div>
                <span class="hero-badge" style="margin-bottom: 0.5rem;">${product.category.toUpperCase()}</span>
                <h2 id="modal-title" style="font-size: 1.75rem; font-weight: 800; margin-bottom: 0.75rem;">${product.name}</h2>
                <div style="display: flex; align-items: baseline; gap: 0.75rem; margin-bottom: 1rem;">
                    <span style="font-size: 1.5rem; font-weight: 800;">$${product.price.toLocaleString()}</span>
                    ${product.originalPrice ? `<span style="font-size: 1rem; color: var(--text-muted); text-decoration: line-through;">$${product.originalPrice.toLocaleString()}</span>` : ""}
                </div>
                <p style="color: var(--text-secondary); font-size: 0.95rem; line-height: 1.6; margin-bottom: 1.5rem;">${product.description}</p>
                <div style="margin-bottom: 1.5rem;">
                    <h4 style="font-size: 0.95rem; font-weight: 700; margin-bottom: 0.5rem; color: var(--text-primary);">Specifications:</h4>
                    <ul style="list-style: disc; padding-left: 1.25rem; color: var(--text-secondary); font-size: 0.9rem;">
                        ${product.specs.map(s => `<li style="margin-bottom: 0.25rem;">${s}</li>`).join("")}
                    </ul>
                </div>
                <button type="button" class="btn btn-primary" id="modal-add-cart-btn" style="width: 100%;">Add to Cart ($${product.price})</button>
            </div>
        </div>
    `;

    document.getElementById("modal-add-cart-btn").addEventListener("click", () => {
        addToCart(product.id);
        productModal.classList.remove("open");
    });

    productModal.classList.add("open");
}

function renderCartModalItems() {
    const itemsList = document.getElementById("cart-items");
    const subtotalEl = document.getElementById("cart-subtotal");
    if (!itemsList || !subtotalEl) return;

    if (cart.length === 0) {
        itemsList.innerHTML = `
            <div style="text-align: center; padding: 2.5rem 0; color: var(--text-secondary);">
                <p style="font-size: 1.1rem; font-weight: 600;">Your shopping cart is empty</p>
                <p style="font-size: 0.9rem; margin-top: 0.25rem;">Explore our products and add devices to your cart.</p>
            </div>
        `;
        subtotalEl.textContent = "$0.00";
        return;
    }

    itemsList.innerHTML = cart.map(item => `
        <div class="cart-item">
            <img src="${item.image}" alt="${item.name}" class="cart-item-img">
            <div class="cart-item-info">
                <div class="cart-item-title">${item.name}</div>
                <div class="cart-item-price">$${item.price.toLocaleString()}</div>
            </div>
            <div class="cart-qty-ctrl">
                <button type="button" class="qty-btn" onclick="updateCartQuantity('${item.id}', -1)">−</button>
                <span style="font-weight: 700; min-width: 20px; text-align: center;">${item.quantity}</span>
                <button type="button" class="qty-btn" onclick="updateCartQuantity('${item.id}', 1)">+</button>
                <button type="button" class="modal-close" style="position: static; font-size: 1.25rem; margin-left: 0.5rem;" onclick="removeFromCart('${item.id}')" aria-label="Remove item">&times;</button>
            </div>
        </div>
    `).join("");

    subtotalEl.textContent = `$${calculateSubtotal().toLocaleString()}`;
}

// Contact Form
function initContactForm() {
    const form = document.getElementById("contact-form");
    const feedback = document.getElementById("contact-feedback");
    if (!form || !feedback) return;

    const nameInput = document.getElementById("contact-name");
    const emailInput = document.getElementById("contact-email");
    const subjectInput = document.getElementById("contact-subject");
    const messageInput = document.getElementById("contact-message");

    const clearError = (input) => {
        const err = document.getElementById(`${input.id}-error`);
        if (err) {
            err.textContent = "";
            err.style.display = "none";
        }
        input.removeAttribute("aria-invalid");
    };

    [nameInput, emailInput, messageInput].forEach(inp => {
        if (inp) {
            inp.addEventListener("input", () => clearError(inp));
        }
    });
    if (subjectInput) {
        subjectInput.addEventListener("change", () => clearError(subjectInput));
    }

    form.addEventListener("reset", () => {
        [nameInput, emailInput, subjectInput, messageInput].forEach(inp => {
            if (inp) clearError(inp);
        });
        feedback.style.display = "none";
        feedback.textContent = "";
    });

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        let valid = true;

        if (!nameInput.value.trim()) {
            showFieldError("contact-name", "Please enter your full name.");
            valid = false;
        }
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(emailInput.value.trim())) {
            showFieldError("contact-email", "Please enter a valid email address.");
            valid = false;
        }
        if (!subjectInput.value) {
            showFieldError("contact-subject", "Please select an inquiry topic.");
            valid = false;
        }
        if (messageInput.value.trim().length < 10) {
            showFieldError("contact-message", "Please enter a message (at least 10 characters).");
            valid = false;
        }

        if (!valid) return;

        feedback.className = "form-feedback success";
        feedback.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem;">
                <div>
                    <strong>Demonstration Mode:</strong> Thank you! Your enquiry has been validated successfully in demonstration mode. No message has been transmitted to an operating company.
                    <div style="margin-top: 0.35rem; font-size: 0.85rem; opacity: 0.9;">Reference: DEMO-NOVA-${Date.now().toString(36).toUpperCase()}</div>
                </div>
                <button type="button" class="feedback-close" aria-label="Close notification" style="background: transparent; border: none; color: inherit; font-size: 1.25rem; cursor: pointer; padding: 0 0.25rem; line-height: 1;">&times;</button>
            </div>
        `;
        feedback.style.display = "block";

        const closeBtn = feedback.querySelector(".feedback-close");
        if (closeBtn) {
            closeBtn.addEventListener("click", () => {
                feedback.style.display = "none";
            });
        }

        form.reset();
        showToast("Enquiry validated in demonstration mode.");
    });
}

function showFieldError(inputId, message) {
    const err = document.getElementById(`${inputId}-error`);
    const inp = document.getElementById(inputId);
    if (err) {
        err.textContent = message;
        err.style.display = "block";
    }
    if (inp) {
        inp.setAttribute("aria-invalid", "true");
    }
}

// Mobile Nav
function initMobileNav() {
    const btn = document.getElementById("mobile-menu-btn");
    const links = document.querySelector(".nav-links");
    if (!btn || !links) return;

    btn.addEventListener("click", () => {
        const isExpanded = btn.getAttribute("aria-expanded") === "true";
        btn.setAttribute("aria-expanded", !isExpanded);
        links.style.display = isExpanded ? "none" : "flex";
        if (!isExpanded) {
            links.style.flexDirection = "column";
            links.style.position = "absolute";
            links.style.top = "72px";
            links.style.left = "0";
            links.style.right = "0";
            links.style.background = "var(--bg-card)";
            links.style.padding = "2rem";
            links.style.borderBottom = "1px solid var(--border-color)";
        }
    });
}

// Toasts
let toastTimer = null;
function showToast(message) {
    const container = document.getElementById("toast-container");
    if (!container) return;

    container.innerHTML = `
        <div class="toast" role="status" aria-live="polite">
            <span>${message}</span>
            <button type="button" class="toast-close" aria-label="Close notification" style="background: transparent; border: none; color: inherit; cursor: pointer; font-size: 1.1rem; line-height: 1;">&times;</button>
        </div>
    `;

    const closeBtn = container.querySelector(".toast-close");
    if (closeBtn) {
        closeBtn.addEventListener("click", hideToast);
    }

    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(hideToast, 4500);
}

function hideToast() {
    const container = document.getElementById("toast-container");
    if (container) container.innerHTML = "";
    if (toastTimer) {
        clearTimeout(toastTimer);
        toastTimer = null;
    }
}
"""
        js_path.write_text(js_content, encoding="utf-8")
        WorkspaceOwnershipManifest.register_generated_files(ws, ["app.js"], source="foundation_scaffolder")

    return True
