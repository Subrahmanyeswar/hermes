# HERMES 2.x Agent Skills Architecture

## 1. The 3-Level Progressive Disclosure Model

Traditional agent architectures load entire skill bodies, prompt guidelines, and supporting scripts into the primary system prompt at session initialization. In projects with 20+ specialized skills, this consumes tens of thousands of tokens before turn 1 begins.

HERMES 2.x introduces the **3-Level Progressive Disclosure** model:

```
Level 1: Startup Metadata Index (~50 tokens per skill)
  ├── Name & description
  ├── Semantic trigger phrases
  ├── Allowed / hinted tools
  └── Execution flags (context fork, model disable)
        │
        ▼ (Model triggers or task matches)
Level 2: Skill Body On-Demand (~500 - 1500 tokens)
  └── Full SKILL.md instructions loaded JIT
        │
        ▼ (Agent requests specific reference or script)
Level 3: Supporting Resources On-Demand (Exact file size)
  └── References, schemas, checklists, or scripts loaded individually
```

---

## 2. Directory Layout & Frontmatter Schema

Each Agent Skill lives in its own subdirectory inside `.hermes/skills/` (or repository root `skills/`):

```
.hermes/skills/db_migration/
  ├── SKILL.md
  ├── references/
  │   ├── safety_checklist.md
  │   └── schema_template.sql
  └── scripts/
      └── check_drift.py
```

### Frontmatter Schema

```yaml
---
name: db-migration
description: Safely generate and apply relational database migrations.
triggers:
  - database migration
  - schema change
  - alembic
priority: 5
allowed-tools:
  - fs.read
  - fs.write
  - shell.bash
disable-model-invocation: false
context: inline  # or "fork"
---
# Database Migration Procedure
Instructions here...
```

---

## 3. Security & Containment Invariants

1. **Path Traversal Defense**:
   Attempts to resolve resources outside the skill directory via `../` (e.g. `../../secret.env`) are intercepted and rejected with a `Security violation: path traversal detected` error.
2. **Binary File Protection**:
   Resource files containing null bytes or non-text content are rejected with `SKILL_RESOURCE_BINARY`.
3. **Permission Containment**:
   The `allowed_tools` field serves as a filter and hint. It **never escalates** permissions beyond the authoritative `PermissionPolicy` of the harness.
4. **Prompt Injection Boundary**:
   Skill resources loaded into model context are explicitly tagged with `<skill_resource name="..." path="...">` to prevent untrusted content from overriding core system rules.
