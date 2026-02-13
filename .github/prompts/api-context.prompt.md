# Context: Student Course API & Logic

Use this context when asking an AI to generate new endpoints or fix bugs in this project.

## Core Architecture Constraints

1.  **Database Models (Beanie)**:
    *   **IDs**: ALL models must override `id` to allow string IDs: `id: Optional[str] = Field(default=None, alias="_id")`.
    *   **Collections**: Explicitly set collection names in `Settings` (e.g., `name = "Courses"`). Be case-sensitive.
    *   **Enums**: When querying, always use `.value` (e.g., `status == Status.ACTIVE.value`).

2.  **Authentication**:
    *   `get_current_user` returns a `Dict[str, Any]`, **not** a class instance.
    *   ALWAYS access user properties like `current_user["user_id"]` or `current_user.get("role")`.

3.  **Bugs & Fixes Log**:
    *   **CORS**: `allow_headers` should be `["*"]` to prevent blocking frontend frameworks.
    *   **Validation**: 
        *   If you see `Id must be of type PydanticObjectId`, you defined `id` as `str` but the DB used `ObjectId`. Check `Alerts` vs `Courses` models.
        *   If you see `Document failed validation (121)`, you are likely `.save()`-ing nulls into fields that don't allow it. Use `.update({"$set": ...})`.
    *   **Logic (Auto-Enrollment)**: 
        *   **Standard Courses**: Only runs if the student has **ZERO** enrollments (active or dropped) for the term.
        *   **Retake Courses (Mandatory)**: MUST run always. If a student failed a course in a previous matching semester (Odd/Even parity match), it **must** be auto-inserted if missing.
        *   **Idempotency**: Check `Enrollment.find(status="Dropped")` before re-inserting.
    *   **Logic (Drop Course)**: **NEVER** use `delete()`. specific Use `update({"$set": {"status": "Dropped"}})` to prevent auto-enrollment loops.
    *   **Typing**: Use `Dict[str, Any]` for mixed content fields (like `semester` config) to handle booleans/numbers inside dicts.

## Directory Map
*   Models: `app/models/`
*   Endpoints: `app/api/v1/endpoints/`
*   Dependencies: `app/api/v1/deps/`

