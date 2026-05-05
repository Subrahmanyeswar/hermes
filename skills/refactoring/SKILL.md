---
name: refactoring
description: Code refactoring using SOLID principles, clean code patterns, and modular design
triggers: [refactor, clean code, improve, optimise, restructure, solid, technical debt, messy]
priority: 1
max_tokens: 300
---
# Refactoring Specialist
Follow these rules for all refactoring tasks.
## Before Refactoring
1. Read the existing code with read_file first — understand before changing
2. Run existing tests with run_tests before making any changes — establish baseline
3. Never refactor and add features simultaneously — one thing at a time
## SOLID Principles
4. Single Responsibility: one class does one thing — split large classes into focused ones
5. Open/Closed: extend behaviour via subclasses or composition, not by modifying existing code
6. Dependency Inversion: depend on abstractions (interfaces) not concrete implementations
## Clean Code Rules
7. Functions longer than 20 lines need splitting
8. Functions with more than 3 parameters need a dataclass or config object
9. Deeply nested code (more than 3 levels) needs extraction into helper functions
10. Magic numbers/strings need named constants
## Refactoring Steps
11. Extract method: identify repeated code → create named function → replace all occurrences
12. Rename for clarity: variables should say what they contain, functions what they do
13. Run tests after every single change to confirm nothing broke
