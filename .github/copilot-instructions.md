<!-- Copilot instructions tailored to this FastAPI + Beanie project -->
# AI coding assistant guidance

Purpose: make the assistant immediately productive with the Backend service (FastAPI + MongoDB + Beanie).

- Big picture:
  - This is a FastAPI service; the application entrypoint is [app/main.py](app/main.py).
  - MongoDB is used via Motor + Beanie ODM; DB setup lives in [app/core/database.py](app/core/database.py).
  - Configuration is environment-driven using `pydantic-settings` in [app/core/config.py](app/core/config.py) (env file `.env`).
  - Routes are grouped under `/api/v1` via [app/api/v1/__init__.py](app/api/v1/__init__.py). Key endpoints:
    - Health: [app/api/v1/endpoints/health.py](app/api/v1/endpoints/health.py)
    - Users: [app/api/v1/endpoints/users.py](app/api/v1/endpoints/users.py)

- Project-specific patterns to follow (don't invent alternatives):
  - Data layer: domain models are Beanie `Document` classes (see [app/models/user.py](app/models/user.py)). New models must be added to `document_models` in [app/core/database.py](app/core/database.py) so `init_beanie` registers them.
  - Validation/IO: request/response shapes are Pydantic models in [app/schemas/user.py](app/schemas/user.py). Use `UserCreate`, `UserUpdate`, `UserResponse` where appropriate.
  - ID handling: endpoints accept string IDs and validate with `bson.ObjectId.is_valid()` before converting to `ObjectId` (see [app/api/v1/endpoints/users.py](app/api/v1/endpoints/users.py)). Follow this pattern for new resources.
  - Lifespan: DB connect/disconnect is handled by the `lifespan` context in [app/main.py](app/main.py). Avoid duplicating startup logic; extend `init_db` / `close_db` as needed.

- Integration points & external dependencies:
  - MongoDB connection string: `MONGODB_URL` and `MONGODB_DB_NAME` from [app/core/config.py](app/core/config.py).
  - Beanie + Motor: ensure `init_beanie(...)` is called with all `Document` models before app handles requests.
  - Tests use `httpx.AsyncClient` + `pytest` (see [tests/test_users.py](tests/test_users.py)). Many tests assume an operational DB or test fixtures that provide `sample_user` and `client`.

- Developer workflows (concrete commands):
  - Run the app locally: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
  - Run tests: `pytest -q` or `pytest tests/`
  - API docs available at `/docs` when the server is running (configured in [app/main.py](app/main.py)).

- Safety notes & quick wins:
  - Passwords: `hash_password` in [app/api/v1/endpoints/users.py](app/api/v1/endpoints/users.py) is a placeholder; do not rely on it for production changes—use `passlib`/bcrypt.
  - CORS: default `CORS_ORIGINS` is `['*']` (open). Keep changes explicit for production.
  - Indexes: model indexes are declared in `User.Settings.indexes`; add necessary indexes when introducing new query patterns.

- Where to look when making common changes:
  - Add new API route: create endpoint module under `app/api/v1/endpoints/` and `include_router` it in [app/api/v1/__init__.py](app/api/v1/__init__.py).
  - Add new DB model: implement a `Document` in `app/models/` and add it to `document_models` in [app/core/database.py](app/core/database.py).
  - Update config: change defaults or add env keys in [app/core/config.py](app/core/config.py) and document the expected `.env` entries.

- Tests and fixtures note:
  - Tests in `tests/` use async HTTP client fixtures; check [tests/conftest.py](tests/conftest.py) for fixture shapes before changing model fields used by tests.

If any section is unclear or you'd like more examples (for example, fixture shapes in `tests/conftest.py`), tell me which part to expand and I'll iterate.
