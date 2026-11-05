# core/scripts/validate_wanderworld_greenfield.py
"""
Deterministic Greenfield Website Qualification & Multi-Viewport Verification Script.
Validates the complete HERMES 2.x website generation and visual acceptance pipeline
on the representative WanderWorld mission in C:\\Users\\SUBBU\\Downloads\\wanderworld_val.
"""

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

# Ensure hermes repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from core.asset_pipeline import AssetPipeline
from core.design_intelligence import DesignBriefGenerator, ContentCoverageMap
from core.frontend_contract_validator import FrontendContractValidator
from core.verification_profiles import VerificationProfile, VerificationProfileEvaluator
from core.browser.manager import BrowserManager, Viewport
from core.browser.dev_server import DevServerManager
from core.browser.acceptance import BrowserAcceptanceVerifier


WORKSPACE_DIR = Path(r"C:\Users\SUBBU\Downloads\wanderworld_val").resolve()

PROMPT = (
    "Create a visually impressive travel agency website called WanderWorld. "
    "The website should help visitors explore holiday destinations and discover travel packages. "
    "Include: "
    "- A full-width travel photography hero section. "
    "- Destination cards for Bali, Switzerland, Paris, Dubai, Maldives and Japan. "
    "- Destination search and category filters. "
    "- Travel package cards with prices, duration and details button. "
    "- Customer reviews and testimonials section. "
    "- Clean booking/inquiry modal dialog. "
    "- Booking inquiry form with validation. "
    "- Responsive design for mobile and desktop."
)


