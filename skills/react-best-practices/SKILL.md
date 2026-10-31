---
name: react-best-practices
description: "React and Next.js engineering quality, performance optimization, server/client boundary management, async waterfall elimination, and state resilience."
triggers:
  - "react best practices"
  - "react performance"
  - "react re-render"
  - "nextjs best practices"
  - "bundle size optimization"
  - "react data fetching"
  - "avoid re-renders"
  - "client component optimization"
priority: 2
allowed-tools:
  - "fs.read"
  - "fs.write"
  - "fs.edit"
  - "search.glob"
  - "shell.bash"
---

# React Best Practices & Performance Engineering

Apply context-aware engineering discipline to React and Next.js applications. Adapt recommendations to the project's actual framework, installed versions, routing architecture, and verified bottlenecks rather than enforcing rigid dogma.

## 1. Inspect Environment & Architecture Before Acting

Before proposing or applying changes, inspect the target project using `fs.read` and `search.glob`:
1. **Identify Framework & Version:**
   - Inspect `package.json` for React version (`^18.x`, `^19.x`) and framework (`next`, `vite`, `remix`, or standalone CRA).
   - For Next.js, check whether the project uses App Router (`app/`) or Pages Router (`pages/`).
2. **Inspect Existing State & Data Layer:**
   - Detect data fetching libraries in use (`tanstack-query`, `swr`, native `fetch` in Server Components).
   - Do not introduce a new state-management or fetching library if the project already has an established solution.

## 2. Server/Client Execution Boundaries (Next.js / RSC)

When working in Next.js App Router or environments supporting React Server Components (RSC):
1. **Default to Server Components:**
   - Keep data fetching, heavy transformations, and secret handling on the server.
   - Do not add `"use client"` to a component unless it requires client-side hooks (`useState`, `useEffect`, `useRef`), browser APIs (`window`, `localStorage`), or DOM event listeners (`onClick`, `onChange`).
2. **Push `"use client"` Down the Component Tree:**
   - Instead of marking an entire page or layout as `"use client"`, extract interactive subcomponents (e.g. `<FavoriteButton />`, `<SearchBar />`) into small, focused client components.
   - Pass server-rendered children through composition (`children` or slots) into client wrappers to avoid converting child trees into client bundles.

## 3. Eliminating Asynchronous Waterfalls

1. **Parallel Execution:**
   - Identify independent asynchronous calls and run them concurrently using `Promise.all()` or `Promise.allSettled()`.
   - Avoid awaiting unrelated promises sequentially:
     ```typescript
     // Preferred: Parallel data retrieval
     const [userData, ordersData] = await Promise.all([
       fetchUserData(userId),
       fetchOrderHistory(userId),
     ]);
     ```
2. **Suspense Boundaries for Streaming:**
   - Wrap slow or non-critical page sections in `<Suspense fallback={<Skeleton />}>` so critical content renders immediately without waiting for secondary requests.

## 4. Re-Render Discipline & State Localization

1. **Locate State Close to Consumers:**
   - Avoid lifting state to parent components or global context when only a single leaf component needs it.
   - Moving state down eliminates re-rendering unaffected sibling branches.
2. **Judicious Memoization:**
   - Do NOT wrap every function in `useCallback` or every object in `useMemo` indiscriminately.
   - Apply `useMemo` when computing expensive derived state (e.g. computationally heavy transformations with measurable render cost) or preserving referential equality for dependency arrays of custom hooks.
   - Apply `React.memo` only to components that render frequently with unchanged props and have measurable render costs.

## 5. Bundle Size & Code Splitting

1. **Dynamic Imports:**
   - Use dynamic imports (`React.lazy` with `<Suspense>`, or `next/dynamic`) for heavy, non-critical components (e.g. charting engines, rich text editors, modal dialogues).
2. **Surgical Imports:**
   - Avoid barrel-file imports that pull in entire icon or utility libraries:
     ```typescript
     // Avoid: import { LucideIcon } from 'lucide-react'; (can bloat bundles)
     // Prefer path-specific or tree-shakeable imports per project build config
     ```

## 6. Resilient Interaction States

Every data-dependent interface must handle all five interaction states explicitly:
1. **Loading State:** Skeleton loaders or unobtrusive spinners that preserve layout stability (prevent CLS).
2. **Error State:** Human-readable error message with actionable recovery (e.g. retry button).
3. **Empty State:** Clear message when data sets are empty, guiding the user on how to populate data.
4. **Pending/Optimistic State:** Visual feedback during mutations, with rollback handling on error.
5. **Success State:** Accessible confirmation and updated data view.

## 7. Verification Loop

1. **Static Analysis & Types:** Run `shell.bash` with `npm run build` or `npx tsc --noEmit` to verify type safety.
2. **Test Execution:** Execute existing test suites via `shell.bash` using the project's test runner (`npm test` or `npx vitest`).
3. **Behavioral Proof:** Verify that no regressions in user experience or state consistency were introduced.
