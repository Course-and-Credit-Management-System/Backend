# Plan: Student Course Dashboard API

We will implement the backend support for the "My Courses" page, including the auto-enrollment logic you described.

**Steps**
1.  **Update Course Model**: Modify [app/models/course.py](app/models/course.py) to include `instructor` and `room` fields.
2.  **Create Student Endpoints**:
    *   Create a new folder `app/api/v1/endpoints/student/`.
    *   Create `app/api/v1/endpoints/student/courses.py`.
    *   Implement `GET /current` to:
        *   Check if the student has enrollments for their `current_year`.
        *   **Auto-Enroll**: If no enrollments exist, find all courses for that year/semester and create them.
        *   Return the dashboard data (credits summary + course list) matching your JSON requirements.
3.  **Register Router**: Update [app/api/v1/__init__.py](app/api/v1/__init__.py) to include the new student routes.

**Verification**
*   **Manual Test**: Login as a student and hit the endpoint. Verify that enrollments are created in the database and the JSON response matches your screenshot.
*   **Idempotency**: Verify that refreshing the page (calling the API again) does not duplicate enrollments.

**Decisions**
*   **Max Credits**: I will default `max_credits` to **18** in the response (based on your screenshot). We can make this dynamic later if needed.
*   **Lazy Enrollment**: The enrollment happens automatically on the first `GET` request to minimize setup steps for new users.

Does this plan look correct to you?

