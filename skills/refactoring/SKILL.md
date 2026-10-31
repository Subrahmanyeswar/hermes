---
name: refactoring
description: Systematic code refactoring to improve modularity, readability, and maintainability while strictly preserving external behavior
triggers: [refactor, clean code, improve, optimise, restructure, solid, technical debt, messy]
priority: 1
max_tokens: 450
---

# Code Refactoring Specialist

Apply disciplined, step-by-step refactoring techniques. The primary objective is improving code health and maintainability without altering externally observable behavior.

## 1. Grounding & Baseline Verification
1. Inspect the target code and existing tests using `fs.read` and `shell.bash`.
2. Run existing tests before making any changes to establish an authoritative green baseline. If tests are absent or incomplete, write focused regression tests first.
3. Never combine refactoring with new feature development or bug fixes. Separate refactoring into dedicated, atomic steps.

## 2. Observable Maintainability Indicators (No Arbitrary Limits)
Avoid arbitrary metrics such as universal line-count or parameter-count thresholds. Instead, evaluate real architectural smells:
- **Mixed Levels of Abstraction:** Functions that handle high-level orchestration and low-level protocol parsing simultaneously.
- **Deeply Nested Control Flow:** Complex nested `if`/`for` structures (more than 3 levels) that hinder comprehension and error tracing.
- **Code Duplication:** Repeated logic across multiple modules that can be abstracted into a single, well-tested helper.
- **Hidden Side Effects & High Coupling:** Functions that mutate global state or modify input arguments unexpectedly.
- **Violations of Single Responsibility:** Classes or modules that change for multiple unrelated business reasons.

## 3. Safe Refactoring Procedures
4. **Extract Method / Function:** Group a cohesive block of logic into a private helper with clear input parameters and an explicit return type.
5. **Rename for Intent:** Replace ambiguous or cryptic identifiers with descriptive names reflecting their exact role and domain meaning.
6. **Replace Complex Conditionals:** Use guard clauses (early returns) to flatten deeply nested logic, or lookup dictionaries for static branching.
7. **Introduce Parameter Objects:** When a group of parameters always travels together across multiple functions, encapsulate them into a coherent dataclass or typed structure.

## 4. Verification & Diff Review
8. Apply modifications surgically using `fs.edit`.
9. Re-run tests immediately after each refactoring transformation using `shell.bash`.
10. Review `git diff` to ensure changes preserve public API contracts and do not introduce unintended side effects.
