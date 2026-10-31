---
name: design-system
description: "Extract, document, maintain, and evolve consistent design systems and semantic token architectures from real codebases."
triggers:
  - "design system"
  - "design tokens"
  - "design token"
  - "token extraction"
  - "create design system"
  - "document design system"
  - "color tokens"
  - "typography scale"
  - "design token migration"
priority: 2
allowed-tools:
  - "fs.read"
  - "fs.write"
  - "fs.edit"
  - "search.glob"
  - "search.grep"
---

# Design System & Token Architecture

Extract, document, formalize, and evolve design systems from real codebases. Create cohesive design tokens, component standards, and clear documentation (such as `DESIGN.md`) rooted in verifiable code evidence rather than theoretical abstractions.

## 1. Audit Existing Source Code Before Defining Tokens

Do not invent arbitrary tokens in isolation. Inspect existing code using `search.glob` and `search.grep`:
1. **Locate Existing Styles & Variables:**
   - Check CSS/SCSS files for CSS custom properties (`:root { --... }`).
   - Check Tailwind configs (`tailwind.config.js`, `tailwind.config.ts`), Theme providers, or styled-system objects.
   - Inspect existing `DESIGN.md` or documentation if already present in the workspace.
2. **Catalog Color Inconsistencies:**
   - Search for hardcoded hex codes (`#...`), RGB, and HSL values across CSS and JSX files.
   - Group near-duplicate values (e.g., `#1E293B`, `#1F2937`, `#1A202C`) into single canonical semantic tokens.

## 2. Semantic Token Architecture

Organize tokens into three disciplined layers:
1. **Global / Primitive Tokens:**
   - Raw color values, font families, and raw numbers (e.g., `--color-blue-600: #2563eb; --space-4: 16px;`).
2. **Semantic / Purpose Tokens:**
   - Named by UI role, not appearance:
     - Surfaces: `--surface-canvas`, `--surface-card`, `--surface-raised`, `--surface-overlay`.
     - Text: `--text-primary`, `--text-secondary`, `--text-muted`, `--text-inverse`.
     - Actions: `--action-primary-bg`, `--action-primary-hover`, `--action-primary-text`.
     - Feedback: `--status-success`, `--status-warning`, `--status-error`, `--status-info`.
     - Borders: `--border-subtle`, `--border-default`, `--border-focus`.
3. **Component Tokens (Optional for complex design systems):**
   - Scoped to specific component slots (e.g., `--button-height-sm`, `--input-padding-x`).

## 3. Typography & Spacing Scales

1. **Typographic Scale:**
   - Base size: 16px (1rem).
   - Proportional scale:
     - `text-xs`: 12px (0.75rem), line-height: 16px
     - `text-sm`: 14px (0.875rem), line-height: 20px
     - `text-base`: 16px (1.000rem), line-height: 24px
     - `text-lg`: 18px (1.125rem), line-height: 28px
     - `text-xl`: 20px (1.250rem), line-height: 28px
     - `text-2xl`: 24px (1.500rem), line-height: 32px
     - `text-3xl`: 30px (1.875rem), line-height: 36px
2. **Spacing Grid:**
   - Multiples of 4px / 8px: `2px`, `4px`, `8px`, `12px`, `16px`, `20px`, `24px`, `32px`, `40px`, `48px`, `64px`.

## 4. Theme & Dark Mode Integration

1. When dark mode is required, map semantic tokens to theme variables rather than swapping hardcoded class names across hundreds of components:
   ```css
   :root {
     --surface-canvas: #ffffff;
     --text-primary: #0f172a;
     --border-default: #e2e8f0;
   }
   
   [data-theme="dark"], .dark {
     --surface-canvas: #0b0f19;
     --text-primary: #f8fafc;
     --border-default: #1e293b;
   }
   ```
2. Ensure both light and dark themes maintain minimum WCAG AA contrast ratios (4.5:1).

## 5. Documenting the Design System (`DESIGN.md`)

When creating or updating `DESIGN.md`, document:
- Design Principles (clarity, density, motion).
- Color Palette (swatches, hex values, semantic mappings).
- Typography Scale (font families, sizes, weights, line-heights).
- Spacing & Layout Tokens.
- Component Standards (interactive states, button variants, form inputs).
- Accessibility Standards (focus rings, contrast benchmarks).

## 6. Verification Loop

1. **Token Utilization Check:** Run `search.grep` to verify that newly defined tokens are actually consumed in stylesheets and components.
2. **Duplicate Value Audit:** Search for remaining unmigrated raw hex/rgb values in code.
3. **Build & Render Verification:** Execute `shell.bash` with project build commands to confirm CSS compilation succeeds without syntax errors.
