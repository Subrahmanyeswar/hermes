# Relational Database Schema Patterns Reference

This reference provides practical schema templates for common relational modeling patterns.

## 1. Many-to-Many Junction Table (Composite Primary Key)
```sql
CREATE TABLE IF NOT EXISTS user_roles (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id)
);
CREATE INDEX IF NOT EXISTS idx_user_roles_role_id ON user_roles(role_id);
```

## 2. Multi-Tenant Partitioning by Organization
```sql
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(120) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_org_project_name UNIQUE (organization_id, name)
);
CREATE INDEX IF NOT EXISTS idx_projects_org_id ON projects(organization_id);
```

## 3. Soft Delete Pattern
```sql
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE NULL
);
-- Partial index excluding soft-deleted records
CREATE INDEX IF NOT EXISTS idx_active_documents ON documents(title) WHERE deleted_at IS NULL;
```
