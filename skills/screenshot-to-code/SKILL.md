---
name: screenshot-to-code
description: Convert UI screenshots, Figma mockups, and visual designs into clean, responsive HTML/CSS or React components
triggers: [screenshot, screenshot to code, ui mockup, design to code, figma to code, image to code, wireframe, visual mockup]
priority: 1
max_tokens: 450
---

# Screenshot-to-Code Specialist

Apply these design-to-code techniques when translating visual mockups, wireframes, or screenshots into functional web markup.

## 1. Activation & Intent Boundary
1. Activate this specialist *only* when an actual screenshot, design mockup, wireframe, or visual reference is provided or explicitly requested. Do not activate for standard text-based web development tasks where no visual reference is involved.
2. Determine the requested target framework (vanilla HTML5/CSS, React, Vue, or Tailwind) based on project configuration and user requirements. Do not force Tailwind if the project does not use it.

## 2. Visual Analysis & Structural Hierarchy
3. **Layout Deconstruction:**
   - Identify main page landmarks: header, navigation, hero section, card grid, sidebar, footer.
   - Choose appropriate CSS layout primitives: CSS Grid for 2D card/table structures, Flexbox for 1D navigation bars and aligned rows/columns.
4. **Color & Typography Extraction:**
   - Extract primary, secondary, and background colors from the mockup; define them as CSS custom properties (`:root { --primary: #...; }`).
   - Identify font families, font weights, and type scales. Fall back gracefully to modern system fonts (`system-ui, -apple-system, sans-serif`) if custom fonts are unavailable.
5. **Spacing & Component Rhythm:**
   - Maintain consistent padding, margins, border radii, and drop shadows matching the visual reference.

## 3. Implementation & Accuracy Standards
6. **Semantic Markup:** Use semantic HTML (`<nav>`, `<main>`, `<section>`, `<article>`, `<button>`) rather than unstyled `<div>` soup.
7. **Interactive Elements:** Ensure buttons, inputs, links, and modal triggers have proper hover, focus, and active states.
8. **Responsive Breakpoints:** Implement mobile-first media queries (`@media (min-width: 768px)` or `@media (max-width: 768px)`) so the layout scales gracefully across screen sizes.
9. **Fidelity to Content:** Use the exact text, labels, and icons present in the visual reference; do not insert random placeholder copy when actual text is readable.

## 4. File Delivery & Verification
10. Write the generated markup and styles to the destination requested by the user using `fs.write`.
11. Inspect the resulting HTML/CSS files to verify syntactic correctness and stylesheet linkage.