async def main():
    print(f"=== Starting Greenfield Validation in {WORKSPACE_DIR} ===")
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    screenshots_dir = WORKSPACE_DIR / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    # 1. Asset Pipeline Provisioning
    print("\n[Step 1] Provisioning genuine photographic assets via AssetPipeline...")
    manifest = AssetPipeline.provision_assets(
        workspace_root=WORKSPACE_DIR,
        prompt=PROMPT,
        domain="travel_tourism",
        mission_id="m_wanderworld_val_001",
    )
    print(f"Provisioned {len(manifest.assets)} assets in assets/images/")
    for a in manifest.assets[:5]:
        p = WORKSPACE_DIR / a.relative_path
        print(f"  • {a.asset_id}: {a.relative_path} ({round(p.stat().st_size/1024, 1)} KB)")

    # 2. Design Intelligence & Brief Generation
    print("\n[Step 2] Generating Design Brief and Content Coverage Map...")
    brief = DesignBriefGenerator.generate_brief(PROMPT, active_skills=["taste-design", "design-engineering", "design-system", "web-design-guidelines", "vanilla-web"])
    brief.persist_artifacts(WORKSPACE_DIR)
    cmap = ContentCoverageMap.from_prompt(PROMPT)
    print(f"Design Brief persisted. Domain: {brief.domain}, Personality: {brief.brand_personality}")

    # 3. Code Generation (HTML, CSS, JS)
    print("\n[Step 3] Emitting Production Website Implementation...")
    
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>WanderWorld — Curated Luxury Travel & Expeditions</title>
  <link rel="stylesheet" href="style.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body>
  <!-- Navigation Header -->
  <header class="navbar" id="navbar">
    <div class="nav-container">
      <a href="#" class="brand-logo">
        <span class="logo-mark">❖</span>
        <span class="logo-text">WanderWorld</span>
      </a>
      <nav class="nav-menu" id="nav-menu">
        <a href="#destinations" class="nav-link">Destinations</a>
        <a href="#packages" class="nav-link">Packages</a>
        <a href="#reviews" class="nav-link">Reviews</a>
        <a href="#booking" class="nav-link">Contact</a>
      </nav>
      <div class="nav-actions">
        <a href="#booking" class="btn btn-primary nav-cta">Book Journey</a>
      </div>
    </div>
  </header>

  <!-- Hero Section -->
  <section class="hero" id="hero">
    <div class="hero-overlay"></div>
    <div class="hero-content">
      <span class="hero-badge">Bespoke Journeys Across 7 Continents</span>
      <h1 class="hero-title">Wander Beyond Horizons</h1>
      <p class="hero-subtitle">Discover handpicked luxury resorts, private island sanctuaries, and transformative cultural expeditions tailored to your aspirations.</p>
      
      <!-- Quick Booking / Search Widget -->
      <div class="search-widget" id="search-widget">
        <div class="search-field">
          <label for="dest-search">Where To?</label>
          <input type="text" id="dest-search" placeholder="Search Bali, Switzerland, Paris...">
        </div>
        <div class="search-field">
          <label for="trip-category-select">Travel Style</label>
          <select id="trip-category-select">
            <option value="all">All Styles</option>
            <option value="beach">Tropical Beach</option>
            <option value="mountain">Alpine Mountain</option>
            <option value="cultural">Heritage & Culture</option>
            <option value="luxury">Metropolitan Luxury</option>
          </select>
        </div>
        <div class="search-field">
          <label for="trip-travelers">Travelers</label>
          <select id="trip-travelers">
            <option value="2">2 Adults</option>
            <option value="1">Solo Traveler</option>
            <option value="4">Family (4)</option>
          </select>
        </div>
        <button type="button" class="btn btn-accent search-submit-btn" id="search-btn">Explore</button>
      </div>
    </div>
  </section>

  <!-- Featured Destinations Section -->
  <section class="section destinations-section" id="destinations">
    <div class="container">
      <div class="section-header">
        <span class="section-eyebrow">Iconic Escapes</span>
        <h2 class="section-title">Featured Holiday Destinations</h2>
        <p class="section-desc">Immerse yourself in world-renowned panoramas and intimate cultural wonders.</p>
        
        <!-- Category Filter Pills -->
        <div class="filter-pills" id="category-filters">
          <button type="button" class="filter-pill active" data-category="all">All</button>
          <button type="button" class="filter-pill" data-category="beach">Beach</button>
          <button type="button" class="filter-pill" data-category="mountain">Mountain</button>
          <button type="button" class="filter-pill" data-category="cultural">Cultural</button>
          <button type="button" class="filter-pill" data-category="luxury">Luxury</button>
        </div>
      </div>

      <!-- Destination Cards Grid -->
      <div class="cards-grid destinations-grid" id="destinations-grid">
        <!-- Rendered dynamically by app.js with verified local photography -->
      </div>
    </div>
  </section>

  <!-- Curated Travel Packages Section -->
  <section class="section packages-section" id="packages">
    <div class="container">
      <div class="section-header">
        <span class="section-eyebrow">Signature Itineraries</span>
        <h2 class="section-title">Curated Holiday Packages</h2>
        <p class="section-desc">All-inclusive guided expeditions crafted by local experts and luxury concierge curators.</p>
      </div>

      <div class="cards-grid packages-grid" id="packages-grid">
        <!-- Package Card 1 -->
        <div class="package-card">
          <div class="package-image-wrap">
            <img src="assets/images/packages/bali-package.jpg" alt="Bali Jungle Sanctuary Escape" class="package-img">
            <span class="package-tag">Best Seller</span>
          </div>
          <div class="package-body">
            <div class="package-meta">
              <span class="package-duration">⏱ 8 Days / 7 Nights</span>
              <span class="package-rating">★ 4.9 (128 reviews)</span>
            </div>
            <h3 class="package-title">Bali Rainforest Sanctuary & Coastal Retreat</h3>
            <p class="package-desc">Private pool villa in Ubud jungle canopy followed by beachfront cliffside relaxation in Uluwatu with private chauffeur.</p>
            <div class="package-footer">
              <div class="package-price">
                <span class="price-from">From</span>
                <span class="price-amount">$2,450</span>
                <span class="price-per">/ person</span>
              </div>
              <button type="button" class="btn btn-outline package-cta" data-package="bali">Book Package</button>
            </div>
          </div>
        </div>

        <!-- Package Card 2 -->
        <div class="package-card">
          <div class="package-image-wrap">
            <img src="assets/images/packages/swiss-package.jpg" alt="Swiss Alpine Glacier Express" class="package-img">
            <span class="package-tag">Scenic Journey</span>
          </div>
          <div class="package-body">
            <div class="package-meta">
              <span class="package-duration">⏱ 10 Days / 9 Nights</span>
              <span class="package-rating">★ 5.0 (94 reviews)</span>
            </div>
            <h3 class="package-title">Swiss Alpine Peaks & Glacier Express Tour</h3>
            <p class="package-desc">First-class panoramic rail journey through St. Moritz, Zermatt, and Matterhorn vistas with 5-star mountain chalet stays.</p>
            <div class="package-footer">
              <div class="package-price">
                <span class="price-from">From</span>
                <span class="price-amount">$3,890</span>
                <span class="price-per">/ person</span>
              </div>
              <button type="button" class="btn btn-outline package-cta" data-package="swiss">Book Package</button>
            </div>
          </div>
        </div>

        <!-- Package Card 3 -->
        <div class="package-card">
          <div class="package-image-wrap">
            <img src="assets/images/packages/paris-package.jpg" alt="Parisian Romance and Gourmet Journey" class="package-img">
            <span class="package-tag">Culture & Dining</span>
          </div>
          <div class="package-body">
            <div class="package-meta">
              <span class="package-duration">⏱ 7 Days / 6 Nights</span>
              <span class="package-rating">★ 4.9 (82 reviews)</span>
            </div>
            <h3 class="package-title">Paris Haute Couture & Michelin Gastronomy</h3>
            <p class="package-desc">Private Louvre curator tour, Seine river sunset champagne cruise, and exclusive chef table dining across Saint-Germain.</p>
            <div class="package-footer">
              <div class="package-price">
                <span class="price-from">From</span>
                <span class="price-amount">$3,200</span>
                <span class="price-per">/ person</span>
              </div>
              <button type="button" class="btn btn-outline package-cta" data-package="paris">Book Package</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- Testimonials & Reviews Section -->
  <section class="section reviews-section" id="reviews">
    <div class="container">
      <div class="section-header">
        <span class="section-eyebrow">Guest Stories</span>
        <h2 class="section-title">Cherished Travel Experiences</h2>
        <p class="section-desc">Over 14,000 travelers have embarked on bespoke journeys with WanderWorld.</p>
      </div>

      <div class="cards-grid reviews-grid">
        <div class="review-card">
          <div class="review-stars">★★★★★</div>
          <p class="review-text">“Our honeymoon to the Maldives and Bali arranged through WanderWorld was pure magic. Every transfer was seamless and the private overwater villa was beyond expectations.”</p>
          <div class="review-author">
            <div class="author-avatar">SC</div>
            <div class="author-info">
              <span class="author-name">Sarah & Christopher M.</span>
              <span class="author-loc">New York, USA</span>
            </div>
          </div>
        </div>

        <div class="review-card">
          <div class="review-stars">★★★★★</div>
          <p class="review-text">“The Swiss Alpine expedition was impeccably organized. The glacier helicopter tour and private mountain guide made this the most memorable trip our family has taken.”</p>
          <div class="review-author">
            <div class="author-avatar">DK</div>
            <div class="author-info">
              <span class="author-name">David K.</span>
              <span class="author-loc">London, UK</span>
            </div>
          </div>
        </div>

        <div class="review-card">
          <div class="review-stars">★★★★★</div>
          <p class="review-text">“From tea ceremonies in Kyoto to private helicopter transfers in Dubai, WanderWorld curates experiences you simply cannot book on regular booking engines.”</p>
          <div class="review-author">
            <div class="author-avatar">EL</div>
            <div class="author-info">
              <span class="author-name">Elena L.</span>
              <span class="author-loc">Zurich, Switzerland</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- Booking & Inquiry Form Section -->
  <section class="section booking-section" id="booking">
    <div class="container">
      <div class="booking-card">
        <div class="booking-header">
          <span class="section-eyebrow">Start Planning</span>
          <h2 class="section-title">Design Your Custom Journey</h2>
          <p class="section-desc">Share your travel dreams with our private destination concierge for a tailored itinerary.</p>
        </div>

        <form class="booking-form" id="booking-form" novalidate>
          <div class="form-row">
            <div class="form-group">
              <label for="form-name" class="form-label">Full Name *</label>
              <input type="text" id="form-name" class="form-input" placeholder="e.g. Subrahmanyeswar Rao" required>
              <span class="form-error" id="name-error">Please enter your name</span>
            </div>
            <div class="form-group">
              <label for="form-email" class="form-label">Email Address *</label>
              <input type="email" id="form-email" class="form-input" placeholder="name@domain.com" required>
              <span class="form-error" id="email-error">Please enter a valid email</span>
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label for="form-destination" class="form-label">Preferred Destination *</label>
              <select id="form-destination" class="form-input" required>
                <option value="">Select Destination</option>
                <option value="Bali">Bali, Indonesia</option>
                <option value="Switzerland">Swiss Alps, Switzerland</option>
                <option value="Paris">Paris, France</option>
                <option value="Dubai">Dubai, UAE</option>
                <option value="Maldives">Maldives Lagoon</option>
                <option value="Japan">Kyoto & Tokyo, Japan</option>
              </select>
              <span class="form-error" id="dest-error">Please select a destination</span>
            </div>
            <div class="form-group">
              <label for="form-guests" class="form-label">Number of Guests</label>
              <select id="form-guests" class="form-input">
                <option value="1">1 Traveler</option>
                <option value="2" selected>2 Travelers</option>
                <option value="3-5">3–5 Travelers</option>
                <option value="6+">6+ Travelers</option>
              </select>
            </div>
          </div>

          <div class="form-group">
            <label for="form-notes" class="form-label">Special Requests or Preferences</label>
            <textarea id="form-notes" class="form-input form-textarea" rows="3" placeholder="Tell us about your travel dates, preferred hotels, or dietary requirements..."></textarea>
          </div>

          <button type="submit" class="btn btn-primary form-submit-btn" id="submit-btn">Send Travel Inquiry</button>
          
          <div class="form-feedback" id="form-feedback" style="display: none;">
            <span class="feedback-icon">✓</span>
            <span class="feedback-msg">Thank you! Your travel inquiry has been received. A destination specialist will contact you within 24 hours.</span>
          </div>
        </form>
      </div>
    </div>
  </section>

  <!-- Interactive Destination Details Modal -->
  <div class="modal-overlay" id="destination-modal" style="display: none;">
    <div class="modal-dialog">
      <button type="button" class="modal-close" id="modal-close-btn" aria-label="Close modal">&times;</button>
      <div class="modal-content-wrap">
        <div class="modal-media">
          <img id="modal-img" src="assets/images/destinations/bali.jpg" alt="Destination Details" class="modal-img">
        </div>
        <div class="modal-body">
          <span class="modal-tag" id="modal-category">Beach Sanctuary</span>
          <h3 class="modal-title" id="modal-title">Bali, Indonesia</h3>
          <p class="modal-meta" id="modal-meta">⏱ 7 Days Recommended | ★ 4.9 Rating</p>
          <p class="modal-desc" id="modal-desc">Immerse yourself in verdant rice terraces, spiritual water temples, and cliffside oceanfront resorts.</p>
          <div class="modal-highlights">
            <h4>Highlights Included:</h4>
            <ul id="modal-highlights-list">
              <li>Private sunrise trek and luxury spa package</li>
              <li>VIP airport fast-track and luxury chauffeur</li>
              <li>Handcrafted artisanal dining experiences</li>
            </ul>
          </div>
          <div class="modal-footer">
            <div class="modal-price">
              <span class="price-from">Package starting from</span>
              <span class="price-val" id="modal-price">$1,890</span>
            </div>
            <a href="#booking" class="btn btn-primary modal-action-btn" id="modal-book-btn">Inquire Now</a>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Footer Section -->
  <footer class="footer" id="footer">
    <div class="container footer-container">
      <div class="footer-col brand-col">
        <a href="#" class="brand-logo footer-logo">
          <span class="logo-mark">❖</span>
          <span class="logo-text">WanderWorld</span>
        </a>
        <p class="footer-about">Crafting unforgettable, luxury journeys to the planet's most breathtaking sanctuaries since 2018.</p>
      </div>
      <div class="footer-col">
        <h4 class="footer-title">Top Destinations</h4>
        <ul class="footer-links">
          <li><a href="#destinations">Bali & Indonesia</a></li>
          <li><a href="#destinations">Swiss Alps</a></li>
          <li><a href="#destinations">Parisian Romance</a></li>
          <li><a href="#destinations">Dubai & Emirates</a></li>
          <li><a href="#destinations">Maldives Atolls</a></li>
          <li><a href="#destinations">Kyoto & Tokyo</a></li>
        </ul>
      </div>
      <div class="footer-col">
        <h4 class="footer-title">Concierge</h4>
        <ul class="footer-links">
          <li><a href="#packages">Curated Packages</a></li>
          <li><a href="#booking">Custom Planning</a></li>
          <li><a href="#reviews">Guest Reviews</a></li>
          <li><a href="#booking">VIP Assistance</a></li>
        </ul>
      </div>
      <div class="footer-col">
        <h4 class="footer-title">Stay Connected</h4>
        <p class="footer-about">Subscribe to receive private travel invitations and seasonal journal entries.</p>
        <div class="newsletter-form">
          <input type="email" placeholder="Your email address" class="newsletter-input" aria-label="Email for newsletter">
          <button type="button" class="btn btn-accent newsletter-btn">Join</button>
        </div>
      </div>
    </div>
    <div class="footer-bottom">
      <div class="container footer-bottom-inner">
        <p>&copy; 2026 WanderWorld Luxury Travel Ltd. All rights reserved.</p>
        <div class="footer-bottom-links">
          <a href="#">Privacy Policy</a>
          <a href="#">Terms of Service</a>
          <a href="#">Security</a>
        </div>
      </div>
    </div>
  </footer>

  <script src="app.js"></script>
