# Backend AI & Enrollment Trial-and-Error Log

## Purpose
Track what was tried, what worked, what failed, and why for backend AI and enrollment behavior changes.  
This prevents repeating the same mistakes and makes future tuning faster.

## Is This Necessary?
Yes, for this project it is necessary to keep this log because both AI behavior and enrollment filtering depend on prompt/mode logic, context assembly, and DB-backed business rules.

Use this log when you change:
- Chat routes or request/response schema
- Mode classification or mode-specific behavior
- Prompt/context assembly logic
- Retrieval strategy, model settings, retry behavior, or rate-limit handling
- Student course filtering/enrollability rules
- Major/track eligibility behavior tied to `students_progress`

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

### Experiment ID: EXP-0008
- Date: 2026-02-16
- Owner: Backend team
- Goal: Fix `/api/v1/student/courses/current` course selection rules for semester + major/track + neutral(common) courses
- Hypothesis: Enrollment dashboard becomes correct when eligibility combines:
  - same semester
  - selected major/track rules from `students_progress`
  - neutral courses (no `major` and no `track`)
  - exclusion of already passed/completed history
- Change:
  - Updated `app/api/v1/endpoints/student/courses.py` (`GET /student/courses/current`)
  - Added `students_progress`-based filtering:
    - major+track: match both
    - major only: match major
    - track only: match track
    - always include neutral/common courses (missing/null/empty `major` and `track`)
  - Kept strict same-semester condition (`semester.semester == student_profile.current_year`)
  - Excluded passed/completed courses using `academic_history` + Enrollment passed/completed statuses
  - Changed auto-enroll behavior to ensure missing eligible semester courses are added even when enrollments already exist
- Data/Prompt/Mode used:
  - N/A (non-chatbot endpoint behavior)
- Result:
  - Quality: Correct current-course list for mixed curriculum (major-specific + common/core semester courses)
  - Latency: Small additional filtering/query overhead, no expected major regression
  - Reliability: Reduced false inclusion/exclusion from earlier conditional logic
- Decision: Keep
- Notes:
  - Earlier edits on `student/academic.py` were reverted because response payload source was `student/courses.py`
  - Canonical schema reference: `.github/skills/data-schemas/SKILL.md`
- Next step:
  - Add integration tests for:
    - major only
    - track only
    - major+track
    - neutral course inclusion
    - passed-history exclusion

### Experiment ID: EXP-0009
- Date: 2026-02-16
- Owner: Backend team
- Goal: Add major filter tokens for `GET /api/v1/student/courses`
- Hypothesis: Allowing `sort=major` and combined `sort=major,enrollable` will reduce frontend-side filtering and ambiguity.
- Change:
  - Updated `app/api/v1/endpoints/student/courses.py` (`GET /student/courses`)
  - `sort` now supports comma-separated tokens:
    - `major`
    - `enrollable`
    - combined `major,enrollable` (or reversed order)
  - Added aliases `type:major` and `course_type:major` for compatibility.
- Data/Prompt/Mode used:
  - N/A (non-chatbot endpoint behavior)
- Result:
  - Quality: Endpoint can now return major-only and major+enrollable subsets directly.
  - Latency: No material impact (in-memory filter over existing response list).
  - Reliability: Backward compatibility kept for existing `sort=enrollable`.
- Decision: Keep
- Notes:
  - Filtered responses are sorted by `code` for deterministic output.
- Next step:
  - Add endpoint tests for `sort=major`, `sort=enrollable`, and `sort=major,enrollable`.

### Experiment ID: EXP-0010
- Date: 2026-02-16
- Owner: Backend team
- Goal: Enforce `selected_major` compatibility for enrollable Major courses
- Hypothesis: For students with `selected_major`, major-type courses from other majors should never appear enrollable.
- Change:
  - Updated `app/api/v1/endpoints/student/courses.py` (`GET /student/courses`)
  - During course search, load student's `selected_major` from `students_progress`
  - Added major-compatibility check in enrollability flow:
    - If `course.type == "Major"` and course `major` is present but differs from student `selected_major`, mark as locked/non-enrollable
- Data/Prompt/Mode used:
  - N/A (non-chatbot endpoint behavior)
