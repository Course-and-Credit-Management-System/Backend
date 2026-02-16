# AI Chatbot Trial-and-Error Log

## Purpose
Track what was tried, what worked, what failed, and why for AI chatbot development.  
This prevents repeating the same mistakes and makes future tuning faster.

## Is This Necessary?
Yes, for this project it is necessary to keep this log because chatbot behavior depends on prompts, mode routing, context building, and provider reliability.

Use this log when you change:
- Chat routes or request/response schema
- Mode classification or mode-specific behavior
- Prompt/context assembly logic
- Retrieval strategy, model settings, retry behavior, or rate-limit handling

## Current Architecture Snapshot
- API routes:
  - `POST /api/v1/ai/ai/student/chat`
  - `POST /api/v1/ai/ai/admin/chat`
  - `POST /api/v1/ai/ai/chat` (compat route, dispatch by role)
  - `POST /api/v1/ai/ai/student/course-chat` (forces `course_advisor` mode)
- Core orchestration:
  - `app/services/ai_chat_service.py`
- Structured context builders:
  - `app/services/ai_context_service.py`
- Request shape:
  - `message`, `history`, `mode`, `course_id` (optional except for course advisor route)
- Mode values:
  - `auto`, `course_selection`, `course_stats`, `course_advisor`, `academic_progress`, `major_requirements`, `announcements`, `policy_general`

## Success Metrics (track every change)
- Answer quality:
  - Correctness (manual score 1-5)
  - Hallucination rate (%)
  - Groundedness (uses context correctly, yes/no)
- Retrieval quality:
  - Relevant chunks in top-k (%)
  - Score distribution (`min`, `avg`, `max`)
- Runtime:
  - P50/P95 response time
  - Token usage (if available)
- Reliability:
  - Error rate by type (HTTP 5xx, timeout, provider errors)

## Experiment Template
Copy this block for each trial:

```md
### Experiment ID: EXP-XXXX
- Date:
- Owner:
- Goal:
- Hypothesis:
- Change:
- Data/Prompt/Mode used:
- Result:
  - Quality:
  - Latency:
  - Reliability:
- Decision: Keep / Revert / Partial
- Notes:
- Next step:
```

## Initial Trials Logged (based on current implementation)

### Experiment ID: EXP-0001
- Date: 2026-02-14
- Owner: Backend team
- Goal: Separate student/admin chat behavior safely
- Hypothesis: Role-specific routes reduce accidental context leakage and simplify frontend integration
- Change:
  - Added `/student/chat` and `/admin/chat`
  - Kept `/chat` compatibility route with role dispatch
- Data/Prompt/Mode used:
  - Existing mode system
  - Same request shape for both routes
- Result:
  - Quality: Improved control of role behavior
  - Latency: No major change expected
  - Reliability: Improved route-level role guard
- Decision: Keep
- Notes: Keep frontend and backend route mapping explicit
- Next step: Add route-level integration tests for role mismatch (403)

### Experiment ID: EXP-0002
- Date: 2026-02-14
- Owner: Backend team
- Goal: Make admin chat include broader operational context
- Hypothesis: Admin answers improve if context includes all students' academic data + realtime counters
- Change:
  - Admin context now includes `students_academic_data` from `Users`
  - Realtime helpers include student search/count behavior
- Data/Prompt/Mode used:
  - `include_admin_student_data=True` in admin orchestration
- Result:
  - Quality: Better admin-side operational answers expected
  - Latency: May increase with large student volume
  - Reliability: Works; needs load validation
- Decision: Keep with monitoring
- Notes:
  - Potential prompt bloat risk if user base grows
  - Consider summarization/caching if latency rises
- Next step:
  - Benchmark with realistic student counts
  - Add guardrails for context size

### Experiment ID: EXP-0003
- Date: 2026-02-14
- Owner: Backend team
- Goal: Keep request contract simple
- Hypothesis: Removing extra request fields lowers client confusion and integration bugs
- Change:
  - Removed request fields not needed from client payload (`user_id`, `student_id`, `target_student_id`)
  - Standardized on `message`, `history`, `mode`
- Data/Prompt/Mode used:
  - All modes
- Result:
  - Quality: Unchanged
  - Latency: Unchanged
  - Reliability: Better contract consistency
- Decision: Keep
- Notes: Identity and role come from auth context, not body payload
- Next step: Update frontend typing to enforce minimal payload

### Experiment ID: EXP-0004
- Date: 2026-02-14
- Owner: Backend team
- Goal: Add course-specific chatbot answers grounded in live enrollment analytics
- Hypothesis: A dedicated course advisor mode with `course_id` + enrollment aggregates improves factual answers for "enrolled/passed/failed/average grade/suitability" prompts
- Change:
  - Added `course_advisor` mode
  - Added `course_id` in chat request payload
  - Added `POST /api/v1/ai/ai/student/course-chat`
  - Added structured context builder joining `Courses` + `Enrollments` with student-fit signals
- Data/Prompt/Mode used:
  - Request body with `course_id`, `message`, optional `history`
  - `mode="course_advisor"` for dedicated endpoint
- Result:
  - Quality: Expected improvement for direct course analytics and suitability questions
  - Latency: Slight increase due to aggregation queries
  - Reliability: Uses existing base-model orchestration and role guard
