---
name: react-frontend
description: React 18 component patterns with Tailwind CSS, hooks, and state management
triggers: [react, frontend, component, tailwind, jsx, ui, hooks, useState, useEffect, nextjs, website, site, web, robotics, robot, page, html, css]
priority: 1
max_tokens: 300
---
# React Frontend Specialist
Apply these rules for all React component and UI tasks.
## Component Structure
1. One component per file — filename matches component name exactly
2. Always use functional components — never class components
3. Props must be destructured in the function signature with TypeScript types
4. Export default at the bottom of the file, not inline with the function
## Hooks Rules
5. useState for local component state only
6. useEffect dependencies array must be complete — include all values used inside
7. Custom hooks go in src/hooks/ and start with 'use' prefix
## Tailwind CSS Rules
8. Use Tailwind utility classes only — no custom CSS files unless absolutely necessary
9. Responsive design: start mobile-first with sm: md: lg: prefixes
10. Common patterns: flex items-center justify-between, grid grid-cols-N gap-4
## File Structure
11. Components: src/components/ComponentName.tsx
12. Pages: src/pages/PageName.tsx or src/app/page.tsx (Next.js App Router)
13. API calls: src/lib/api.ts — never make fetch calls directly in components
## State Management
14. Local state: useState, complex local: useReducer, global: Context API or Zustand