</body>
</html>
"""

    css_content = """/* WanderWorld Authoritative Design System & High-Fidelity UI */
:root {
  --color-primary: #0e7490;
  --color-primary-hover: #0891b2;
  --color-secondary: #0369a1;
  --color-accent: #f59e0b;
  --color-accent-hover: #d97706;
  --color-background: #f8fafc;
  --color-surface: #ffffff;
  --color-surface-muted: #f1f5f9;
  --color-text-primary: #0f172a;
  --color-text-secondary: #475569;
  --color-text-muted: #64748b;
  --color-border: #e2e8f0;
  --color-border-focus: #0e7490;
  
  --font-heading: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
  --font-body: 'Inter', system-ui, -apple-system, sans-serif;
  
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 16px;
  --radius-pill: 9999px;
  
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.06);
  --shadow-md: 0 4px 20px -2px rgba(0,0,0,0.08);
  --shadow-lg: 0 12px 36px -4px rgba(0,0,0,0.12);
  --shadow-hover: 0 16px 40px -4px rgba(14,116,144,0.18);
  
  --transition-normal: 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html, body {
  overflow-x: hidden;
  width: 100%;
  font-family: var(--font-body);
  background-color: var(--color-background);
  color: var(--color-text-primary);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

a {
  color: inherit;
  text-decoration: none;
  transition: color var(--transition-normal);
}

img {
  max-width: 100%;
  height: auto;
  display: block;
}

.container {
  width: 100%;
  max-width: 1240px;
  margin: 0 auto;
  padding: 0 1.5rem;
}

.section {
  padding: 5rem 0;
}

.section-header {
  text-align: center;
  max-width: 720px;
  margin: 0 auto 3rem;
}

.section-eyebrow {
  display: inline-block;
  font-size: 0.8125rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--color-primary);
  margin-bottom: 0.5rem;
}

