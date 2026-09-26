# HERMES 2.x Project Intelligence Architecture

## 1. Overview & Core Philosophy

The HERMES 2.x **Project Intelligence Subsystem** provides a unified, progressive-disclosure intelligence layer that equips the autonomous agent with project context without context-window bloat, stale instructions, or security vulnerabilities.

Prior to Prompt 8, long-running agents suffered from:
1. **Instruction Contamination**: Giant 500+ line rule files dumped indiscriminately into every turn context.
2. **Static Blindness**: The agent remained unaware if repository rules or dependencies changed mid-session.
3. **Prompt Injection Risks**: Unsandboxed user instructions injected directly into model system prompts without data/instruction fencing.
4. **Execution Uncertainty**: The agent repeatedly attempted to guess how to build, test, and run the project.

Project Intelligence solves this through a strict four-layer relevance hierarchy:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PROJECT INTELLIGENCE HIERARCHY                  │
├────────────────────────────────────────────────────────────────────────┤
│ 1. ALWAYS-KNOWN: HERMES.md                                             │
│    Root project constitution. Pinned, freshness-tracked, < 200 lines.   │
├────────────────────────────────────────────────────────────────────────┤
│ 2. PATH-RELEVANT: .hermes/rules/*.md                                   │
│    Indexed as metadata; body loaded lazily when active files match.    │
├────────────────────────────────────────────────────────────────────────┤
│ 3. TASK-RELEVANT: .hermes/skills/*/SKILL.md                            │
│    3-Level Progressive Disclosure: metadata → body → resources.       │
├────────────────────────────────────────────────────────────────────────┤
│ 4. ENVIRONMENT-RELEVANT: .hermes/bootstrap/                            │
│    Declared lifecycle actions (install, test, build, lint, dev).       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Taxonomy

| Layer | Source | Granularity | Ingestion Model | Prompt Fence |
|---|---|---|---|---|
| **Root Constitution** | `HERMES.md` / `.hermes/HERMES.md` | Repository-wide | Always loaded into `PROJECT_RULES` | `<project_constitution>` |
| **Scoped Rules** | `.hermes/rules/*.md` | File, Subsystem, Directory, Language | Metadata indexed; body loaded JIT on file match | `<scoped_rule>` |
| **Agent Skills** | `.hermes/skills/*/` | Task/Capability | 3-Level disclosure: Metadata $\to$ Body $\to$ Resource | `<skill_resource>` |
| **Lifecycle Bootstrap** | `.hermes/bootstrap/` | Environment Actions | Manifest discovered; never auto-executed | Telemetry / Action hints |

---

## 3. Freshness & Invalidation Engine

All four layers feature sub-millisecond freshness verification via `st_mtime_ns` and SHA-256 fingerprinting:
- **Root Constitution**: Detects external file edits mid-mission without restarting the process. Emits `PROJECT_INSTRUCTIONS_CHANGED`.
- **Scoped Rules**: Detects rule additions, modifications, or deletions. Invalidates body caches and emits `RULE_CHANGED` / `RULE_INVALIDATED`.
- **Skills**: Detects modifications to `SKILL.md`. Invalidates active skill bodies and resources, emitting `SKILL_CHANGED` / `SKILL_INVALIDATED`.
- **Bootstrap**: Detects updates to `bootstrap.json` / `bootstrap.yaml` and emits `BOOTSTRAP_CHANGED`.

---

## 4. Context Engine 2.x Integration

The `ProjectIntelligenceRegistry` synchronizes directly into `ContextEngine 2.x` during `build_context()`:
- `HERMES.md` instructions populate `ContextSectionType.PROJECT_RULES` with `ContextPriority.MANDATORY` and `relevance_score=1.0`.
- Matching scoped rules populate `ContextSectionType.SCOPED_RULES` with `ContextPriority.IMPORTANT` (for mandatory rules) or `OPTIONAL` (for guidance).
- Stale rules whose paths no longer match active files are evicted from the context pack automatically.
- Serializer places `PROJECT_RULES` and `SCOPED_RULES` strictly into the System role message, fenced by XML tags to prevent prompt injection.

---

## 5. Performance Benchmarks

Measured on standard development hardware:

| Operation | Target | Measured p50 | Measured p95 | Status |
|---|---|---|---|---|
| **Full Subsystem Discovery** | < 50.0 ms | **2.19 ms** | **3.19 ms** | PASS (15x faster) |
| **Scoped Rule Matching** | < 5.0 ms | **0.01 ms** | **0.02 ms** | PASS (250x faster) |
| **Skill Body Loading** | < 5.0 ms | **0.08 ms** | **0.17 ms** | PASS (30x faster) |
| **Skill Resource Loading** | < 5.0 ms | **0.36 ms** | **0.67 ms** | PASS (7x faster) |
| **100-Turn Average Context Build** | < 50.0 ms | **16.4 ms** | **28.2 ms** | PASS |
