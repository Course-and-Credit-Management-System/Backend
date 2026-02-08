# Backend API Development Guide & Best Practices

This document documents the specific architectural decisions, common bugs, and fixes encountered during the development of the FastAPI Backend. Refer to this when creating new endpoints to avoid recurring issues.

## 7. Collection Naming Conventions
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

### **Idempotent Auto-Enrollment**
When implementing "auto-create" or "initialization" logic (like enrolling students in courses upon their first visit):
1.  **Do NOT** just check `if not existing_data: create_all()`. This fails if partial data exists.
2.  **Instead**: Fetch all required items, check which ones are missing from the user's records, and create ONLY the missing ones.
    *   Find suitable courses used `In` operator or loop check.
    *   Create `Enrollment` for `course_code` NOT IN existing enrollments.
