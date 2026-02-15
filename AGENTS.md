# AGENTS.md - Backend Agent Operating Guide

This file defines how coding agents should work in this backend repository.

## Purpose

Provide consistent, safe, and high-quality changes for:
- FastAPI + Beanie API endpoints
- UniPortal business rules
- MongoDB Atlas Vector Search / RAG workflows

Source alignment:
- `Backend/.cursor/skills/mongodb-rag/SKILL.md`
- `Backend/.github/skills/business-logic/SKILL.md`
- `Backend/.github/skills/data-schemas/SKILL.md`
- `Backend/.github/prompts/api-context.prompt.md`
- `Backend/.github/prompts/plan-studentCourseDashboardApi.prompt.md`
- `Backend/docs/API_DEVELOPMENT_GUIDE.md`

## Agent Priorities

1. Preserve database integrity and existing business behavior.
2. Keep endpoints idempotent and safe under repeated calls.
3. Prefer strict, explicit schema-aware logic over assumptions.
4. Keep collection names and enums exact.
5. For AI features, maximize retrieval quality before prompt complexity.

## Required Architecture Rules

### 1) Mongo/Beanie model rules

- Collection names are case-sensitive and must match existing DB names (TitleCase).
- If collection stores ObjectId, do not type model `id` as `str`.
- For partial updates, use atomic operators (`$set`) and avoid `.save()` when only changing a subset of fields.
- Do not hard-delete enrollments for drop flow; use soft delete status updates.

### 2) Auth dependency rules

- `get_current_user` returns a `Dict[str, Any]`.
- Access user data via dict keys (`current_user.get("user_id")`), not attribute access.

### 3) Enum/query rules

- Use enum `.value` for Mongo queries to avoid serialization issues.

### 4) Endpoint structure

- Follow role/resource pathing:
  - `app/api/v1/endpoints/{role}/{resource}.py`
- Register routers in `app/api/v1/__init__.py`.

## Business Logic Rules (UniPortal)

- Roles: `student`, `admin`.
- Respect first-login password reset flow (`must_reset_password`).
- Enforce major-student checks and major selection gating where relevant.
- Enrollment constraints:
  - 18-credit baseline
  - max 8 subjects
  - retake priority over new subjects
  - odd/even semester parity for retake eligibility
- Admin override capability must remain possible in admin workflows.
- GPA/CGPA behavior must remain consistent with existing grading logic.

## Data Schema Rules

- Treat `data-schemas` as source of truth for:
  - required fields
  - enums
  - inter-collection references
- When uncertain, align endpoint response shapes to current schema objects instead of inventing new fields.
- Keep dynamic/mixed fields typed as `Dict[str, Any]` where required by existing data.

## RAG / AI Rules (MongoDB Atlas Vector Search)

- Always ensure embedding dimensions match Atlas vector index `numDimensions`.
- Document shape must include:
  - `text` (string)
  - `embedding` (numeric array)
  - `metadata` (source and filtering fields)
- Retrieval flow:
  1. embed query
  2. vector search (`$vectorSearch`)
  3. context build
  4. LLM answer
- Tune with `numCandidates`, `limit`, and score controls.
- Log retrieval quality signals (result count, scores, chunk info) for debugging.

## Quality Defaults for New API Work

- Prefer idempotent write logic.
- Validate all user inputs with explicit HTTP errors.
- Keep role checks and ownership checks in endpoints/services.
- Avoid implicit magic behavior; document defaults in code comments.
- For bugfixes, include minimal regression checks or reproducible manual test steps.

## Prompt/Planning Style for Agents

When planning endpoint work, follow this order:
1. Model/collection impact
2. endpoint contract (request/response)
3. service logic and business constraints
4. idempotency and failure modes
5. verification steps (manual + automated where possible)

For student dashboard-type features, default assumptions:
- lazy initialization only if no prior records exist
- no duplicate enrollment creation on repeated requests
- dropped/history records must block accidental re-auto-enroll

## Explicit Do/Don't

Do:
- Use `$set` updates for status transitions.
- Keep collection names explicit in model settings.
- Keep CORS headers permissive enough for configured frontend (`allow_headers=["*"]` pattern when needed).
- Add migration scripts for schema/index/embedding transitions.

Don't:
- Hard-delete enrollment rows in drop flows.
- Break role-based route separation.
- Return empty data because of incorrect collection casing.
- Mix new AI embedding dimensions with old vector index dimensions.

## Fast Troubleshooting Checklist

If API returns 500:
- Check uvicorn logs first.
- Confirm settings/env keys match code expectations.
- Verify model ID type matches actual collection IDs.
- Check enum `.value` usage in queries.
- Confirm Beanie collection naming.

If RAG quality is poor:
- Verify index exists and dimensions match.
- inspect chunking strategy and overlap
- tune `numCandidates` and `limit`
- confirm retrieved context is actually passed as plain text to LLM

