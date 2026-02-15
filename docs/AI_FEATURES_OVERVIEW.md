# AI Features Overview

## 1) Scope
This document describes all AI-powered backend features currently implemented in this project:
- AI chatbot endpoints (student/admin/general compatibility)
- Course advisor chat (course-specific analytics)
- AI-assisted enrollment recommendations
- AI-assisted drop-course recommendations
- RAG pipeline (Gemini embeddings + MongoDB Atlas Vector Search)

## 2) High-Level Architecture
Core files:
- `Backend/app/api/v1/endpoints/ai/chatbot.py`
- `Backend/app/api/v1/endpoints/student/courses.py`
- `Backend/app/services/ai_chat_service.py`
- `Backend/app/services/ai_context_service.py`
- `Backend/app/schemas/chatbot.py`
- `Backend/app/core/config.py`

Request flow:
1. Client calls endpoint with JWT-authenticated user.
2. Endpoint applies role guard and validates payload.
3. Service classifies intent (`mode` or auto classification).
4. Service builds structured context from live MongoDB data.
5. For RAG-enabled intents, service:
   - embeds user query via Gemini
   - runs `$vectorSearch` on `KnowledgeBase`
   - merges retrieved chunks with structured context
6. Service calls Gemini chat completion with final context.
7. Endpoint returns answer and optional sources.

## 3) AI Endpoints and Features

### 3.1 Chatbot Endpoints
Base API prefix is `/api/v1`.

AI router currently resolves to:
- `POST /api/v1/ai/ai/student/chat`
- `POST /api/v1/ai/ai/admin/chat`
- `POST /api/v1/ai/ai/chat` (compat route, dispatches by user role)
- `POST /api/v1/ai/ai/student/course-chat` (forces `course_advisor` mode)

Chat request contract (`ChatRequest`):
- `message: str` (required)
- `course_id: str | null` (optional except course-chat)
- `history: [{ role, content }]` (optional)
- `mode`: one of:
  - `auto`
  - `course_selection`
  - `course_stats`
  - `course_advisor`
  - `academic_progress`
  - `major_requirements`
  - `announcements`
  - `policy_general`

Chat response contract:
- `answer: str`
- `sources: [{ text, source, score }]`

### 3.2 Course Enrollment Assistance (AI)
Endpoint:
- `POST /api/v1/student/courses/enrollment-assistance`

Behavior:
- Requires student role.
- Builds list of currently enrollable courses.
- Sends constrained prompt to AI (JSON output required).
- Parses AI JSON recommendations.
- Falls back to deterministic recommendations if AI output is invalid.

### 3.3 Course Drop Recommendation (AI)
Endpoint:
- `GET /api/v1/student/courses/drop-recommendation`

Behavior:
- Requires student role.
- Computes whether current credits exceed limit (18).
- If over limit, asks AI for structured JSON drop plan.
- Enforces business constraints in backend even after AI output:
  - never drop retake courses
  - keep at most one elective
  - minimize dropped courses
- Uses fallback deterministic plan when AI is unavailable/invalid.
- Uses short-term cache and cooldown to reduce repeated provider calls.

## 4) Context and RAG Strategy

### 4.1 Structured Context
`ai_context_service.py` builds role-scoped, intent-aware data such as:
- Student/admin profile context
- Academic history and enrollment summary
- Course statistics and catalog samples
- Major requirements
- Announcements
- Admin student operational summaries
- Course advisor aggregates (enrolled/passed/failed/grade distributions/fit signals)

### 4.2 RAG Retrieval
`ai_chat_service.py` performs:
- `embed_texts(...)` via Gemini embeddings endpoint
- `vector_search_knowledge(...)` on MongoDB `KnowledgeBase`
- source extraction and context assembly

RAG usage is intent-dependent:
- Usually enabled for `course_selection`, `major_requirements`, `announcements`, `policy_general`
- Usually disabled for highly user-specific intents like `academic_progress` and `course_advisor`

## 5) What Is Required to Run AI Features

