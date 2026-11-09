---
name: web-design-guidelines
description: "Review websites and application interfaces against evidence-backed usability, accessibility (WCAG AA), interaction, and visual consistency criteria."
triggers:
  - "web design guidelines"
  - "ui audit"
  - "usability review"
  - "accessibility audit"
  - "keyboard navigation audit"
  - "a11y review"
  - "design heuristic evaluation"
priority: 2
allowed-tools:
  - "fs.read"
  - "search.grep"
  - "search.glob"
  - "browser.navigate"
  - "browser.inspect"
  - "browser.console"
---

# Web Design Guidelines & Interface Usability Audit

Perform rigorous, evidence-driven audits of web interfaces, forms, and applications against established usability, accessibility, and interaction standards. Distinguish verified defects from speculative risks and subjective design preferences.

## 1. Audit Taxonomy & Severity Tiers

Structure every audit report into three clear categories with exact file, line, or selector locations:
1. **[CONFIRMED ISSUE]:** Verified defect violating accessibility or usability standards (e.g. contrast ratio < 4.5:1, non-focusable interactive controls, missing form labels, broken keyboard trap, layout overflow on mobile).
2. **[RISK REQUIRING VERIFICATION]:** Potential issue that depends on runtime data, dynamic viewport sizing, or localized text expansion (e.g. text truncation risks, dynamic touch target overlap).
3. **[RECOMMENDATION / ENHANCEMENT]:** Subjective polish or micro-interaction refinement that improves user flow but does not constitute a functional defect.

## 2. Core Audit Checklist

### A. Accessibility & Semantics (WCAG 2.1 AA)
- [ ] **Contrast:** Text and interactive icons maintain minimum 4.5:1 contrast against their rendered background (3:1 for text >= 24px or 18.5px bold).
- [ ] **Form Labels:** Every `<input>`, `<textarea>`, and `<select>` is programmatically associated with an accessible label (`<label for="...">` or `aria-label`).
- [ ] **Keyboard Operability:** All interactive components can be reached and operated via `Tab`, `Shift+Tab`, `Enter`, `Space`, and arrow keys without keyboard traps.
- [ ] **Focus Indication:** A clear, visible `:focus-visible` indicator (minimum 2px solid outline or distinctive ring) appears when navigating via keyboard.
- [ ] **Touch Targets:** Interactive targets on touch devices measure at least 44x44 CSS pixels (or 24x24 with adequate surrounding spacing).
- [ ] **Mobile Navigation:** Navigation toggle uses an accessible styled icon (e.g. 3-bar hamburger or SVG) with aria-label="Toggle navigation" and aria-expanded state; raw unstyled 'Menu' text is strictly prohibited.

### B. Usability & Information Architecture
- [ ] **Visual Hierarchy:** Primary action is visually prominent; secondary actions are subordinated; destructive actions are clearly delineated.
- [ ] **Reading Length & Typography:** Paragraph line lengths do not exceed 75 characters; font size is at least 16px for body copy on mobile.
- [ ] **Navigation Predictability:** Navigation links clearly indicate current page state (`aria-current="page"`); breadcrumbs or back links function reliably.

### C. Responsiveness & Layout Resilience
- [ ] **No Horizontal Scroll:** Pages fit within 320px–375px viewports without horizontal scrolling or clipped content.
- [ ] **Dynamic Content Resilience:** Containers accommodate varying text lengths without overlapping sibling elements or truncating critical actions.

### D. State Completeness
- [ ] **Interactive States:** Buttons, links, and form fields provide distinct visual feedback for default, hover, focus, active, and disabled states.
- [ ] **Lifecycle States:** Data views explicitly provide Loading (skeleton/spinner), Empty (informative prompt), Error (recovery path), and Success feedback.

## 3. Actionable Remediation Format

For each confirmed issue, provide:
- **Location:** File path, component name, and line numbers.
- **Evidence:** Concrete violation (e.g., contrast measured 2.8:1; missing `aria-expanded` on accordion button).
- **Impact:** How the issue affects real users (e.g., screen reader users cannot perceive collapsed state).
- **Surgical Remedy:** Exact drop-in replacement HTML/CSS/JSX diff.

## 4. Browser Verification Loop

When browser capabilities (`browser.navigate`, `browser.inspect`, `browser.console`) are accessible:
1. Load the page at standard viewports (375px, 768px, 1280px).
2. Check `browser.console` for accessibility warnings, layout shift flags, or unhandled errors.
3. Test keyboard focus sequence via simulated Tab navigation.
4. Report verified findings honestly; if browser access is unavailable, clearly state that inspection was performed via static analysis.
