---
name: fastapi-backend
description: Asynchronous backend engineering with FastAPI, Pydantic v2 schemas, dependency injection, and ASGI architecture.
category: backend
priority: 2
triggers:
  - fastapi
  - fastapi backend
  - asgi
  - pydantic model
  - fastapi router
  - async backend
  - fastapi endpoints
allowed_tools:
  - fs.read
  - fs.write
  - fs.edit
  - shell.bash
  - search.glob
  - search.grep
---

# FastAPI Backend Engineering

This skill guides the construction, refactoring, and verification of robust asynchronous backend services using **FastAPI**, **Pydantic v2**, and **ASGI** conventions.

---

## 1. Core Architectural Invariants

1. **Lifespan Context Management**:
   - Always use `lifespan` context manager via `@asynccontextmanager` on the `FastAPI` instance.
   - Never use deprecated `@app.on_event("startup")` or `@app.on_event("shutdown")`.
2. **Pydantic v2 Canonical Schemas**:
   - Use `pydantic.BaseModel` with `ConfigDict(extra="forbid", from_attributes=True)`.
   - Serialization: Use `.model_dump()` and `.model_dump_json()`. Never call deprecated `.dict()` or `.json()`.
   - Field constraints: Use `Field(min_length=..., max_length=..., pattern=...)`. Never use deprecated `regex=`.
   - Validators: Use `@field_validator` and `@model_validator(mode="after")`. Never use deprecated `@validator` or `@root_validator`.
3. **Modular APIRouter Decomposition**:
   - Decompose endpoints into domain routers (`APIRouter(prefix="/...", tags=["..."])`).
   - Include routers into the root app via `app.include_router(router)`.
4. **Dependency Injection**:
   - Encapsulate database sessions, authentication, and service clients via `Depends(...)`.
   - Use generator dependencies with `try / finally` to ensure resource cleanup.
5. **Async Safety**:
   - Endpoints performing non-blocking async I/O must be declared `async def`.
   - Endpoints performing blocking CPU-bound or synchronous I/O should be declared standard `def` (allowing FastAPI's threadpool to run them) or wrapped with `asyncio.to_thread`.
6. **Strict Response Typing**:
   - Always specify `response_model=...` and appropriate `status_code` (e.g. `status.HTTP_201_CREATED` for creations).

---

## 2. Canonical Application Pattern

```python
from contextlib import asynccontextmanager
from typing import AsyncGenerator, List, Optional
from fastapi import FastAPI, APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field


# ── Schemas (Pydantic v2) ─────────────────────────────────────────────
class ItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=100)
    price: float = Field(..., gt=0.0)
    description: Optional[str] = Field(None, max_length=500)


class ItemResponse(ItemCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str


# ── Lifespan Management ───────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: initialize connections, pools, background workers
    yield
    # Shutdown: cleanly close connections and flush buffers


app = FastAPI(title="Backend Service", version="1.0.0", lifespan=lifespan)

# ── Router & Dependency Injection ─────────────────────────────────────
router = APIRouter(prefix="/api/v1/items", tags=["items"])


def get_service():
    # Provide scoped resource or service client
    return {"status": "ready"}


@router.post("", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(payload: ItemCreate, service: dict = Depends(get_service)):
    if payload.name.lower() == "forbidden":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Item name is forbidden",
        )
    return ItemResponse(id="item-001", **payload.model_dump())


app.include_router(router)
```

---

## 3. Integration Testing Pattern

Always test FastAPI applications using `httpx.AsyncClient` with `ASGITransport` or `fastapi.testclient.TestClient`.

```python
import pytest
from httpx import ASGITransport, AsyncClient
from my_app.main import app


@pytest.mark.asyncio
async def test_create_item_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/items",
            json={"name": "Widget", "price": 19.99, "description": "Test widget"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Widget"
    assert data["id"] == "item-001"
```

---

## 4. Negative Boundaries & Anti-Patterns

- **Do NOT use for Flask**: When the task or codebase specifies Flask, route to `flask-rest-api`.
- **Do NOT rewrite existing Flask services to FastAPI** unless explicitly requested by the mission prompt.
- **Do NOT use deprecated FastAPI startup/shutdown event handlers**.
- **Do NOT mix Pydantic v1 syntax** (`.dict()`, `regex=`, `@validator`) into new code.
- **Do NOT leak internal database models**; always map through explicit Pydantic response schemas.
- **Do NOT run long-running blocking I/O directly in `async def` handlers**; wrap with `asyncio.to_thread` or use standard `def`.
