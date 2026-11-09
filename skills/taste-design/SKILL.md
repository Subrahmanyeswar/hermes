---
name: taste-design
description: "Interpret design briefs, audience context, and brand character to formulate intentional, distinctive visual directions rather than generic templates."
triggers:
  - "taste design"
  - "design brief"
  - "editorial design"
  - "distinctive aesthetic"
  - "brand mood"
  - "visual direction"
  - "creative direction"
priority: 2
allowed-tools:
  - "fs.read"
  - "fs.write"
  - "fs.edit"
---

# Taste Design & Creative Direction

Formulate intentional, audience-appropriate visual directions from project briefs, brand signals, and context. Design interfaces that feel tailored to their domain, purpose, and users rather than generated from interchangeable AI templates.

## 1. The Brief-First Principle

Before selecting fonts, colors, or layouts, extract and document the design context:
1. **Domain & Audience:**
   - Who is using this product? (e.g., enterprise data analysts, boutique coffee shop patrons, indie developers, healthcare clinicians).
   - What emotional tone is expected? (e.g., utilitarian and dense, warm and artisanal, technical and precise, bold and editorial).
2. **Context & Density:**
   - Analytical/pro tools demand high information density, compact typography, neutral palettes, and minimal decorative flourish.
   - Editorial, consumer, or brand storytelling demands expressive typography, generous whitespace, visual hierarchy, and tactile accents.
3. **Existing Signals:**
   - Inspect existing logos, brand colors, images, and copy in the workspace using `fs.read`. Align with what already exists rather than imposing an external aesthetic.

## 2. Guardrails Against Generic Template Tropes

Recognize and actively avoid standard automated design clichés:
- **The Purple/Indigo Gradient Trap:** Do not default to deep indigo/purple gradient backgrounds for every technology product. Select colors rooted in the product's actual domain (e.g., slate, moss, warm terracotta, cobalt, deep copper).
- **The Centered Hero Formula:** Do not automatically create a centered H1 + subtitle + two pill buttons on every landing page. Consider split-screen, asymmetrical, editorial header, or product-first layouts when appropriate to the content.
- **The Three-Card Feature Grid:** Do not default to exactly three cards with generic lucide icons for product features. Use dynamic layouts, comparative lists, interactive walkthroughs, or typography-led callouts.
- **Universal Glassmorphism:** Avoid gratuitous `backdrop-blur` and semi-transparent borders on every container unless the design language specifically calls for layered physical glass.
- **Boxed Hero Overlay Bands:** Prohibit narrow or partial-height translucent gradient bands (.hero-overlay with relative positioning and padding). Hero overlays MUST be full-bleed (position: absolute; inset: 0; z-index: 1; pointer-events: none;) over the entire hero container, with content positioned at position: relative; z-index: 2;.
- **Raw Text Mobile Menu Controls:** Prohibit raw unstyled 'Menu' text on mobile navigation headers. Use a compact styled hamburger icon (3 bars or SVG, 44–48px touch target) with aria-label="Toggle navigation" and aria-expanded="false".
- **Gratuitous Animation:** Do not add entrance animations, spinning badges, or bouncy hover states that slow down interaction or distract from content.

## 3. Defining a Coherent Direction

When establishing a visual direction, articulate four concrete decisions:
1. **Typography Voice:**
   - Pair a distinctive display/heading typeface with an ultra-readable body font (e.g., high-contrast serif for editorial craft; clean geometric sans for modern fintech; tabular monospace accents for data interfaces).
2. **Color Palette with Semantic Roles:**
   - 1 dominant background neutral (warm paper, deep ink, clean slate).
   - 1 high-contrast text color.
   - 1 functional accent color with high intention (used sparingly for primary actions and active selections).
   - Muted border/divider colors with subtle contrast (8–12% opacity).
3. **Surface & Texture Strategy:**
   - Flat with crisp borders, subtle elevation with soft shadows, or warm tactile layering.
4. **Information Density:**
   - Compact (8px spacing grid, small padding, tabular data).
   - Relaxed/Editorial (16px–32px spacing grid, generous leading, breathing room).

## 4. Resolving Ambiguity

- If the user provides a brief with a single critical ambiguity that would fundamentally invert the design direction (e.g., B2B enterprise dashboard vs B2C marketing page), ask **at most one** clarifying question.
- Otherwise, make a reasonable, documented interpretation based on available signals, explain the rationale, and proceed directly to implementation.
