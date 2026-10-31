---
name: react-composition-patterns
description: "Reusable, accessible React component architecture using compound components, slots, controlled/uncontrolled state, and clean public APIs."
triggers:
  - "react composition"
  - "compound component"
  - "component architecture"
  - "react slots"
  - "controlled component"
  - "react tabs pattern"
  - "react menu pattern"
  - "reusable component design"
priority: 2
allowed-tools:
  - "fs.read"
  - "fs.write"
  - "fs.edit"
  - "shell.bash"
---

# React Composition Patterns & Component Architecture

Design flexible, maintainable, and accessible React component systems. Prefer composition over prop drilling and configuration overload. Choose the simplest pattern that meets the requirements without introducing premature abstraction for simple one-off components.

## 1. Composition Over Boolean Prop Explosion

Avoid creating monolithic components controlled by dozens of boolean flags (e.g. `hasIcon`, `isCompact`, `showBadge`, `withDropdown`, `isHighlighted`):
1. **Inversion of Control via `children`:**
   - Let consumers pass arbitrary content, icons, or badges into dedicated sub-slots rather than configuring strings and flags through props.
2. **Explicit Variants:**
   - Use union-typed variant props (e.g. `variant: "primary" | "secondary" | "danger"`) instead of multiple conflicting boolean props (`isPrimary`, `isSecondary`).

## 2. Compound Component Pattern

When multiple subcomponents must coordinate shared state (e.g. Tabs, Accordion, Dropdown Menu, Dialog), use compound components with a scoped React context:

```tsx
// Pattern: Coordinated subcomponents with clean DX
interface TabsContextValue {
  activeTab: string;
  setActiveTab: (id: string) => void;
}

const TabsContext = React.createContext<TabsContextValue | null>(null);

export function Tabs({ defaultValue, value, onChange, children }: TabsProps) {
  const [internalValue, setInternalValue] = React.useState(defaultValue);
  const isControlled = value !== undefined;
  const activeTab = isControlled ? value : internalValue;

  const setActiveTab = React.useCallback((id: string) => {
    if (!isControlled) setInternalValue(id);
    onChange?.(id);
  }, [isControlled, onChange]);

  return (
    <TabsContext.Provider value={{ activeTab, setActiveTab }}>
      <div className="tabs-container" role="tablist">
        {children}
      </div>
    </TabsContext.Provider>
  );
}

Tabs.List = function TabList({ children }: { children: React.ReactNode }) {
  return <div className="tabs-list" role="tablist">{children}</div>;
};

Tabs.Tab = function Tab({ value, children }: { value: string; children: React.ReactNode }) {
  const ctx = React.useContext(TabsContext);
  if (!ctx) throw new Error("Tabs.Tab must be used within <Tabs>");
  const isSelected = ctx.activeTab === value;

  return (
    <button
      role="tab"
      aria-selected={isSelected}
      tabIndex={isSelected ? 0 : -1}
      onClick={() => ctx.setActiveTab(value)}
      className={`tab-trigger ${isSelected ? "tab-active" : ""}`}
    >
      {children}
    </button>
  );
};

Tabs.Panel = function TabPanel({ value, children }: { value: string; children: React.ReactNode }) {
  const ctx = React.useContext(TabsContext);
  if (!ctx) throw new Error("Tabs.Panel must be used within <Tabs>");
  if (ctx.activeTab !== value) return null;

  return (
    <div role="tabpanel" tabIndex={0} className="tab-panel">
      {children}
    </div>
  );
};
```

## 3. Controlled and Uncontrolled Dual-Mode

When designing reusable inputs, dialogs, or selectors:
1. Support uncontrolled usage via `defaultValue` for zero-boilerplate consumption.
2. Support controlled usage via `value` and `onChange` for parent state orchestration.
3. Ensure no warning about switching from uncontrolled to controlled state during lifecycle.

## 4. Scoped Context vs Mega-Context

1. **Keep Contexts Scoped:**
   - Create focused contexts specifically for the coordinating compound component family (`TabsContext`, `AccordionContext`).
   - Never place unrelated application state into component coordination contexts.
2. **Context Guard Hooks:**
   - Always throw an informative error if a compound child is rendered outside its parent provider.

## 5. Accessibility & Keyboard Semantics

Ensure all composed interactive components adhere to WAI-ARIA authoring practices:
1. **Roles:** Apply appropriate ARIA roles (`role="tablist"`, `role="tab"`, `role="tabpanel"`, `role="menu"`, `role="menuitem"`).
2. **State Attributes:** Maintain live ARIA state (`aria-expanded`, `aria-selected`, `aria-controls`, `aria-haspopup`).
3. **Keyboard Navigation:**
   - Tabs: `ArrowLeft`/`ArrowRight` (or `ArrowUp`/`ArrowDown` for vertical tabs) switches focus.
   - Menus: `ArrowDown`/`ArrowUp` cycles items; `Escape` closes the menu and returns focus to the trigger.
   - Enter/Space activates the focused item.

## 6. Testing Composed Components

1. Test observable user behavior rather than internal component state or context implementation details.
2. Verify:
   - Initial active item renders correctly.
   - Clicking tab or menu trigger changes the visible panel or closes the menu.
   - Keyboard arrows shift focus correctly and Space/Enter activates options.
   - Controlled `value` prop updates override internal clicks.

## 7. Verification Loop

1. **Type Checking:** Run `shell.bash` with `npx tsc --noEmit` to verify generic prop types and compound component assignments.
2. **Component Testing:** Execute behavioral interaction tests using React Testing Library or Vitest via `shell.bash`.
3. **Simplicity Guard:** Review API: does this component require compound architecture, or would a simple single component with `children` suffice?
