---
name: react-frontend
description: Modern React 18+ component patterns, state management, hooks lifecycle, accessible UI, and TypeScript integration
triggers: [react, reactjs, jsx, tsx, nextjs, react-router, zustand, redux, react-hooks]
priority: 1
max_tokens: 450
---

# React Frontend Specialist

Apply these best practices for building responsive, accessible, and maintainable React applications.

## 1. Project Alignment & Architecture
1. Inspect existing project structure before creating components (Vite, Next.js App Router, or standard SPA).
2. Adapt to the project's established styling strategy (Tailwind CSS, CSS Modules, styled-components, or vanilla CSS). Do not introduce Tailwind if the project does not already configure it.
3. Keep component responsibilities focused: separate presentation components from data-fetching or state-container logic.

## 2. Component Design & TypeScript
4. Use functional components with explicit TypeScript interfaces for props:
   ```tsx
   interface UserCardProps {
     name: string;
     email: string;
     onSelect?: (email: string) => void;
   }
   export const UserCard: React.FC<UserCardProps> = ({ name, email, onSelect }) => { ... };
   ```
5. Destructure props in the function signature for clarity and default values.
6. Provide meaningful fallback states for loading and error conditions in asynchronous UI.

## 3. Hooks & State Ownership
7. Keep state as local as possible (`useState`, `useReducer`). Hoist state to parents or context only when multiple sibling components genuinely require it.
8. Maintain exhaustive dependency arrays in `useEffect` and `useCallback`. Never suppress ESLint dependency warnings without clear architectural justification.
9. Avoid redundant state that can be derived during rendering from existing props or state.

## 4. Accessibility & User Experience
10. Use semantic HTML elements (`<main>`, `<header>`, `<nav>`, `<article>`, `<button>`). Never use `<div onClick=...>` without proper `role="button"`, `tabIndex`, and keyboard handlers (`onKeyDown`).
11. Ensure form inputs have associated `<label>` elements or `aria-label` attributes.
12. Design responsive layouts mobile-first using Flexbox and CSS Grid.
