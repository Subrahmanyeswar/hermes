---
name: database-design
description: Database schema design patterns for SQLite and PostgreSQL with SQLAlchemy
triggers: [database, schema, sqlite, postgresql, sql, tables, migration, models, orm, db]
priority: 1
max_tokens: 300
---
# Database Design Specialist
Apply these rules for all database schema and migration tasks.
## Schema Design Rules
1. Every table must have: id (INTEGER PRIMARY KEY AUTOINCREMENT for SQLite, SERIAL for PostgreSQL), created_at (DATETIME DEFAULT CURRENT_TIMESTAMP), updated_at
2. Use snake_case for all table and column names
3. Foreign keys must have explicit ON DELETE behaviour: CASCADE or SET NULL
4. Add indexes on columns used in WHERE clauses and JOIN conditions
## SQLAlchemy 2.0 Model Rules
5. Define __tablename__ and __repr__ on every model class
6. Use relationship() with back_populates for bidirectional relationships
7. Never use the legacy Model.query API — use db.session.execute(select(Model))
## SQLite Specific
8. Enable WAL mode for concurrent access: PRAGMA journal_mode=WAL
9. Enable foreign key enforcement: PRAGMA foreign_keys=ON
## Migration Pattern
10. Always create a migration script at migrations/V{N}_{description}.sql
11. Migration scripts must be idempotent — use IF NOT EXISTS, IF EXISTS