- Decision: Keep
- Notes:
  - Prefer structured context over RAG for this mode to avoid stale/non-factual KB snippets
  - Enrollment data is aggregated from `Enrollments` using exact case-sensitive collection names
- Next step:
  - Add integration tests for missing `course_id`, unknown course, and distribution calculations

### Experiment ID: EXP-0005
- Date: 2026-02-14
- Owner: Backend team
- Goal: Add AI-guided drop-course recommendation when student exceeds 18 credits
- Hypothesis: Reusing base student model with strict JSON output + deterministic fallback can provide stable frontend-ready recommendations
- Change:
  - Added `GET /api/v1/student/courses/drop-recommendation`
  - Endpoint consumes current enrollment from existing `/api/v1/student/courses/current` flow
  - Response shape includes:
    - `elective` (single recommended elective drop for radio UI)
    - `others` (multiple additional suggested drops)
    - `reason` per suggested course
  - Enforced business constraints:
    - Keep at most one elective
    - Minimize number of dropped courses
    - Do not suggest unnecessary extra drops once credits are under limit
- Data/Prompt/Mode used:
  - `mode="course_selection"` through `chat_with_student_model(...)`
  - Structured candidate list from current enrolled courses
- Result:
  - Quality: Structured output for frontend controls
  - Latency: Similar to other student AI assistance endpoints
  - Reliability: Fallback plan ensures valid response even when AI output is malformed
- Decision: Keep
- Notes:
  - If total credits do not exceed 18, endpoint returns empty recommendations with a friendly message
- Next step:
  - Add integration tests for over-limit, exactly-18, and multiple-elective scenarios

### Experiment ID: EXP-0006
- Date: 2026-02-15
- Owner: Backend team
- Goal: Remove hardcoded enrollment control and make admin-configured singleton setting authoritative
- Hypothesis: A single enrollment-settings document with explicit status + time window reduces ambiguity and admin friction
- Change:
  - Added singleton admin settings endpoints:
    - `POST /api/v1/admin/enrollment-settings` (replace existing)
    - `GET /api/v1/admin/enrollment-settings`
    - `PUT /api/v1/admin/enrollment-settings` (upsert)
    - `PATCH /api/v1/admin/enrollment-settings/status`
  - Added student settings read endpoint:
    - `GET /api/v1/student/enrollment/settings/current`
  - Removed semester/year and policy/drop-deadline complexity from settings contract
  - Added duration controls:
    - `window_minutes` (testing)
    - `window_days` (real operations)
  - Enrollment open time is server current time; close time is computed from selected window
  - `status=closed` now hard-blocks enrollment (`403`) regardless of time window
- Data/Prompt/Mode used:
  - N/A (non-chatbot control-plane behavior)
- Result:
  - Quality: Admin flow simplified to one object, no id management
  - Latency: No material impact
  - Reliability: Enrollment gating became deterministic and test-verified
- Decision: Keep
- Notes:
  - Backward fallback is only for missing setting document; if singleton exists and is closed, enrollment is blocked
  - Added endpoint-level test coverage for closed-window and closed-status paths
- Next step:
  - Add frontend admin page using singleton contract only

### Experiment ID: EXP-0007
- Date: 2026-02-15
- Owner: Backend team
- Goal: Fix enrollment window false-expiry due to timezone mismatch
- Hypothesis: Naive Mongo datetimes interpreted as local time can shift windows and trigger incorrect `Enrollment period is closed` responses
- Change:
  - Added app timezone configuration: `APP_TIMEZONE` (default `Asia/Yangon`)
  - Added timezone utility normalization for enrollment setting timestamps
  - Naive DB datetimes are now treated as UTC and converted into app timezone before enforcement
  - Enrollment setting API responses are normalized to app timezone
- Data/Prompt/Mode used:
  - N/A (control-plane/time handling)
- Result:
  - Quality: Enrollment time display aligns with admin local time
  - Latency: No material impact
  - Reliability: Removed false "closed" rejections for active windows
- Decision: Keep
- Notes:
  - Student enrollment guard continues to enforce `is_active` + time window
  - Closed status remains a hard block independent of time
- Next step:
  - Ensure frontend renders timestamps without unintended client-side timezone shifts

## Failure/Issue Log
Use this table for real incidents and regressions.

| Date | ID | Symptom | Root Cause | Fix | Preventive Action |
|---|---|---|---|---|---|
| 2026-02-14 | INC-0001 | Chat payload drift across routes | Extra optional fields in request body | Standardized request schema | Add schema contract check in CI |

## Known Risks
- Admin context size can grow too large as student records increase.
- Realtime student search/count may add DB load on high query volume.
- Mode classification in `auto` can still misroute edge-case queries.

## Mitigation Plan
1. Add context size cap and truncation strategy for admin context.
2. Add cached aggregate metrics for frequent admin count queries.
3. Add test suite for `mode` behavior and role route behavior.
4. Add canary prompts for regression checks before deployment.

## Weekly Review Checklist
- Top 10 failed prompts reviewed?
- Any hallucination incident logged with root cause?
- Any latency regression over 20% week-over-week?
- Any schema/route contract drift with frontend?
- Any new experiment documented with decision?