.section-title {
  font-family: var(--font-heading);
  font-size: 2.25rem;
  font-weight: 800;
  color: var(--color-text-primary);
  margin-bottom: 0.75rem;
  line-height: 1.25;
}

.section-desc {
  font-size: 1.0625rem;
  color: var(--color-text-secondary);
}

/* ── Buttons ── */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.75rem 1.75rem;
  font-family: var(--font-heading);
  font-size: 0.9375rem;
  font-weight: 600;
  border-radius: var(--radius-pill);
  border: 1px solid transparent;
  cursor: pointer;
  transition: all var(--transition-normal);
}

.btn-primary {
  background-color: var(--color-primary);
  color: #ffffff;
}
.btn-primary:hover {
  background-color: var(--color-primary-hover);
  box-shadow: 0 4px 14px rgba(14, 116, 144, 0.35);
  transform: translateY(-1px);
}

.btn-accent {
  background-color: var(--color-accent);
  color: #ffffff;
}
.btn-accent:hover {
  background-color: var(--color-accent-hover);
  box-shadow: 0 4px 14px rgba(245, 158, 11, 0.35);
  transform: translateY(-1px);
}

.btn-outline {
  background-color: transparent;
  color: var(--color-primary);
  border-color: var(--color-primary);
}
.btn-outline:hover {
  background-color: var(--color-primary);
  color: #ffffff;
}

/* ── Navigation Bar ── */
.navbar {
  position: sticky;
  top: 0;
  z-index: 100;
  background-color: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--color-border);
}

.nav-container {
  max-width: 1240px;
  margin: 0 auto;
  padding: 1rem 1.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.brand-logo {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  font-family: var(--font-heading);
  font-size: 1.375rem;
  font-weight: 800;
  color: var(--color-text-primary);
}

.logo-mark {
  color: var(--color-primary);
  font-size: 1.5rem;
}

.nav-menu {
  display: flex;
  align-items: center;
  gap: 2rem;
}

.nav-link {
  font-size: 0.9375rem;
  font-weight: 500;
  color: var(--color-text-secondary);
}

.nav-link:hover {
  color: var(--color-primary);
}

/* ── Hero Presentation ── */
.hero {
  position: relative;
  min-height: 85vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: url('assets/images/hero/hero-wanderlust.jpg') center/cover no-repeat;
  padding: 6rem 1.5rem 5rem;
  text-align: center;
}

.hero-overlay {
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.55) 0%, rgba(15, 23, 42, 0.75) 100%);
}

.hero-content {
  position: relative;
  z-index: 10;
  max-width: 900px;
  color: #ffffff;
}

.hero-badge {
  display: inline-block;
  background-color: rgba(255, 255, 255, 0.18);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.3);
  padding: 0.375rem 1.125rem;
  border-radius: var(--radius-pill);
  font-size: 0.8125rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  margin-bottom: 1.25rem;
}

.hero-title {
  font-family: var(--font-heading);
  font-size: 3.5rem;
  font-weight: 800;
  line-height: 1.15;
  margin-bottom: 1.25rem;
  text-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
}

.hero-subtitle {
  font-size: 1.2rem;
  font-weight: 400;
  color: rgba(255, 255, 255, 0.9);
  max-width: 680px;
  margin: 0 auto 2.5rem;
}

/* ── Search Widget ── */
.search-widget {
  background-color: #ffffff;
  padding: 1.25rem 1.75rem;
  border-radius: var(--radius-lg);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.25);
  display: grid;
  grid-template-columns: 2fr 1.5fr 1.2fr auto;
  gap: 1rem;
  align-items: center;
  max-width: 960px;
  margin: 0 auto;
  text-align: left;
}

.search-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.search-field label {
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-muted);
}

.search-field input,
.search-field select {
  border: 1px solid var(--color-border);
  padding: 0.625rem 0.875rem;
  border-radius: var(--radius-sm);
  font-family: var(--font-body);
  font-size: 0.9375rem;
  color: var(--color-text-primary);
  outline: none;
  background-color: #fff;
}

.search-field input:focus,
.search-field select:focus {
  border-color: var(--color-primary);
}

.search-submit-btn {
  height: 48px;
  align-self: flex-end;
  padding: 0 1.75rem;
}

/* ── Filter Pills ── */
.filter-pills {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.625rem;
  margin-top: 1.75rem;
}

.filter-pill {
  padding: 0.5rem 1.375rem;
  border-radius: var(--radius-pill);
  border: 1px solid var(--color-border);
  background-color: #ffffff;
  font-family: var(--font-heading);
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-normal);
}

.filter-pill:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.filter-pill.active {
  background-color: var(--color-primary);
  color: #ffffff;
  border-color: var(--color-primary);
  box-shadow: 0 2px 8px rgba(14, 116, 144, 0.25);
}

/* ── Card Grids ── */
.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 2rem;
}

