---
name: flask-rest-api
description: Production-quality Flask REST API design, modular blueprints, input validation, and database integration
triggers: [flask, rest api, api server, backend, crud api, flask app, web api, endpoints]
priority: 1
max_tokens: 450
---

# Flask REST API Specialist

Apply these design principles for building robust, maintainable Flask REST APIs.

## 1. Project Architecture & Factory Pattern
1. Use the Application Factory pattern (`create_app(config_class=...)`) for testability and modularity, unless the project has an established structure.
2. Group related endpoints into modular `Blueprint`s (e.g. `api/users.py`, `api/items.py`).
3. Keep business logic in a dedicated service layer or model methods rather than bloating route handlers.
4. Adapt to existing project file conventions rather than forcing an arbitrary directory layout.

## 2. Request Handling & Validation
5. Parse and validate JSON request payloads explicitly:
   - Check content type (`request.is_json`).
   - Validate presence and types of required fields; return HTTP 400 Bad Request with a clear message if validation fails.
6. Use query parameters (`request.args`) for filtering, pagination, and sorting on `GET` endpoints.
7. Return standard HTTP status codes:
   - `200 OK`: Successful read or update.
   - `201 Created`: Successful resource creation (include `Location` header or resource ID).
   - `204 No Content`: Successful deletion.
   - `400 Bad Request`: Invalid input or validation failure.
   - `404 Not Found`: Resource does not exist.
   - `500 Internal Server Error`: Unhandled server exception.

## 3. Database & Transaction Safety
8. Use modern SQLAlchemy 2.0 query patterns: `db.session.execute(select(Model).where(...))`.
9. Wrap mutations in safe transactional blocks with automatic rollback on error:
   ```python
   try:
       db.session.add(item)
       db.session.commit()
   except Exception:
       db.session.rollback()
       raise
   ```

## 4. Authentication & Security (Conditional)
10. Include authentication (JWT via `flask-jwt-extended`, API keys, or session tokens) *only* when the task or project explicitly requires authentication. Do not force auth dependencies on public/unauthenticated endpoints.
11. Secure sensitive configuration (secret keys, database credentials) via environment variables or a configuration class, never hardcoded in source files.

## 5. File Operations & Testing
12. Use `fs.write` to create new route or model files, and `fs.edit` for surgical updates.
13. Verify API behavior using pytest with Flask's test client (`app.test_client()`) via `shell.bash`.
