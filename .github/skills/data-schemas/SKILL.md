---
name: data-schemas
description: Formal definition of MongoDB collections, field constraints, enums, and entity relationships for UniPortal.
---

# Data Schemas: UniPortal

This skill defines the source-of-truth for the MongoDB database layer. All frontend types and API endpoints must adhere strictly to these schema definitions.

## 1. User & Authentication

### User Collection
The `User` collection is polymorphic. Depending on the `role`, it requires either `student_profile` or `admin_profile`.

**Common Fields:**
| Field | Type | Description |
| :--- | :--- | :--- |
| `_id` | ObjectId | System ID |
| `user_id` | String | Unique Identifier (e.g., `TNT-8801`, `ADM-001`) |
| `name` | String | Full Name |
| `email` | String | Contact Email |
| `avatar` | String | URL to profile image |
| `role` | Enum | `'student'`, `'admin'` |
| `created_at` | Date | Account creation timestamp |

**Role-Specific: Student Profile**
*Required if role is 'student'*
| Field | Type | Constraints/Enums |
| :--- | :--- | :--- |
| `major_id` | String | Reference to **Majors** collection |
| `academic_status` | Enum | `'Active'`, `'Probation'`, `'Suspended'`, `'Graduated'`, `'majorChange'` |
| `total_credits` | Int | Min: 0 |
| `advisor_id` | String | User ID (Admin) |
| `is_major_student`| Boolean | True if officially declared |
| `gpa` | Double | Min: 0, Max: 4 |
| `cgpa` | Double | Min: 0, Max: 4 |
| `current_sem_earned_credits` | Int | Credits this semester |
| `total_credits_completed` | Int | All-time earned credits |
| `current_year` | Enum | See **Year Enum Dictionary** below |

**Role-Specific: Admin Profile**
*Required if role is 'admin'*
| Field | Type | Constraints/Enums |
| :--- | :--- | :--- |
| `department` | String | Administrative department |
| `access_level` | Enum | `'super_admin'`, `'registrar'`, `'instructor'` |
| `permissions` | Array | `['manage_courses', 'grade_students', 'approve_enrollment']` |

**Embedded Histories:**
*   **Academic History**: Array of `{ course_id, course_code, course_title, semester, credits, grade, status }`.
*   **Major History**: Array of `{ major_name, status, start_term, end_term, major_id }`.

### UserAuth Collection
Separated for security.
| Field | Type | Notes |
| :--- | :--- | :--- |
| `user_id` | String | Links to `User.user_id` |
| `password_hash` | String | Argon2id hash |
| `must_reset_password` | Boolean | `true` for initial default passwords |

---

## 2. Academic Core

### Majors Collection
| Field | Type | Notes |
| :--- | :--- | :--- |
| `_id` | String | Manual Code ID (e.g., "SE", "CS") |
| `major_name` | String | Full Name |
| `department` | String | Owning department |
| `requirements` | Array | List of required `course_id` strings |

### Course Collection
| Field | Type | Description |
| :--- | :--- | :--- |
| `course_code` | String | e.g., "CST-1010" |
| `title` | String | Course Name |
| `credits` | Number | Min: 0.5, Max: 6.0 |
| `type` | Enum | `'Core'`, `'Elective'`, `'Prerequisite'`, `'Major'` |
| `semester` | Array | Array of objects: `[{ semester: "String" }]` |
| `major_specific` | Boolean | If true, restricted to declared majors |
| `prerequisites` | Array | List of `course_code` strings |
| `schedule` | Array | `["Mon 10:00-11:30"]` |
| `syllabus` | Array | `[{ week: Int, topic: String }]` |

---

## 3. Enrollment & Grading

### Enrollment Collection
Tracks a student's relationship with a course for a specific term.

| Field | Type | Description |
| :--- | :--- | :--- |
| `student_id` | String | Ref to User |
| `course_id` | String | Ref to Course |
| `semesterAttend` | String | e.g., "First Year, First Sem(old)" |
| `is_retake` | Boolean | Flag for repeat attempts |
| `status` | Enum | `'Enrolled'`, `'Pending'`, `'Conflict'`, `'Waitlisted'`, `'Completed'`, `'Dropped'`, `'Withdrawn'`, `'Failed'`, `'Passed'` |
| `grade` | Enum | `'A+'`, `'A'`, `'A-'`, `'B+'`, `'B'`, `'B-'`, `'C+'`, `'C'`, `'D'`, `'F'`, `'W'`, `'I'`, `'U'`, `'Abs'` |
| `points` | Number | Grade points for GPA (e.g., 4.0, 2.33) |
| `scores` | Number | Raw numeric score (e.g., 85.5) |

---

## 4. Communication

### Announcements Collection
| Field | Type | Constraints |
| :--- | :--- | :--- |
| `type` | Enum | `'General'`, `'Urgent'`, `'Event'`, `'Academic'` |
| `target_audience` | Enum | `'All'`, `'Students'`, `'Faculty'`, `'Computer Science Dept'`, `'Seniors'` |
| `expiry_date` | Date | Nullable. If null, never expires. |
| `posted_by` | String | Admin ID |

### Messages Collection
| Field | Type | Constraints |
| :--- | :--- | :--- |
| `category` | Enum | `'General'`, `'Warning'`, `'Advisor Note'`, `'Enrollment Issue'` |
| `is_read` | Boolean | For UI badges |
| `sender_id` | String | Admin ID |
| `receiver_id` | String | Student ID |

---

## Reference Dictionaries

### Year & Semester Enum (Crucial)
This specific format must be used for `current_year` and `semesterAttend`.

```typescript
type AcademicYear = 
  | '1st Year, First Sem(new)' | '1st Year, Second Sem(new)'
  | '2nd Year, First Sem(new)' | '2nd Year, Second Sem(new)'
  | '3rd Year, First Sem(new)' | '3rd Year, Second Sem(new)'
  | '4th Year, First Sem(new)' | '4th Year, Second Sem(new)'
  | '1st Year, First Sem(old)' | '1st Year, Second Sem(old)'
  | '2nd Year, First Sem(old)' | '2nd Year, Second Sem(old)'
  | '3rd Year, First Sem(old)' | '3rd Year, Second Sem(old)'
  | '4th Year, First Sem(old)' | '4th Year, Second Sem(old)'
  | '5th Year, First Sem(old)' | '5th Year, Second Sem(old)';
```