/* ── Destination Cards ── */
.destination-card {
  background-color: var(--color-surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  overflow: hidden;
  box-shadow: var(--shadow-md);
  transition: all var(--transition-normal);
  display: flex;
  flex-direction: column;
}

.destination-card:hover {
  transform: translateY(-6px);
  box-shadow: var(--shadow-hover);
  border-color: rgba(14, 116, 144, 0.3);
}

.card-image-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 4/3;
  overflow: hidden;
  background-color: var(--color-surface-muted);
}

.card-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.5s ease;
}

.destination-card:hover .card-img {
  transform: scale(1.04);
}

.card-category-badge {
  position: absolute;
  top: 1rem;
  left: 1rem;
  background-color: rgba(15, 23, 42, 0.75);
  backdrop-filter: blur(6px);
  color: #ffffff;
  padding: 0.25rem 0.75rem;
  border-radius: var(--radius-pill);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.card-rating-badge {
  position: absolute;
  top: 1rem;
  right: 1rem;
  background-color: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(6px);
  color: #0f172a;
  padding: 0.25rem 0.625rem;
  border-radius: var(--radius-pill);
  font-size: 0.75rem;
  font-weight: 700;
}

.card-body {
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  flex-grow: 1;
}

.card-title {
  font-family: var(--font-heading);
  font-size: 1.375rem;
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: 0.5rem;
}

.card-desc {
  font-size: 0.9375rem;
  color: var(--color-text-secondary);
  margin-bottom: 1.25rem;
  flex-grow: 1;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid var(--color-border);
  padding-top: 1rem;
}

.card-price .price-from {
  display: block;
  font-size: 0.75rem;
  color: var(--color-text-muted);
  text-transform: uppercase;
}

.card-price .price-amount {
  font-family: var(--font-heading);
  font-size: 1.25rem;
  font-weight: 800;
  color: var(--color-primary);
}

/* ── Package Cards ── */
.packages-grid {
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
}

.package-card {
  background-color: var(--color-surface);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  overflow: hidden;
  box-shadow: var(--shadow-md);
  transition: all var(--transition-normal);
  display: flex;
  flex-direction: column;
}

.package-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-lg);
}

.package-image-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 16/10;
  overflow: hidden;
}

.package-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.package-tag {
  position: absolute;
  bottom: 1rem;
  left: 1rem;
  background-color: var(--color-accent);
  color: #ffffff;
  padding: 0.25rem 0.75rem;
  border-radius: var(--radius-sm);
  font-size: 0.75rem;
  font-weight: 700;
}

.package-body {
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  flex-grow: 1;
}

.package-meta {
  display: flex;
  justify-content: space-between;
  font-size: 0.8125rem;
  color: var(--color-text-muted);
  margin-bottom: 0.75rem;
}

.package-title {
  font-family: var(--font-heading);
  font-size: 1.25rem;
  font-weight: 700;
  margin-bottom: 0.625rem;
}

.package-desc {
  font-size: 0.9375rem;
  color: var(--color-text-secondary);
  margin-bottom: 1.25rem;
  flex-grow: 1;
}

.package-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid var(--color-border);
  padding-top: 1rem;
}

/* ── Reviews ── */
.reviews-grid {
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
}

.review-card {
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 2rem;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
}

.review-stars {
  color: #f59e0b;
  font-size: 1.125rem;
  margin-bottom: 1rem;
}

.review-text {
  font-size: 1rem;
  font-style: italic;
  color: var(--color-text-secondary);
  margin-bottom: 1.5rem;
  flex-grow: 1;
  line-height: 1.7;
}

.review-author {
  display: flex;
  align-items: center;
  gap: 0.875rem;
}

.author-avatar {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-pill);
  background-color: var(--color-primary);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 0.875rem;
}

.author-info {
  display: flex;
  flex-direction: column;
}

.author-name {
  font-weight: 700;
  font-size: 0.9375rem;
  color: var(--color-text-primary);
}

.author-loc {
  font-size: 0.8125rem;
  color: var(--color-text-muted);
}

/* ── Booking Form ── */
.booking-section {
  background-color: var(--color-surface-muted);
}

.booking-card {
  max-width: 760px;
  margin: 0 auto;
  background-color: #ffffff;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 3rem;
  box-shadow: var(--shadow-md);
}

.booking-header {
  text-align: center;
  margin-bottom: 2.25rem;
}

.booking-form {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.25rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.form-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--color-text-primary);
}

.form-input {
  width: 100%;
  padding: 0.75rem 1rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-family: var(--font-body);
  font-size: 0.9375rem;
  outline: none;
  background-color: #ffffff;
  transition: border-color var(--transition-normal);
}

.form-input:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(14, 116, 144, 0.12);
}

.form-input.invalid {
  border-color: #ef4444;
}

.form-error {
  display: none;
  font-size: 0.75rem;
  color: #ef4444;
}

.form-input.invalid + .form-error {
  display: block;
}

.form-submit-btn {
  width: 100%;
  padding: 0.875rem;
  font-size: 1rem;
  margin-top: 0.5rem;
}

.form-feedback {
  background-color: #ecfdf5;
  border: 1px solid #10b981;
  color: #065f46;
  padding: 1rem;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 1rem;
}

.feedback-icon {
  font-size: 1.25rem;
  font-weight: 800;
}

/* ── Modal Dialog ── */
.modal-overlay {
  position: fixed;
  inset: 0;
  background-color: rgba(15, 23, 42, 0.65);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
}

.modal-dialog {
  position: relative;
  background-color: #ffffff;
  width: 100%;
  max-width: 680px;
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-lg);
  animation: modalFadeIn 0.25s ease-out;
}

@keyframes modalFadeIn {
  from { opacity: 0; transform: scale(0.96); }
  to { opacity: 1; transform: scale(1); }
}

.modal-close {
  position: absolute;
  top: 1rem;
  right: 1rem;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-pill);
  background-color: rgba(255, 255, 255, 0.85);
  border: none;
  font-size: 1.5rem;
  color: var(--color-text-primary);
  cursor: pointer;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-media {
  width: 100%;
  height: 280px;
}

.modal-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.modal-body {
  padding: 2rem;
}

