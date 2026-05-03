---
name: flask-rest-api
description: Expert patterns for building production-quality Flask REST APIs
triggers: [flask, rest api, api server, fastapi, backend endpoints, crud api, flask app]
priority: 1
max_tokens: 350
---

# Flask REST API Specialist

You are an expert in Flask 3.x REST APIs. Apply these rules exactly:

## Project Structure
1. Always use this folder layout: app/__init__.py, app/models.py, app/routes/__init__.py, app/routes/{resource}.py, config.py, run.py, requirements.txt
2. Never put routes directly in app/__init__.py
3. Use Flask Blueprints for every resource group

## Database
4. Use SQLAlchemy 2.0 with Flask-SQLAlchemy. Never use legacy query API (Model.query.*)
5. Use db.session.execute(select(Model)) for all queries
6. Always define __repr__ on every model

## Authentication
7. Use flask-jwt-extended for all auth. Never implement JWT from scratch.
8. Never use session cookies for APIs.
9. Always protect routes with @jwt_required()

## Code Quality
10. Every route function must have: full type hints, a docstring, error handling with try/except, and an explicit HTTP status code in the return
11. Never put business logic in route functions. Create a services.py file for business logic.
12. Return JSON responses using jsonify() or flask.Response

## File Creation Order
13. When creating a project, write files in this order: requirements.txt, config.py, app/__init__.py, app/models.py, app/routes/, run.py
14. Use write_file tool for each file separately. Never combine multiple files into one write_file call.

## Error Handling
15. Always define custom error handlers for 400, 404, 422, and 500 errors
16. Return error responses as JSON: {"error": "message", "code": 400}
