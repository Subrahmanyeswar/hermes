---
name: design-engineering
description: "Translate product briefs and UI designs into polished, responsive, accessible, and maintainable frontend implementations."
triggers:
  - "design engineering"
  - "frontend design"
  - "polished frontend"
  - "ui engineering"
  - "product design implementation"
  - "visual direction implementation"
priority: 2
allowed-tools:
  - "fs.read"
  - "fs.write"
  - "fs.edit"
  - "search.glob"
  - "shell.bash"
  - "browser.navigate"
  - "browser.screenshot"
  - "browser.inspect"
---

# Design Engineering

Bridge the gap between design vision and production-grade engineering. Translate product requirements, briefs, and mockups into polished, responsive, and accessible user interfaces while maintaining rigorous code quality.

## 1. Understand Context & Constraints First

Before writing or editing code:
1. **Clarify User Intent & Hierarchy:**
   - Identify the primary user action on the screen (the "one thing" the user came to accomplish).
   - Establish secondary and tertiary actions; ensure visual weight correlates directly with task priority.
2. **Inspect Existing UI Conventions:**
   - Use `fs.read` and `search.glob` to inspect existing stylesheets, theme tokens, typography scales, and component libraries.
   - Respect established component conventions rather than inventing a competing design language.
3. **Respect Scope:**
   - When asked for a localized fix or component refinement, do not redesign the surrounding application or rewrite global styles.

## 2. Intentional Layout, Spacing & Typography

1. **Fluid Layout Architecture:**
   - Use modern CSS Grid and Flexbox for layout structures.
   - Ensure the layout is responsive across mobile (375px), tablet (768px), and desktop (1280px+) viewports.
   - Hero Section Architecture: Full-bleed background photography (background-size: cover; background-position: center; min-height: 85vh; position: relative; overflow: hidden;); full-bleed gradient overlay (position: absolute; inset: 0; z-index: 1; pointer-events: none;); text content in relative container (position: relative; z-index: 2;). Never render partial-height translucent overlay bands.
   - Navigation Header & Mobile Control: Fixed/sticky header height between 64px and 76px. Use compact styled hamburger button (<button class="mobile-menu-btn" aria-label="Toggle navigation" aria-expanded="false"><span></span><span></span><span></span></button>) with 44-48px touch target; never render raw text 'Menu'. Drawer/dropdown must open with clean background and close on link click or Escape key.
2. **Proportional Spacing System:**
   - Use a consistent baseline spacing scale (such as a 4px or 8px grid or design token system) adapted to the project's style.
   - Use consistent gap and padding tokens between related elements (tight: 8px, standard: 16px, loose: 24-32px).
3. **Typographic Hierarchy:**
   - Establish clear optical hierarchy: Display -> Heading 1 -> Heading 2 -> Body -> Caption.
   - Maintain readable line lengths (45–75 characters per line for body copy) and line-heights (1.4–1.6 for body, 1.1–1.25 for display headers).

## 3. Intentional Motion & Micro-Interactions

Draw upon interaction craft principles (inspired by Emil Kowalski's animations.dev):
1. **Purpose-Driven Motion:**
   - Motion must inform, guide attention, or provide direct feedback—never merely serve as decorative delay.
2. **Durations & Easing:**
   - Micro-interactions (hover, active, toggle): typically 100ms–150ms with `ease-out`.
   - Small structural transitions (dropdowns, accordions, tooltips): typically 150ms–250ms with cubic-bezier or `ease-out`.
   - Modals and sheet entrances: typically 200ms–300ms with deceleration curves.
   - Exit transitions should generally be 20–30% faster than entrance transitions.
3. **Reduced Motion Accessibility:**
   - Always wrap transitions in `@media (prefers-reduced-motion: reduce)`:
     ```css
     @media (prefers-reduced-motion: reduce) {
       *, *::before, *::after {
         animation-duration: 0.01ms !important;
         transition-duration: 0.01ms !important;
         scroll-behavior: auto !important;
       }
     }
     ```

## 4. Accessibility by Default

1. **Contrast & Perception:** Ensure text meets WCAG AA minimum contrast ratio (4.5:1 for normal text, 3:1 for large text).
2. **Keyboard Navigation:** Every interactive element must have a visible, high-contrast `:focus-visible` outline. Never remove outlines without providing an accessible alternative.
3. **Semantics:** Use native HTML buttons (`<button>`) for actions, links (`<a>`) for navigation, and appropriate ARIA attributes for dynamic disclosure widgets.

## 5. Browser Verification Loop

When browser capabilities (`browser.navigate`, `browser.screenshot`, `browser.inspect`) are available:
1. **Viewport Verification:** Check rendered output at mobile (375px) and desktop (1280px) viewports.
2. **Interactive State Check:** Verify `:hover`, `:focus-visible`, `:active`, and `:disabled` states visually and functionally.
3. **Console & Error Audit:** Ensure zero JavaScript console errors or failed network requests occur during rendering.
4. **Honest Limitations:** If browser execution is unavailable in the environment, state the limitation and verify via static analysis and automated component tests.