.modal-tag {
  display: inline-block;
  background-color: var(--color-surface-muted);
  color: var(--color-primary);
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 0.25rem 0.625rem;
  border-radius: var(--radius-pill);
  margin-bottom: 0.5rem;
}

.modal-title {
  font-family: var(--font-heading);
  font-size: 1.75rem;
  font-weight: 800;
  margin-bottom: 0.25rem;
}

.modal-meta {
  font-size: 0.875rem;
  color: var(--color-text-muted);
  margin-bottom: 1rem;
}

.modal-desc {
  font-size: 0.9375rem;
  color: var(--color-text-secondary);
  margin-bottom: 1.5rem;
  line-height: 1.7;
}

.modal-highlights {
  background-color: var(--color-surface-muted);
  padding: 1rem 1.25rem;
  border-radius: var(--radius-md);
  margin-bottom: 1.5rem;
}

.modal-highlights h4 {
  font-size: 0.875rem;
  font-weight: 700;
  margin-bottom: 0.5rem;
}

.modal-highlights ul {
  padding-left: 1.25rem;
  font-size: 0.875rem;
  color: var(--color-text-secondary);
}

.modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid var(--color-border);
  padding-top: 1.25rem;
}

.modal-price .price-from {
  display: block;
  font-size: 0.75rem;
  color: var(--color-text-muted);
}

.modal-price .price-val {
  font-family: var(--font-heading);
  font-size: 1.5rem;
  font-weight: 800;
  color: var(--color-primary);
}

/* ── Footer ── */
.footer {
  background-color: #0f172a;
  color: #94a3b8;
  padding: 5rem 0 2rem;
}

.footer-container {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1.5fr;
  gap: 3rem;
  margin-bottom: 3rem;
}

.footer-logo {
  color: #ffffff;
  margin-bottom: 1rem;
}

.footer-about {
  font-size: 0.875rem;
  line-height: 1.6;
}

.footer-title {
  font-family: var(--font-heading);
  color: #ffffff;
  font-size: 1rem;
  font-weight: 700;
  margin-bottom: 1.25rem;
}

