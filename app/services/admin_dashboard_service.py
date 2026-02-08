from __future__ import annotations

from typing import Any

from app.core.database import get_database


class AdminDashboardService:
    def __init__(self, db):
        self.db = db
        self.users = db["Users"]
        self.enrollments = db["Enrollments"]
        self.majors = db["Majors"]
        self.major_histories = db["MajorHistories"]
        self.courses = db["Courses"]
        self.auth_credentials = db["AuthCredentials"]

    @classmethod
    async def create(cls) -> "AdminDashboardService":
        db = await get_database()
        return cls(db)

    async def statistics(self) -> dict[str, Any]:
        total_students = await self.users.count_documents({"role": "student"})

        graduated_count = await self.users.count_documents(
            {"role": "student", "student_profile.academic_status": "Graduated"}
        )

        retake_requirement = await self.enrollments.count_documents(
            {
                "is_retake": True,
                "status": {"$in": ["Pending", "Enrolled", "Conflict", "Waitlisted"]},
            }
        )

        # Average GPA (safe even if some students don't have it)
        pipeline = [
            {"$match": {"role": "student", "student_profile.gpa": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": None, "avgGpa": {"$avg": "$student_profile.gpa"}}},
        ]
        res = await self.users.aggregate(pipeline).to_list(length=1)
        avg_gpa = float(res[0]["avgGpa"]) if res and res[0].get("avgGpa") is not None else 0.0

        return {
            "totalStudents": total_students,
            "graduatedCount": graduated_count,
            "retakeRequirement": retake_requirement,
            "averageGPA": round(avg_gpa, 2),
        }

    async def major_distribution(self) -> list[dict[str, Any]]:
        """
        Your DB has:
        - Majors: _id = "CS", major_name = "Computer Science"
        - MajorHistories: major_id = "MAJ-CS-001", major_name = "B.S. Computer Science"
        Users may store either:
        - student_profile.major_id = "CS" (matches Majors._id)
        OR
        - student_profile.major_id = "MAJ-CS-001" (matches MajorHistories.major_id)
        So we resolve names with a 2-step lookup.
        """
        pipeline = [
            {"$match": {"role": "student", "student_profile.major_id": {"$exists": True, "$ne": None, "$ne": ""}}},
            {"$group": {"_id": "$student_profile.major_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        rows = await self.users.aggregate(pipeline).to_list(length=200)

        output: list[dict[str, Any]] = []
        for r in rows:
            major_id = r["_id"]
            major_name = str(major_id)

            # 1) Try Majors collection where _id is like "CS"
            major_doc = await self.majors.find_one({"_id": major_id}, {"major_name": 1})
            if major_doc and major_doc.get("major_name"):
                major_name = major_doc["major_name"]
            else:
                # 2) Try MajorHistories where major_id is like "MAJ-CS-001"
                hist_doc = await self.major_histories.find_one({"major_id": major_id}, {"major_name": 1})
                if hist_doc and hist_doc.get("major_name"):
                    major_name = hist_doc["major_name"]

            output.append({"major": major_name, "count": r["count"]})

        return output

    async def pending_actions(self) -> dict[str, Any]:
        """
        We'll return REAL pending signals from your current collections:

        - majorChanges: MajorHistories with status == "Transition"
        - scheduleConflicts: Enrollments with status == "Conflict"
        - creditOverloads: keep empty for now (needs a clear rule & joins)
        - mustResetPasswords: AuthCredentials where must_reset_password == true
        """

        # Major change requests
        major_changes = await self.major_histories.find(
            {"status": {"$in": ["Transition", "Pending"]}}
        ).limit(50).to_list(length=50)

        # Conflicting enrollments
        schedule_conflicts = await self.enrollments.find(
            {"status": "Conflict"}
        ).limit(50).to_list(length=50)

        # Must reset password
        must_reset_password_count = await self.auth_credentials.count_documents({"must_reset_password": True})

        # Clean ObjectId for JSON
        def clean(doc: dict[str, Any]) -> dict[str, Any]:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
            return doc

        return {
            "majorChanges": [clean(d) for d in major_changes],
            "creditOverloads": [],  # will implement once you define the rule/threshold
            "scheduleConflicts": [clean(d) for d in schedule_conflicts],
            "mustResetPasswordCount": must_reset_password_count,
        }

    async def list_students(self):
        students = await self.users.find({"role": "student"}).to_list(length=1000)

        for s in students:
            if "_id" in s:
                s["_id"] = str(s["_id"])

            sid = s.get("user_id") or s.get("id")
            sp = s.get("student_profile") or {}

            # ✅ compute earned credits from Passed enrollments
            earned = 0
            if sid:
                passed = await self.enrollments.find(
                    {"student_id": sid, "status": {"$in": ["Passed"]}}
                ).to_list(length=500)

                for e in passed:
                    code = e.get("course_id")
                    if code:
                        course = await self.courses.find_one({"course_code": code})
                        if course and course.get("credits"):
                            earned += int(course["credits"])

            # put computed fields into student_profile so frontend can read them
            sp["credits_earned"] = earned
            sp["credits_required"] = sp.get("credits_required") or 120  # default for now
            s["student_profile"] = sp

        return students


    async def get_student_details(self, student_id: str):
        # 1) Find the student in Users
        student = await self.users.find_one({"role": "student", "user_id": student_id})
        if not student:
            # fallback: some systems store student_id in different fields
            student = await self.users.find_one({"role": "student", "id": student_id})

        if not student:
            return None

        # make json-safe
        student["_id"] = str(student.get("_id"))

        sp = student.get("student_profile") or {}

        # 2) Resolve major name (supports both Majors and MajorHistories styles)
        major_id = sp.get("major_id") or sp.get("major") or None
        major_name = sp.get("major_name") or None

        if not major_name and major_id:
            major_doc = await self.majors.find_one({"_id": major_id})
            if major_doc and major_doc.get("major_name"):
                major_name = major_doc["major_name"]
            else:
                hist_doc = await self.major_histories.find_one({"major_id": major_id})
                if hist_doc and hist_doc.get("major_name"):
                    major_name = hist_doc["major_name"]

        # 3) Get enrollments for this student
        # Try a few common field names to avoid breaking if schema differs
        enroll_query = {
            "$or": [
                {"student_id": student_id},
                {"student_user_id": student_id},
                {"user_id": student_id},
            ]
        }
        enrollments = await self.enrollments.find(enroll_query).to_list(length=200)

        # 4) Build UI-friendly enrollment rows
        enrollment_rows = []
        for e in enrollments:
            if "_id" in e:
                e["_id"] = str(e["_id"])

            course_code = e.get("course_id") or e.get("course_code") or ""
            course_doc = None

            # ✅ Your Enrollments.course_id is actually Courses.course_code (ex: "CS-101")
            if course_code:
                course_doc = await self.courses.find_one({"course_code": course_code})

            title = (course_doc or {}).get("title") or (course_doc or {}).get("name") or "-"
            credits = (course_doc or {}).get("credits") or 0

            enrollment_rows.append(
                {
                    "id": str(e.get("_id") or ""),
                    "code": course_code or "-",
                    "name": title,
                    "credits": int(credits) if isinstance(credits, (int, float)) else 0,
                    "grade": e.get("grade") or "-",
                    "status": e.get("status") or "Enrolled",
                }
            )


        # 5) Build the response payload used by the frontend page
        payload = {
            "id": student.get("user_id") or student.get("id") or student_id,
            "name": student.get("name", "Unknown"),
            "email": student.get("email", ""),
            "major": major_name or major_id or "—",
            "year": sp.get("year") or "—",
            "gpa": sp.get("gpa") or 0.0,
            "advisor": sp.get("advisor") or sp.get("advisor_name") or "—",
            "creditsEarned": sp.get("credits_earned") or sp.get("creditsEarned") or 0,
            "creditsRequired": sp.get("credits_required") or sp.get("creditsRequired") or 0,
            "status": sp.get("academic_status") or student.get("status") or "Active",
            "avatar": sp.get("avatar") or "",
            "enrollments": enrollment_rows,
        }

        return payload
