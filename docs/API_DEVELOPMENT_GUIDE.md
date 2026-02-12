# Backend API Development Guide & Best Practices

This document documents the specific architectural decisions, common bugs, and fixes encountered during the development of the FastAPI Backend. Refer to this when creating new endpoints to avoid recurring issues.

## 0. Collection Naming Conventions
**CRITICAL:** ALL collection names must be **TitleCase** and match the existing database schema exactly. The database is case-sensitive.
-   **Enrollments** (not `enrollment` or `enrollments`)
-   **Courses** (not `courses`)

If you use default Beanie behavior (snake_case), queries will return empty results because the collections won't be found.



## 1. Database Persistence (Beanie & MongoDB)

### **Handling Custom String IDs**
By default, Beanie expects MongoDB `_id` fields to be `ObjectId`. Since our legacy data or seeded data uses string IDs (e.g., `"c_101"`, `"auth_01"`), we **must** explicitly define the `id` field in every `Document` model.

**❌ Incorrect (Will fail validation):**
```python
class Course(Document):
    # Beanie assumes _id is PydanticObjectId
    course_code: str
```

**✅ Correct:**
```python
class Course(Document):
    # Tell Beanie _id is a string
    id: Optional[str] = Field(default=None, alias="_id")
    course_code: str
```

### **Collection Names**
Beanie converts model names to snake_case by default. If your existing MongoDB collections are PascalCase (e.g., `Courses`, `Users`), you must override it in valid `Settings`.

```python
class Settings:
    name = "Courses"  # Match the exact collection name in MongoDB
    indexes = ["course_code"]
```

## 2. Authentication & User User Dependency

### **Current User Object Type**
The dependency `get_current_user` returns a **Python Dictionary**, NOT a Pydantic Model. This is because we fetch raw data for performance or verify structure manually.

**❌ Incorrect (Attribute Access):**
```python
# Will raise AttributeError: 'dict' object has no attribute 'student_profile'
year = current_user.student_profile.current_year
```

**✅ Correct (Dictionary Access):**
```python
# Access fields using dict syntax
profile = current_user.get("student_profile", {})
year = profile.get("current_year")
```

## 3. Enums in Database Queries

MongoDB drivers do not automatically serialize Python `Enum` objects to their string values. You must extract the value manually before querying.

**❌ Incorrect:**
```python
# MongoDB driver error: cannot encode object ...
await Enrollment.find(Enrollment.status == EnrollmentStatus.ENROLLED)
```

**✅ Correct:**
```python
# Pass the string value
await Enrollment.find(Enrollment.status == EnrollmentStatus.ENROLLED.value)
```

## 4. CORS Issues

If using `allow_credentials=True`, you cannot set `allow_origins=["*"]`. You must specify exact domains.
However, to fix "header not allowed" errors during local dev:

```python
allow_headers=["*"]  # Allow all headers (Content-Type, Authorization, etc.)
```

## 5. Directory Structure for Endpoints

Follow the existing pattern for new features:
*   `app/api/v1/endpoints/{role}/{resource}.py`
    *   Example: `app/api/v1/endpoints/student/courses.py`
*   Register new routers in `app/api/v1/__init__.py`.

## 6. Debugging 500 Errors
If the API returns "Internal Server Error" without a clear valid traceback in the HTTP response:
1.  Check the `uvicorn` terminal output.
2.  Common causes:
    *   `AttributeError`: Accessing dict keys as attributes.
    *   `ValidationError`: Beanie model ID mismatch.
    *   `ModuleNotFoundError`: Missing `__init__.py` or circular imports.

## 7. Business Logic Implementation

### **Data Structures inside Models**
If a field structure is dynamic or mixed (like `semester` containing boolean flags alongside string values), avoid strict typing like `List[Dict[str, str]]`.
Use `List[Dict[str, Any]]` instead to prevent `ValidationError` on read.

### **Idempotent Auto-Enrollment & Re-Enrollment Prevention**
When implementing "auto-create" or "initialization" logic (like enrolling students in courses upon their first visit):

1.  **Check for Prior Interactions**: Before auto-enrolling, check if the student has *any* records (Active, Dropped, Failed, etc.).
    *   If **ZERO records** exist: Safe to Auto-Enroll.
    *   If **ANY records** exist (even if count < expected): Do **NOT** auto-enroll. The student might have manually dropped a course. Auto-enrolling would disrespect their decision.

2.  **Logic Pattern**:
    ```python
    existing_enrollments = await Enrollment.find(student_id=...).to_list()
    if not existing_enrollments:
        # User is brand new -> Enroll in all default courses
        await enroll_in_all(defaults)
    else:
        # User has history -> Do nothing (or only add strictly new curriculum changes, care required)
    ```

## 8. Enrollment Dropping Logic
**CRITICAL:** Never **Hard Delete** enrollment records.

**❌ Incorrect:**
```python
await Enrollment.find(...).delete()
```
*   **Result:** The record vanishes. The "Auto-Enrollment" logic (see #7) sees a "missing" course and immediately re-enrolls the student on next refresh.

**✅ Correct (Soft Delete):**
```python
await Enrollment.find(...).update({"$set": {"status": EnrollmentStatus.DROPPED}})
# And filter out DROPPED records in your GET /dashboard endpoints.
```
*   **Result:** The "tombstone" record persists. The Auto-Enroll logic sees the record exists (so it doesn't re-enroll), but the UI hides it because of the status filter.


## 9. Course Enrollment & Business Rules

### **Filters & Sorting**
- **Filtering**: Server-side string searching (`q`) is removed; search is handled by frontend.
- **Sorting**: `sort="enrollable"` is a strict filter.
  - **Action**: Returns ONLY courses where `enrollable: true`.
  - **Ordering**: Alphabetical by `code`.

### **Validation Rules (Parity & Version)**
To determine if a user can enroll (Status: "normal"):
1.  **Parity Match**: 
    -   If User Profile is "First Sem" -> Can only enroll in "First Sem" (matches "1st Sem" etc) courses.
    -   If User Profile is "Second Sem" -> Can only enroll in "Second Sem" (matches "2nd Sem" etc) courses.
    -   *Message if Closed*: `"this course has been closed"`.
2.  **Version Match**:
    -   If User Profile is "(new)" -> Course must match "(new)" or be version-agnostic.
    -   If User Profile is "(old)" -> Course must match "(old)" or be version-agnostic.
    -   *Message if Mismatch*: `"this course is for old student"` or `"this course is for new student"`.

### **"Already Taken" vs "Failed"**
A course is considered **"Already Taken"** if it exists in the user's Global Academic History (regardless of status).

**Enrollable Boolean Calculations (`enrollable`):**
| Status in History | `enrollable` | Message |
| :--- | :--- | :--- |
| **Passed / Completed** | `false` | `"this course is already been taken"` |
| **Failed / F** | `true` | *None* (Retake allowed) |
| **No Status** (Legacy) | `false` | `"this course is already been taken"` |
| **Not in History** | `true` (if Valid Context) | *None* |

### **Priority of Messages**
1.  **"Already Taken"**: Always shown first if the course exists in history.
2.  **"Closed / Version Mismatch"**: Shown if not taken, but context prevents enrollment.