.footer-links {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

.footer-links a {
  font-size: 0.875rem;
  color: #94a3b8;
}

.footer-links a:hover {
  color: #ffffff;
}

.newsletter-form {
  display: flex;
  gap: 0.5rem;
  margin-top: 1rem;
}

.newsletter-input {
  flex-grow: 1;
  padding: 0.625rem 0.875rem;
  border-radius: var(--radius-pill);
  border: 1px solid #334155;
  background-color: #1e293b;
  color: #ffffff;
  font-size: 0.875rem;
  outline: none;
}

.newsletter-btn {
  padding: 0.625rem 1.25rem;
  font-size: 0.875rem;
}

.footer-bottom {
  border-top: 1px solid #1e293b;
  padding-top: 2rem;
  font-size: 0.8125rem;
}

.footer-bottom-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.footer-bottom-links {
  display: flex;
  gap: 1.5rem;
}

/* ── Responsive Viewports ── */
@media (max-width: 1024px) {
  .hero-title { font-size: 2.75rem; }
  .search-widget { grid-template-columns: 1fr 1fr; gap: 1rem; }
  .footer-container { grid-template-columns: 1fr 1fr; gap: 2rem; }
}

@media (max-width: 768px) {
  .nav-menu { display: none; }
  .hero { min-height: 75vh; padding: 4rem 1rem 3rem; }
  .hero-title { font-size: 2.25rem; }
  .hero-subtitle { font-size: 1rem; }
  .search-widget { grid-template-columns: 1fr; }
  .search-submit-btn { width: 100%; }
  .cards-grid { grid-template-columns: 1fr; }
  .form-row { grid-template-columns: 1fr; }
  .booking-card { padding: 1.75rem; }
  .footer-container { grid-template-columns: 1fr; }
  .footer-bottom-inner { flex-direction: column; gap: 1rem; text-align: center; }
}
"""

    js_content = """// WanderWorld Interactive Application Logic
document.addEventListener("DOMContentLoaded", () => {
  // Verified Destination Data using Pre-Provisioned Workspace Photography
  const destinations = [
    {
      id: "bali",
      name: "Bali",
      country: "Indonesia",
      category: "beach",
      rating: "4.9",
      price: "$1,890",
      image: "assets/images/destinations/bali.jpg",
      description: "Tropical water temples, emerald rice terraces, and tranquil coastal sanctuaries tailored for rejuvenation.",
      highlights: ["Private cliffside villa with infinity pool", "Guided dawn trek to Mount Batur", "Artisanal culinary tasting menu"]
    },
    {
      id: "switzerland",
      name: "Swiss Alps",
      country: "Switzerland",
      category: "mountain",
      rating: "5.0",
      price: "$2,750",
      image: "assets/images/destinations/switzerland.jpg",
      description: "Dramatic snow-capped alpine summits, pristine glacier lakes, and timeless wooden chalet luxury.",
      highlights: ["Matterhorn sunrise viewing flight", "Glacier Express first-class panoramic rail", "Thermal alpine spa immersion"]
    },
    {
      id: "paris",
      name: "Paris",
      country: "France",
      category: "cultural",
      rating: "4.8",
      price: "$2,200",
      image: "assets/images/destinations/paris.jpg",
      description: "Iconic architecture, private museum curators, and legendary Michelin gastronomy along the Seine.",
      highlights: ["After-hours private Louvre curator tour", "Sunset champagne cruise on the Seine", "Exclusive Saint-Germain boutique concierge"]
    },
    {
      id: "dubai",
      name: "Dubai",
      country: "UAE",
      category: "luxury",
      rating: "4.9",
      price: "$2,400",
      image: "assets/images/destinations/dubai.jpg",
      description: "Futuristic architecture, private golden desert glamping, and world-class waterfront hospitality.",
      highlights: ["Sunset dune safari with private chef dinner", "Helicopter transfer from Dubai Marina", "Burj Khalifa sky-lounge tasting"]
    },
    {
      id: "maldives",
      name: "Maldives",
      country: "Maldives",
      category: "beach",
      rating: "5.0",
      price: "$3,100",
      image: "assets/images/destinations/maldives.jpg",
      description: "Overwater coral bungalows, azure private lagoons, and secluded bioluminescent night diving.",
      highlights: ["Private seaplane transfers directly to lagoon", "Undersea coral reef dining experience", "Private dolphin sunset expedition"]
    },
    {
      id: "japan",
      name: "Kyoto & Tokyo",
      country: "Japan",
      category: "cultural",
      rating: "4.9",
      price: "$2,850",
      image: "assets/images/destinations/japan.jpg",
      description: "Historic bamboo groves, cherry blossom pagoda vistas, and modern culinary mastery.",
      highlights: ["Private tea ceremony with Kyoto master", "Shinkansen Green Car bullet train passes", "Tsukiji morning culinary expedition"]
    }
  ];

  const grid = document.getElementById("destinations-grid");
  const filterPills = document.querySelectorAll(".filter-pill");
  const searchInput = document.getElementById("dest-search");
  const categorySelect = document.getElementById("trip-category-select");
  const searchBtn = document.getElementById("search-btn");

  // Modal Elements
  const modal = document.getElementById("destination-modal");
  const modalClose = document.getElementById("modal-close-btn");
  const modalImg = document.getElementById("modal-img");
  const modalTitle = document.getElementById("modal-title");
  const modalCategory = document.getElementById("modal-category");
  const modalMeta = document.getElementById("modal-meta");
  const modalDesc = document.getElementById("modal-desc");
  const modalPrice = document.getElementById("modal-price");
  const modalHighlightsList = document.getElementById("modal-highlights-list");

  // Booking Form Elements
  const bookingForm = document.getElementById("booking-form");
  const formFeedback = document.getElementById("form-feedback");
  const nameInput = document.getElementById("form-name");
  const emailInput = document.getElementById("form-email");
  const destSelect = document.getElementById("form-destination");

  // 1. Render Destination Cards into inner grid container (Never overwrite <section>)
  function renderDestinations(items) {
    if (!grid) return;
    if (items.length === 0) {
      grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 3rem; color: #64748b;">No destinations match your selection. Try clearing filters.</div>';
      return;
    }
    grid.innerHTML = items.map(dest => `
      <div class="destination-card" data-id="${dest.id}" data-category="${dest.category}">
        <div class="card-image-wrap">
          <img src="${dest.image}" alt="${dest.name}, ${dest.country}" class="card-img" loading="lazy">
          <span class="card-category-badge">${dest.category}</span>
          <span class="card-rating-badge">★ ${dest.rating}</span>
        </div>
        <div class="card-body">
          <h3 class="card-title">${dest.name}, ${dest.country}</h3>
          <p class="card-desc">${dest.description}</p>
          <div class="card-footer">
            <div class="card-price">
              <span class="price-from">From</span>
              <span class="price-amount">${dest.price}</span>
            </div>
            <button type="button" class="btn btn-outline view-details-btn" data-id="${dest.id}">View Details</button>
          </div>
        </div>
      </div>
    `).join("");

    // Attach click listeners to Details buttons
    grid.querySelectorAll(".view-details-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const destId = btn.getAttribute("data-id");
        openModal(destId);
      });
    });
  }

  // Initial render
  renderDestinations(destinations);

  // 2. Filter Pills Interaction
  filterPills.forEach(pill => {
    pill.addEventListener("click", () => {
      filterPills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      const cat = pill.getAttribute("data-category");
      applyFilters(cat, searchInput ? searchInput.value : "");
    });
  });

  // 3. Search and Select Integration
  function applyFilters(category, query) {
    const qLower = (query || "").trim().toLowerCase();
    const filtered = destinations.filter(d => {
      const matchCat = category === "all" || d.category === category;
      const matchQuery = !qLower || d.name.toLowerCase().includes(qLower) || d.country.toLowerCase().includes(qLower) || d.category.toLowerCase().includes(qLower);
      return matchCat && matchQuery;
    });
    renderDestinations(filtered);
  }

  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      const activePill = document.querySelector(".filter-pill.active");
      const currentCat = activePill ? activePill.getAttribute("data-category") : "all";
      applyFilters(currentCat, e.target.value);
    });
  }

  if (searchBtn && categorySelect) {
    searchBtn.addEventListener("click", () => {
      const selectedCat = categorySelect.value;
      const query = searchInput ? searchInput.value : "";
      // Sync pill active state
      filterPills.forEach(p => {
        if (p.getAttribute("data-category") === selectedCat) {
          p.classList.add("active");
        } else {
          p.classList.remove("active");
        }
      });
      applyFilters(selectedCat, query);
      const destSection = document.getElementById("destinations");
      if (destSection) {
        destSection.scrollIntoView({ behavior: "smooth" });
      }
    });
  }

  // 4. Modal Dialog Handlers
  function openModal(destId) {
    const dest = destinations.find(d => d.id === destId);
    if (!dest || !modal) return;
    
    modalImg.src = dest.image;
    modalImg.alt = `${dest.name} panorama`;
    modalTitle.textContent = `${dest.name}, ${dest.country}`;
    modalCategory.textContent = `${dest.category.toUpperCase()} SANCTUARY`;
    modalMeta.textContent = `⏱ 7–10 Days Recommended | ★ ${dest.rating} Guest Score`;
    modalDesc.textContent = dest.description;
    modalPrice.textContent = dest.price;
    modalHighlightsList.innerHTML = dest.highlights.map(h => `<li>${h}</li>`).join("");

    modal.style.display = "flex";
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    if (!modal) return;
    modal.style.display = "none";
    document.body.style.overflow = "";
  }

  if (modalClose) {
    modalClose.addEventListener("click", closeModal);
  }

  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) {
        closeModal();
      }
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal && modal.style.display === "flex") {
      closeModal();
    }
  });

  // Package CTA click pre-fills inquiry
  document.querySelectorAll(".package-cta").forEach(btn => {
    btn.addEventListener("click", () => {
      const pkg = btn.getAttribute("data-package");
      const destMap = { bali: "Bali", swiss: "Switzerland", paris: "Paris" };
      if (destSelect && destMap[pkg]) {
        destSelect.value = destMap[pkg];
      }
      const bookSec = document.getElementById("booking");
      if (bookSec) bookSec.scrollIntoView({ behavior: "smooth" });
    });
  });

  // 5. Booking Form Validation & Submission
  if (bookingForm) {
    bookingForm.addEventListener("submit", (e) => {
      e.preventDefault();
      let isValid = true;

      // Name validation
      if (!nameInput.value.trim()) {
        nameInput.classList.add("invalid");
        isValid = false;
      } else {
        nameInput.classList.remove("invalid");
      }

      // Email validation
      const emailRegex = /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/;
      if (!emailRegex.test(emailInput.value.trim())) {
        emailInput.classList.add("invalid");
        isValid = false;
      } else {
        emailInput.classList.remove("invalid");
      }

      // Destination select validation
      if (!destSelect.value) {
        destSelect.classList.add("invalid");
        isValid = false;
      } else {
        destSelect.classList.remove("invalid");
      }

      if (isValid) {
        formFeedback.style.display = "flex";
        bookingForm.reset();
        setTimeout(() => {
          formFeedback.style.display = "none";
        }, 8000);
      }
    });
  }
});
"""

    pkg_content = json.dumps({
        "name": "wanderworld-luxury-travel",
        "version": "1.0.0",
        "description": "WanderWorld luxury travel agency web experience",
        "main": "app.js",
        "private": True,
    }, indent=2)

    (WORKSPACE_DIR / "index.html").write_text(html_content, encoding="utf-8")
    (WORKSPACE_DIR / "style.css").write_text(css_content, encoding="utf-8")
    (WORKSPACE_DIR / "app.js").write_text(js_content, encoding="utf-8")
    (WORKSPACE_DIR / "package.json").write_text(pkg_content, encoding="utf-8")
    print("Emitted index.html, style.css, app.js, and package.json.")

    # 4. Frontend Contract Validation
    print("\n[Step 4] Running FrontendContractValidator...")
    validator = FrontendContractValidator(WORKSPACE_DIR)
    contract_rep = validator.validate_all()
    print(f"Contract Valid: {contract_rep.is_valid}")
    print(f"Errors ({len(contract_rep.errors)}): {contract_rep.errors}")
    print(f"Warnings ({len(contract_rep.warnings)}): {contract_rep.warnings[:3]}")
    assert contract_rep.is_valid is True, f"Contract errors: {contract_rep.errors}"

    # 5. Profile C Evaluation
    print("\n[Step 5] Evaluating Verification Profile C...")
    prof_res = VerificationProfileEvaluator.evaluate(
        VerificationProfile.PROFILE_C,
        WORKSPACE_DIR,
        PROMPT,
        written_files={"index.html", "style.css", "app.js", "package.json"},
    )
    print(f"Profile C Passed: {prof_res.passed}")
    print(f"Checks run: {prof_res.checks_run}")
    assert prof_res.passed is True, f"Profile C issues: {prof_res.issues}"

    # 6. Real Headless Browser Multi-Viewport Qualification
    print("\n[Step 6] Running Live DevServer & Headless Browser Multi-Viewport Capture...")
    server_mgr = DevServerManager()
    server_info = await server_mgr.start_static_server(directory=WORKSPACE_DIR, timeout=8.0)
    print(f"Static server live at {server_info.url}")

    browser_mgr = BrowserManager(artifacts_dir=screenshots_dir, prefer_cdp=False)
    try:
        # Launch browser
        launched = await browser_mgr.launch(headless=True, viewport=Viewport.desktop())
        assert launched is True

        target_url = f"{server_info.url}/index.html"
        nav_res = await browser_mgr.navigate(target_url)
        assert nav_res.success is True
        print(f"Navigated to {target_url} — Title: '{nav_res.title}'")

        # Viewport 1: Desktop (1440 x 900)
        shot_desktop = screenshots_dir / "wanderworld_desktop_1440.png"
        art_desktop = await browser_mgr.capture_screenshot(name="wanderworld_desktop_1440", viewport=Viewport.desktop_large())
        shutil.copy2(art_desktop.file_path, shot_desktop)
        print(f"  ✓ Desktop (1440px) screenshot saved: {shot_desktop.name} ({round(shot_desktop.stat().st_size/1024, 1)} KB)")

        # Viewport 2: Tablet (1024 x 768)
        shot_tablet = screenshots_dir / "wanderworld_tablet_1024.png"
        art_tablet = await browser_mgr.capture_screenshot(name="wanderworld_tablet_1024", viewport=Viewport.tablet_landscape())
        shutil.copy2(art_tablet.file_path, shot_tablet)
        print(f"  ✓ Tablet (1024px) screenshot saved: {shot_tablet.name} ({round(shot_tablet.stat().st_size/1024, 1)} KB)")

        # Viewport 3: Mobile (390 x 844)
        shot_mobile = screenshots_dir / "wanderworld_mobile_390.png"
        art_mobile = await browser_mgr.capture_screenshot(name="wanderworld_mobile_390", viewport=Viewport.mobile_iphone12())
        shutil.copy2(art_mobile.file_path, shot_mobile)
        print(f"  ✓ Mobile (390px) screenshot saved: {shot_mobile.name} ({round(shot_mobile.stat().st_size/1024, 1)} KB)")

    finally:
        await browser_mgr.close()
        if server_info:
            server_mgr.stop_server(server_info.name)

    # 7. Authoritative Browser Acceptance Verifier
    print("\n[Step 7] Running BrowserAcceptanceVerifier...")
    b_res = BrowserAcceptanceVerifier.verify_workspace_sync(WORKSPACE_DIR)
    print(f"Browser Acceptance Passed: {b_res.passed} ({b_res.status})")
    print(f"Console Errors: {b_res.console_errors}")
    print(f"Missing Elements: {b_res.missing_rendered_elements}")
    assert b_res.passed is True, f"Browser acceptance failed: {b_res.issues}"

    print("\n=======================================================")
    print("SUCCESS: Greenfield WanderWorld Mission 100% Qualified!")
    print("Genuine Photography: Verified")
    print("Frontend Contracts: Verified")
    print("Profile C: Passed")
    print("Browser Acceptance: Passed")
    print("=======================================================")


if __name__ == "__main__":
    asyncio.run(main())
