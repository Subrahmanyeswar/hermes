---
name: shadcn-ui
description: "Integrate, customize, and compose accessible shadcn/ui components aligned with the project's existing Tailwind and Radix architecture."
triggers:
  - "shadcn"
  - "shadcn/ui"
  - "shadcn ui"
  - "shadcn component"
  - "radix ui"
  - "shadcn dialog"
  - "shadcn form"
priority: 2
allowed-tools:
  - "fs.read"
  - "fs.write"
  - "fs.edit"
  - "search.glob"
  - "shell.bash"
---

# shadcn/ui Integration & Component Architecture

Integrate and customize shadcn/ui components deliberately. Treat shadcn/ui not as a mandatory default for every React project, but as a specialized toolkit of copy-paste, accessible Radix UI primitives styled with Tailwind CSS.

## 1. Inspect Project Configuration Before Acting

Do NOT assume standard paths or run initialization commands blindly. Use `fs.read` and `search.glob` to inspect:
1. **`components.json` Configuration:**
   - Verify whether the project already has `components.json`.
   - Check configured aliases:
     - `components`: e.g. `@/components` or `~/components`
     - `ui`: e.g. `@/components/ui`
     - `utils`: e.g. `@/lib/utils` (containing `cn()`)
     - `tailwind.config`: path to Tailwind configuration
     - `tailwind.css`: path to global CSS containing theme variables
2. **Existing UI Inventory:**
   - List files in the configured `ui/` folder using `search.glob`.
   - If a requested component (e.g. `button.tsx`, `dialog.tsx`, `dropdown-menu.tsx`) already exists, use or extend it. Never overwrite or duplicate existing components.
3. **Authorization Guardrail:**
   - Never run `npx shadcn@latest init` or `npx shadcn-ui add` without explicit operator instruction, as CLI commands can modify global project configurations and lockfiles.

## 2. Component Composition & Utility Helpers

1. **Class Merging (`cn`):**
   - Always merge classes through the project's canonical `cn()` utility (`clsx` + `tailwind-merge`):
     ```typescript
     import { cn } from "@/lib/utils";

     export function CustomCard({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
       return <div className={cn("rounded-lg border bg-card text-card-foreground shadow-sm", className)} {...props} />;
     }
     ```
2. **Radix Primitive Composition:**
   - Preserve Radix UI accessibility behaviors:
     - `Dialog`: Traps focus, handles `Escape` key, closes on backdrop click, restores focus on close.
     - `DropdownMenu`: Manages active item highlight via arrow keys, supports submenus and keyboard selection.
     - `Form`: Uses `<FormItem>`, `<FormLabel>`, `<FormControl>`, `<FormMessage>` to link error messages programmatically to input fields via `aria-describedby`.

## 3. Theme & CSS Variables Discipline

1. **Consume Semantic Color Tokens:**
   - Use HSL/CSS variable tokens configured in the project (`bg-background`, `text-foreground`, `bg-primary`, `text-primary-foreground`, `border-border`, `ring-ring`).
   - Do not replace semantic color tokens with hardcoded hex codes (`bg-[#2563eb]`).
2. **Dark Mode Integration:**
   - Rely on class-based dark mode (`.dark`) and CSS variable switching. Ensure custom component variants respect the active theme automatically.

## 4. Verification Loop

1. **Type Checking:** Execute `shell.bash` with `npx tsc --noEmit` to verify generic prop constraints and Radix event signatures.
2. **Lint & Build:** Run `shell.bash` with `npm run build` or the project's build tool to confirm clean module bundling.
3. **Accessibility Audit:** Ensure keyboard triggers, focus rings (`focus-visible:ring-2`), and screen reader labels are functional.
