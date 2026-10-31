---
name: database-design
description: Relational database schema design, normalization, indexing, transaction integrity, and migration patterns
triggers: [database, schema, sqlite, postgresql, sql, tables, migration, models, orm, db]
priority: 1
max_tokens: 450
---

# Database Design Specialist

Apply these principles for all relational database modeling, schema design, and migration tasks.

## 1. Domain Modeling & Schema Architecture
1. **Normalization & Table Identity:**
   - Entity tables: Typically use an explicit surrogate primary key (`id` integer or UUID) and audit timestamps (`created_at`, `updated_at`).
   - Junction / Associative tables: Use composite primary keys (e.g. `PRIMARY KEY (user_id, role_id)`) to enforce uniqueness without redundant surrogate IDs.
   - Lookup / Enumeration tables: Minimal column sets; timestamps are optional.
2. **Naming Conventions:** Consistent snake_case for tables and columns (`users`, `order_items`, `created_at`).
3. **Relationships & Integrity:**
   - Define foreign keys with explicit `ON DELETE` behavior (`CASCADE`, `SET NULL`, or `RESTRICT`).
   - Use `UNIQUE` constraints to enforce business invariants (e.g. unique email addresses, unique compound slugs).
4. **Indexing Strategy:**
   - Index all foreign key columns used in `JOIN` conditions.
   - Index columns frequently filtered in `WHERE` clauses or sorted in `ORDER BY`.
   - Avoid indexing low-cardinality flags (e.g. booleans) unless part of a selective composite index.

## 2. ORM & Query Conventions
- **SQLAlchemy 2.0:**
  - Use modern 2.0 `select()` syntax: `session.execute(select(User).where(User.active.is_(True)))`.
  - Avoid legacy 1.x `Model.query` patterns.
  - Bidirectional relationships must specify `back_populates` explicitly on both sides.
- **Transactions:** Always wrap multi-statement writes in transactions with explicit commit and rollback on exceptions.

## 3. Database Engine Specifics
- **SQLite:**
  - Enforce foreign keys at connection initialization: `PRAGMA foreign_keys = ON;`.
  - For concurrent read/write workloads, consider WAL mode: `PRAGMA journal_mode = WAL;`. Avoid WAL mode in read-only or distributed network filesystems.
- **PostgreSQL:**
  - Use appropriate column types (`TIMESTAMPTZ` for UTC timestamps, `JSONB` for semi-structured data, `TEXT` instead of arbitrary `VARCHAR(255)`).

## 4. Migration Best Practices
- If the project already uses a migration framework (Alembic, Flask-Migrate, Django migrations), follow the existing framework conventions.
- For raw SQL migrations, write idempotent DDL (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).
- Never perform destructive column or table drops without explicit confirmation and backup considerations.
- For extended schema patterns, see the lazy-loaded reference: `references/schema_patterns.md`.