### 5.1 Required Python Dependencies
From `Backend/requirements.txt`:
- `fastapi`, `uvicorn`
- `motor`, `beanie`
- `httpx`
- `pydantic`, `pydantic-settings`
- `python-jose[cryptography]` for auth

For document ingestion scripts:
- `pypdf` (already listed)

### 5.2 Required Environment Variables
Minimum AI-specific and runtime-critical keys in `.env`:
- `MONGODB_URL`
- `MONGODB_DB_NAME`
- `JWT_SECRET_KEY`
- `GEMINI_API_KEY`

Recommended AI config (defaults exist but should be explicit):
- `GEMINI_API_BASE`
- `GEMINI_CHAT_MODEL`
- `GEMINI_CHAT_FALLBACK_MODEL`
- `GEMINI_EMBEDDING_MODEL`
- `EMBEDDING_DIMENSIONS`
- `EMBEDDING_BATCH_SIZE`
- `GEMINI_MAX_RETRIES`
- `GEMINI_RETRY_BASE_SECONDS`
- `GEMINI_RETRY_MAX_SECONDS`
- `GEMINI_MAX_CONCURRENT_REQUESTS`
- `GEMINI_MIN_REQUEST_INTERVAL_SECONDS`
- `AI_RAG_K`
- `AI_RAG_NUM_CANDIDATES`
- `AI_RAG_SCORE_THRESHOLD`
- `KNOWLEDGE_BASE_COLLECTION`
- `KNOWLEDGE_VECTOR_INDEX_NAME`

### 5.3 Database Requirements
Collections used by AI context/retrieval include:
- `Users`
- `Courses`
- `Enrollments`
- `Majors`
- `Announcements`
- `KnowledgeBase` (for RAG)

### 5.4 Atlas Vector Index Requirement
`KnowledgeBase` must have a vector search index on `embedding` whose dimensions match `EMBEDDING_DIMENSIONS`.

Example shape:
```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 1536,
      "similarity": "cosine"
    }
  ]
}
```

If dimensions mismatch, retrieval will fail or produce invalid behavior.

### 5.5 Auth/Role Requirement
AI endpoints depend on authenticated user context:
- Student-only routes require `role=student`
- Admin-only routes require `role=admin`
- Compatibility route dispatches by role

## 6) Knowledge Base Operations

### 6.1 Ingest New Documents
Script:
- `Backend/scripts/ingest_charter_pdf.py`

Examples:
```powershell
cd Backend
python -m scripts.ingest_charter_pdf
python -m scripts.ingest_charter_pdf "C:\path\to\docs" --chunk-size 1000 --overlap 150
```

### 6.2 Re-embed Existing Documents
Script:
- `Backend/scripts/reembed_knowledge_base.py`

Examples:
```powershell
cd Backend
python -m scripts.reembed_knowledge_base --dry-run
python -m scripts.reembed_knowledge_base
python -m scripts.reembed_knowledge_base --limit 100
```

Use re-embedding when:
- embedding model changes
- embedding dimensions change
- chunking strategy changed and data was re-written

## 7) Local Run Checklist
1. Create `.env` with MongoDB + JWT + Gemini keys.
2. Ensure MongoDB collections exist and contain baseline data.
3. Ensure `KnowledgeBase` vector index exists and matches embedding dimension.
4. Install dependencies:
   - `pip install -r requirements.txt`
5. Run API:
   - `uvicorn app.main:app --reload`
6. Test AI endpoints with valid student/admin JWT tokens.

## 8) Known Operational Risks
- Rate limiting from Gemini (handled with retries/throttle/cooldown).
- Large admin context payloads may increase latency.
- Retrieval quality depends on chunk quality and vector index correctness.
- Incorrect collection naming/casing can silently degrade context.

## 9) Suggested Validation Before Production
1. Verify all AI routes with both success and error-path tests.
2. Validate role-guard behavior (`403` for wrong role).
3. Validate missing config behavior (`500` for missing Gemini key/model).
4. Load test admin AI queries with realistic student counts.
5. Run a small canary prompt set and compare answers release-to-release.