- Result:
  - Quality: `sort=enrollable` now excludes major courses that belong to another major.
  - Latency: Minor overhead from raw major lookup map build.
  - Reliability: Existing prerequisite/context/conflict logic remains unchanged.
- Decision: Keep
- Notes:
  - Rule applies only when student has `selected_major`; otherwise previous behavior remains.
- Next step:
  - Add regression tests for:
    - student with `selected_major` + cross-major major-type course
    - student with no `selected_major`

### Experiment ID: EXP-0011
- Date: 2026-02-16
- Owner: Backend team
- Goal: Finalize combined filter semantics for major/enrollable search
- Hypothesis: Accepting common client token formats while enforcing strict AND semantics reduces integration mistakes.
- Change:
  - Updated `app/api/v1/endpoints/student/courses.py` (`GET /student/courses`)
  - `sort` token parser now accepts both `,` and `|` separators
  - Added `enrollment` as alias for `enrollable`
  - Combined filter semantics confirmed as intersection:
    - `major + enrollable` => `type == "Major"` AND `enrollable == true`
  - Confirmed fallback behavior:
    - If student has no `selected_major`, major-name mismatch filtering is not applied
- Data/Prompt/Mode used:
  - N/A (non-chatbot endpoint behavior)
- Result:
  - Quality: Client can send `major,enrollable` or `major|enrollment` and receive identical intended output.
  - Latency: No material impact.
  - Reliability: Maintains backward compatibility with previous `sort=enrollable`.
- Decision: Keep
- Notes:
  - Canonical meaning for combined major/enrollable is strict AND, not OR.
- Next step:
  - Add endpoint tests for token separators and alias handling.

### Experiment ID: EXP-0012
- Date: 2026-02-18
- Owner: Backend team
- Goal: Align special-major access flow with explicit track selection endpoint
- Hypothesis: Adding a dedicated `POST /student/special-major/track` endpoint (instead of reusing major routes) will remove route mismatch errors from the Special Major Access page.
- Change:
  - Updated `app/api/v1/endpoints/student/special_major_access.py`
  - Added `POST /special-major/track`
  - Validation rules:
    - Accept only `CS` or `CT`
    - Allow only `5-year` program
    - Reuse special-major eligibility gates
    - Block track changes after `selected_major` is already set
  - Persistence:
    - `StudentsProgress.selected_track`
    - `Users.student_profile.major_track`
- Data/Prompt/Mode used:
  - N/A (non-chatbot endpoint behavior)
- Result:
  - Quality: Special Major Access flow now has a native track-selection route in its own module.
  - Latency: No material impact (single upsert/update path).
  - Reliability: Reduced integration ambiguity between `/major/track` and `/special-major/*` routes.
- Decision: Keep
- Notes:
  - Existing `POST /student/special-major/select` remains for major selection.
  - New route is `POST /api/v1/student/special-major/track`.
- Next step:
  - Add API tests for:
    - valid track (`CS`, `CT`)
    - invalid track payload
    - non-5-year user
    - already selected major lock
    - ineligible year/semester

## Failure/Issue Log
Use this table for real incidents and regressions.

| Date | ID | Symptom | Root Cause | Fix | Preventive Action |
|---|---|---|---|---|---|
| 2026-02-14 | INC-0001 | Chat payload drift across routes | Extra optional fields in request body | Standardized request schema | Add schema contract check in CI |
| 2026-02-16 | INC-0002 | `/student/courses/current` returned cross-major courses | Eligibility initially checked on wrong endpoint and lacked final filter coupling in active flow | Moved/kept logic in `student/courses.py` and tied to `students_progress` + semester | Add endpoint ownership note in docs and regression tests for route path |
| 2026-02-16 | INC-0003 | Expected common semester core course not shown when student already had enrollments | Standard courses were only auto-added on "fresh start" (`if not existing_course_ids`) | Always add missing eligible semester courses, then dedupe by existing enrollments | Add regression test for partial-existing-enrollment scenario |
| 2026-02-18 | INC-0004 | Special Major Access UI could not complete track selection | Missing dedicated `/student/special-major/track` endpoint; flow depended on a different route contract | Added `POST /student/special-major/track` in `special_major_access.py` with consistent eligibility + persistence | Add endpoint checklist: "UI route exists, request/response contract documented, and module-local endpoint parity verified" |

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
