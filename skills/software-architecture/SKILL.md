---
name: software-architecture
description: System-level architecture design, C4 modeling, module boundaries, architectural decision records (ADRs), and stable dependency management.
category: architecture
priority: 2
triggers:
  - architecture
  - software architecture
  - c4 model
  - c4 diagram
  - system design
  - adr
  - architectural decision record
  - system decomposition
  - module boundaries
allowed_tools:
  - fs.read
  - fs.write
  - fs.edit
  - search.glob
  - search.grep
---

# Software Architecture & System Decomposition

This skill guides high-level structural design, subsystem boundary enforcement, architectural documentation via the **C4 model**, and formal **Architecture Decision Records (ADRs)**.

---

## 1. Core Architectural Invariants

1. **Unidirectional Dependency Flow**:
   - High-level domain logic must never depend directly on low-level volatile details (UI drivers, concrete network protocols, specific database drivers).
   - Core business entities -> Application services/use cases -> Infrastructure/adapters.
2. **Stable Dependencies Principle**:
   - Modules that change frequently must depend on modules that are more stable, never the reverse.
3. **Explicit Subsystem Interfaces**:
   - Cross-module communication must traverse well-defined public APIs or contracts, not internal private structures.
4. **Pragmatic Monolith First**:
   - Default to a well-structured modular monolith.
   - Do NOT introduce microservices, distributed RPC, or message brokers unless explicitly mandated by independent scaling, deployment, or team boundary constraints.
5. **Separation from Refactoring**:
   - `refactoring` handles method-level, class-level, and local code structure.
   - `software-architecture` handles system composition, inter-package contracts, cross-cutting persistence/event pipelines, and documentation.

---

## 2. C4 Model Architectural Documentation

Document systems across four complementary abstraction tiers:

### Level 1: System Context Diagram
Shows the software system in its ecosystem: who uses it and what external systems it interacts with.
- **Actor/User**: e.g., Operator, End User, Autonomous Agent.
- **System**: The system being designed or analyzed.
- **External Dependencies**: External APIs, identity providers, third-party databases.

### Level 2: Container Diagram
Shows the high-level technical architecture and deployable/runnable units.
- **Web Application / GUI**: Browser-based frontend (e.g. Vite + React).
- **API Server / Core Runtime**: Backend daemon or service process (e.g. FastAPI / Python).
- **Persistence Store**: Database or file-based journal (e.g. SQLite + WAL).

### Level 3: Component Diagram
Shows how a specific container is composed of modular components and interfaces.
- **Controllers / Routers**: Inbound protocol handlers.
- **Domain Services / Engines**: Core computational logic and orchestration.
- **Repositories / Gateways**: Data persistence and integration boundaries.

### Level 4: Code / Class Diagram (Optional)
Reserved strictly for intricate or high-risk domain logic where detailed structural diagrams illuminate complex patterns.

---

## 3. Architecture Decision Record (ADR) Standard

When introducing or changing a critical architectural invariant, capture the rationale using the canonical ADR structure:

```markdown
# ADR-001: [Concise Decision Title]

## Status
[Proposed | Accepted | Superseded | Deprecated]

## Context
What is the business or technical problem? What constraints exist? What options were evaluated?

## Decision
What is the chosen design or pattern? What is the scope of application?

## Consequences
- **Positive**: Benefits gained, risks mitigated, performance improvements.
- **Negative**: Added complexity, operational overhead, learning curves.
- **Neutral**: Migration paths, follow-up monitoring tasks.
```

---

## 4. Anti-Patterns & Negative Boundaries

- **No Premature Microservices**: Never split a system into separate services, networked RPCs, or multi-repo setups without measurable, validated operational need.
- **No Dogmatic Clean Architecture Bloat**: Do not create 5 layers of redundant pass-through classes, DTOs, interfaces, and mappers for trivial CRUD operations.
- **No Circular Module Imports**: Ensure package dependency graphs are Directed Acyclic Graphs (DAGs).
- **No Fictional Tool Usage**: Rely exclusively on genuine platform tools (`fs.read`, `fs.write`, `fs.edit`, `search.glob`, `search.grep`).
