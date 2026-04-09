---
name: fastapi-best-practices
description: 'Apply Python and FastAPI best practices for project structure, async programming, Pydantic validation, error handling, and testing. Use when refactoring, reviewing code, or creating new endpoints.'
---

# FastAPI and Python Best Practices

## When to Use
- Reviewing or refactoring Python and FastAPI code.
- Creating new API endpoints, database models, or business services.
- Fixing or optimizing asynchronous database queries and API calls.
- Writing or debugging tests for FastAPI applications.

## Procedure

1. **Analyze the Target Code**
   Determine the layer of the application being modified (API routes, services, database models, schemas, or tests).

2. **Apply Architectural Rules**
   - **Keep Routes Thin**: API endpoints in `app/api/` should only handle HTTP concerns (request parsing, response formatting).
   - **Service Layer**: Move all business logic and complex orchestrations to `app/services/`.
   - **Separation of Concerns**: Strictly separate database models (`app/models/`) from data validation and serialization schemas (`app/schemas/`).

3. **Enforce Async Best Practices**
   - Use `async def` for I/O-bound operations (e.g., async database drivers, HTTP calls).
   - **Avoid Blocking**: Never run CPU-bound tasks or blocking synchronous code inside an `async def` route. If you must use synchronous blocking code, use a standard `def` route (FastAPI runs these in a threadpool).

4. **Validate Data with Pydantic**
   - Create distinct Pydantic models for different operations to avoid leaky abstractions (e.g., `ItemCreate`, `ItemRead`, `ItemUpdate`).
   - Leverage `pydantic.Field` to enforce constraints (min/max length, regex patterns) directly at the schema level.

5. **Implement Robust Error Handling**
   - Raise `fastapi.HTTPException` for expected API errors (400, 404).
   - Catch unexpected errors globally and do not leak internal database exceptions or stack traces to the client in production.

6. **Ensure Testability**
   - Use `pytest` as the test runner.
   - Use `fastapi.testclient.TestClient` for synchronous testing or `httpx.AsyncClient` for purely async flows.
   - Ensure tests are isolated using database fixtures and mock external services.

## Quality Criteria / Completion Checks
- [ ] Are the API routes thin and delegating business logic to services?
- [ ] Is asynchronous code used correctly without blocking the main event loop?
- [ ] Are Pydantic models utilized effectively with strict validation fields?
- [ ] Are errors handled gracefully without exposing internal stack traces?
- [ ] Are tests updated or added for the modified logic?
