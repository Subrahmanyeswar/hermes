---
name: project-context
description: Authoring, updating, and synchronizing repository context files, agent instructions, HERMES.md, AGENTS.md, and rule hierarchies.
category: documentation
priority: 2
triggers:
  - project context
  - hermes.md
  - agents.md
  - context file
  - repository guidelines
  - system instructions
  - agent instructions
  - project intelligence
allowed_tools:
  - fs.read
  - fs.write
  - fs.edit
  - search.glob
  - search.grep
---

# Project Context & Agent Instruction Engineering

This skill guides the creation, curation, and synchronization of repository context files (**`HERMES.md`**, **`AGENTS.md`**, rules, and system instructions) to provide autonomous coding agents with truthful, high-signal operational guidance.

---

## 1. Core Principles & Distinction from Auto-Docs

1. **Scope Boundary**:
   - `auto-docs` documents source code symbols, function signatures, docstrings, and API reference manuals.
   - `project-context` defines operational rules, architectural invariants, environment contracts, and behavioral boundaries for autonomous agents working in the repository.
2. **Truthfulness Over Aspiration**:
   - Document only verifiable system reality. Never document planned, theoretical, or deprecated capabilities as active features.
3. **Information Density & Anti-Bloat**:
   - Every line in a context file consumes agent context window tokens. Omit conversational filler, obvious boilerplate, and duplicate explanations.
4. **Actionable Operational Guidance**:
   - State explicit commands (e.g. canonical interpreter paths, pytest commands, dev server ports).
   - State explicit negative constraints (e.g. prohibited git commands, forbidden libraries, protected paths).

---

## 2. Canonical Context File Structure (`HERMES.md` / `AGENTS.md`)

When authoring or updating `HERMES.md` or `AGENTS.md`, structure content into these high-signal sections:

```markdown
# [Project Name] — Repository & Agent Guidelines

## 1. System Identity & Mission
Brief 1-2 sentence description of the system purpose, core tech stack, and primary entrypoints.

## 2. Canonical Environment & Tooling
- **Interpreter / Runtime**: Exact path or version (e.g. Python 3.12, Node 20).
- **Package Manager**: e.g., uv, poetry, pip, npm, pnpm.
- **Entrypoints**: CLI invocation or daemon startup command.
- **Test Command**: Exact test execution string (e.g., `pytest tests/ -v`).

## 3. Subsystem Architecture & Invariants
Bullet list of key subsystem boundaries and dependency directions (e.g. "persistence uses SQLite WAL; UI does not touch database directly").

## 4. Operational Guardrails & Prohibitions
- Prohibited operations (e.g. destructive git commands: `git reset --hard`, `git clean -fd`).
- Protected directories (e.g. historical reports, locked artifacts).
- Concurrency & locking contracts.
```

---

## 3. Synchronization Lifecycle

When maintaining project context across repository evolution:

1. **Inspect Codebase Reality**:
   - Use `search.grep` and `search.glob` to inspect actual package versions, config files, and directory layouts.
2. **Identify Divergence**:
   - Compare existing `HERMES.md` / `AGENTS.md` statements against codebase truth.
3. **Surgical Update**:
   - Use `fs.edit` to update outdated paths, commands, or subsystem descriptions.
4. **Verify References**:
   - Check that mentioned test files, scripts, and configuration keys actually exist.

---

## 4. Negative Boundaries & Anti-Patterns

- **Do NOT duplicate code docstrings**: Do not copy function-by-function API descriptions into project context files.
- **Do NOT add decorative prose**: Avoid conversational preambles, historical speculation, or redundant introductory text.
- **Do NOT document unbuilt features**: Context files must guide agents on current code, not unvalidated aspirations.
- **Do NOT reference fictitious tools**: Use genuine platform tools (`fs.read`, `fs.write`, `fs.edit`, `search.glob`, `search.grep`).
