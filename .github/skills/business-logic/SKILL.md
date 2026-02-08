---
name: business-logic
description: Guidelines and rules for the UniPortal & UniAdmin CMS business domain, including enrollment workflows, role-based access, and security mandates.
---

# Business Logic: UniPortal & UniAdmin CMS

This skill covers the core domain logic for the University Portal. It should be used when implementing or modifying features related to academic workflows, user permissions, and institutional reporting.

## Core Concepts

### 1. Unified Authentication & Authorization
- **Roles**: System supports `student` and `admin` roles.
- **Initial State**: Default initial passwords require an immediate reset upon first login (`must_reset_password` flag).
- **Major Verification**: The system must verify if a user is a `major_student`. Non-major students must perform a **Major Selection** before enrolling in specialized courses.

### 2. Subject Classifications
Courses are categorized into four types:
- **Core**: Mandatory for the primary degree.
- **Elective**: Optional subjects based on interest.
- **Prerequisite**: Must be "Completed" before advanced level registration.
- **Retake**: Previously failed or repeating for GPA. **Highest Priority in enrollment.**

### 3. Academic Constraints & Enrollment Logic
- **Credit Limits**: Standard load is **18 credits** per semester.
- **Subject Limits**: Maximum of **8 subjects** per semester.
- **Failure Penalty**: If a student fails 3 subjects in a semester, they are limited to **5 new subjects** in the next cycle (Total 8: 3 retakes + 5 new).
- **Priority Logic**: Students must prioritize Retake Subjects over Core or Electives.
- **Sequence Handling**: 
  - **Term Parity Rule**: Retake courses are season-dependent. A course failed in an **Odd Semester** (First Sem) can only be retaken in a subsequent **Odd Semester**. Same applies for Even Semesters.
  - *Example*: Fail in Sem 1 -> Retake in Sem 3 (not Sem 2).
- **Conflict Resolution**: If enrollment exceeds 18 credits, a **Trade-off Decision** module is triggered.

### 4. Grading & History
- **Enrollment Persistence (Soft Delete)**: 
  - **CRITICAL**: Enrollments are never hard-deleted from the database during a "Drop" action.
  - **Action**: Set `status = "Dropped"`.
  - **Reason**: Hard deletion causes the Auto-Enroller to detect the course as "missing" and erroneously re-enroll the student immediately.
- **Grade Replacement**: New grades update the student's overall GPA.
- **Formulas**: 
  - `Grade Points Earned = Grade Points × Credits Earned`.
  - GPA/CGPA is automatically calculated upon admin mark entry.
- **History Tracking**: Maintain separate records for **Completed** (Passed) and **Learned** (Attempted) courses.

### 5. AI & Smart Features
- **Smart Recommendation**: Advises students on credit selection based on their `major_id`.
- **Trade-off Assistant**: AI agent helping resolve credit conflicts (18+ credits).
- **Course Agents**: Dedicated agents providing course-specific meta-information.

### 6. System Architecture (Task Decomposition)
- **Orchestrator**: Routes user requests to sub-modules.
- **Validator**: Enforces credit limits and prerequisite checks.
- **Conflict Resolver**: Manages the "Trade-off" logic.

## Implementation Guidelines

- **Data Integrity**: Admins use Excel Bulk Upload or manual entry. Role/Major verification must be enforced at the API level.
- **Admin Overrides**: Administrators have the authority to manually override student enrollment confirmations.
- **Exports**: Academic results and schedules must be supported as PDF exports.

## Key Files
- [types.ts](types.ts): Domain entity definitions.
- [lib/api.ts](lib/api.ts): Backend integration points.
- [App.tsx](App.tsx): Route-level authorization logic.
