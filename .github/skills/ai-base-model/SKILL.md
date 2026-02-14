---
name: ai-base-model
description: Standard workflow for adding new AI chatbot features by extending the shared base-model orchestration (context + mode + realtime + RAG) without duplicating pipelines.
---

# AI Base Model Skill

Use this skill when implementing new chatbot features that should reuse the existing AI pipeline instead of creating separate ad-hoc logic.

## Goal
Keep one orchestration path and extend behavior through:
- `mode` routing
- structured context builders
- realtime context enrichers
- optional RAG retrieval tuning

## Primary Files
- `app/services/ai_chat_service.py`
- `app/services/ai_context_service.py`
- `app/api/v1/endpoints/ai/chatbot.py`
- `app/schemas/chatbot.py`

## Rules
1. Do not create parallel chatbot engines for each feature.
2. Add new behavior via `mode` and context functions first.
3. Keep request payload minimal: `message`, `history`, `mode`.
4. Role context comes from auth (`current_user`), not request body IDs.
5. For admin features, enrich context in service layer, not endpoint hacks.
6. Preserve role route separation:
   - `/student/chat`
   - `/admin/chat`
   - `/chat` compatibility dispatch

## Implementation Workflow

### 1) Define intent behavior
- Decide if feature is:
  - a new `mode`, or
  - an extension of an existing mode.
- Update `ChatRequest.mode` enum in `app/schemas/chatbot.py` if needed.

### 2) Wire intent classification
- Update `_classify_intent(...)` in `app/services/ai_chat_service.py`.
- Keep `mode != "auto"` as explicit override.

### 3) Extend structured context
- Add/extend context builders in `app/services/ai_context_service.py`.
- Prefer small focused functions:
  - `_build_*_context(...)`
  - `_search_*_realtime(...)`
  - `_build_*_counts_realtime(...)`

### 4) Decide RAG policy
- Use `_should_use_rag(intent)` for intent-level control.
- Apply retrieval filters where needed (e.g., announcements).
- Keep direct DB fact intents mostly structured-first.

### 5) Keep endpoint thin
- Endpoint should only:
  - validate payload
  - enforce role guard
  - call `chat_with_student_model(...)` or `chat_with_admin_model(...)`
- No business logic in endpoint.

### 6) Validate
- Compile touched files:
  - `python -m compileall app/schemas/chatbot.py app/api/v1/endpoints/ai/chatbot.py app/services/ai_chat_service.py app/services/ai_context_service.py`
- Run or add tests for:
  - mode routing
  - role guard behavior
  - context keys present for new feature

## Anti-Patterns (Do Not)
- Add request-only identity fields (`user_id`, `student_id`, `target_student_id`) for core routing.
- Duplicate prompt orchestration in endpoint or separate service file.
- Force RAG for intents requiring precise real-time DB facts.

## Done Criteria
- Feature works via base model path.
- No payload bloat.
- Role behavior is explicit and testable.
- Changes documented in `docs/AI_CHATBOT_TRIAL_AND_ERROR_LOG.md`.

