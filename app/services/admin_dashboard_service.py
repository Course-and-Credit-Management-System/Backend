from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime

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
        self.students_progress = db["students_progress"]
    @classmethod
    async def create(cls) -> "AdminDashboardService":
        db = await get_database()
        return cls(db)

    # -------------------------
    # Helpers
    # -------------------------
    def _json_safe(self, doc: Any) -> Any:
        """
        Convert ObjectId + datetime (and nested) into JSON safe values.
        """
        if isinstance(doc, dict):
            out = {}
            for k, v in doc.items():
                if k == "_id":
                    out[k] = str(v)
                else:
                    out[k] = self._json_safe(v)
            return out

        if isinstance(doc, list):
            return [self._json_safe(x) for x in doc]

        if isinstance(doc, datetime):
            return doc.isoformat()

        return doc

    async def statistics(self) -> dict[str, Any]:
        total_students = await self.users.count_documents({"role": "student"})

        graduated_count = await self.users.count_documents(
            {"role": "student", "student_profile.academic_status": "Graduated"}
        )

        retake_requirement = await self.enrollments.count_documents(
            {
                "is_retake": True,
                "status": {"$in": ["Pending", "Enrolled", "Failed", "Passed"]},
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
        Fetch major distribution from students_progress.selected_major
        (based on the collection in your screenshot), not Users.student_profile.major_id.
        """

        pipeline = [
            {"$match": {"selected_major": {"$exists": True, "$nin": [None, ""]}}},
            {
                # keep only records that belong to real student users
                "$lookup": {
                    "from": "Users",
                    "let": {"sid": "$student_id"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$role", "student"]},
                                        {"$eq": ["$user_id", "$$sid"]}  # ✅ correct join

                                    ]
                                }
                            }
                        },
                        {"$project": {"_id": 1}},
                    ],
                    "as": "stu",
                }
            },
            {"$match": {"stu.0": {"$exists": True}}},
            {"$group": {"_id": "$selected_major", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 200},
        ]

        rows = await self.students_progress.aggregate(pipeline).to_list(length=200)

        output: list[dict[str, Any]] = []
        for r in rows:
            major_id = r["_id"]
            major_name = str(major_id)

            major_doc = await self.majors.find_one({"_id": major_id}, {"major_name": 1})
            if major_doc and major_doc.get("major_name"):
                major_name = major_doc["major_name"]
            else:
                hist_doc = await self.major_histories.find_one({"major_id": major_id}, {"major_name": 1})
                if hist_doc and hist_doc.get("major_name"):
                    major_name = hist_doc["major_name"]

            output.append({"major": major_name, "count": r["count"]})

        return output

    async def pending_actions(self) -> dict[str, Any]:
        """
        REAL pending signals:

        - majorChanges: MajorHistories where status in ["Transition","Pending"]
        - scheduleConflicts: Enrollments where status == "Conflict"
        - mustResetPasswords: AuthCredentials where must_reset_password == true
          -> includes user name/email/role for UI
        - mustResetPasswordCount: count for badge
        """

        # -------------------------
        # Major change requests
        # -------------------------
        major_changes = await self.major_histories.find(
            {"status": {"$in": ["Transition", "Pending"]}},
            {
                "_id": 1,
                "major_id": 1,
                "major_name": 1,
                "status": 1,
                "created_at": 1,
                "updated_at": 1,
                "student_id": 1,
                "user_id": 1,
            },
        ).sort("updated_at", -1).limit(50).to_list(length=50)

        # -------------------------
        # Conflicting enrollments
        # -------------------------
        schedule_conflicts = await self.enrollments.find(
            {"status": "Pending"},
            {
                "_id": 1,
                "student_id": 1,
                "course_id": 1,
                "course_code": 1,
                "status": 1,
                "created_at": 1,
                "updated_at": 1,
                "semester": 1,
                "year": 1,
            },
        ).sort("updated_at", -1).limit(50).to_list(length=50)

        # -------------------------
        # Must reset password (COUNT + LIST)
        # IMPORTANT: do NOT return password_hash
        # -------------------------
        must_reset_password_count = await self.auth_credentials.count_documents({"must_reset_password": True})

        creds = await self.auth_credentials.find(
            {"must_reset_password": True},
            {
                "_id": 1,
                "user_id": 1,
                "must_reset_password": 1,
                "created_at": 1,
                "updated_at": 1,
            },
        ).sort("updated_at", -1).limit(50).to_list(length=50)

        # Join Users for display names/emails
        must_reset_passwords: List[Dict[str, Any]] = []
        for c in creds:
            uid = c.get("user_id")

            # Try user_id match first, then fallback to id
            user_doc = None
            if uid:
                user_doc = await self.users.find_one(
                    {"user_id": uid},
                    {"_id": 1, "user_id": 1, "id": 1, "name": 1, "email": 1, "role": 1},
                )
                if not user_doc:
                    user_doc = await self.users.find_one(
                        {"id": uid},
                        {"_id": 1, "user_id": 1, "id": 1, "name": 1, "email": 1, "role": 1},
                    )

            must_reset_passwords.append(
                {
                    "id": str(c.get("_id")),
                    "user_id": uid,
                    "must_reset_password": True,
                    "created_at": c.get("created_at"),
                    "updated_at": c.get("updated_at"),
                    "user": {
                        "id": (user_doc or {}).get("user_id") or (user_doc or {}).get("id") or uid,
                        "name": (user_doc or {}).get("name") or "Unknown",
                        "email": (user_doc or {}).get("email") or "",
                        "role": (user_doc or {}).get("role") or "",
                    },
                }
            )

        # JSON-safe all payload parts
        return {
            "majorChanges": self._json_safe(major_changes),
            "scheduleConflicts": self._json_safe(schedule_conflicts),
            "mustResetPasswords": self._json_safe(must_reset_passwords),
            "mustResetPasswordCount": must_reset_password_count,
        }

    async def list_students(self):
        students = await self.users.find({"role": "student"}).to_list(length=1000)

        for s in students:
            if "_id" in s:
                s["_id"] = str(s["_id"])

            sid = s.get("user_id") or s.get("id")
            sp = s.get("student_profile") or {}

            # compute earned credits from Passed enrollments
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

            sp["credits_earned"] = earned
            sp["credits_required"] = sp.get("credits_required") or 120
            s["student_profile"] = sp

        return students

    def _parse_year_semester(self, current_year) -> tuple:
        """Parse current_year string to (year, semester). Same logic as students router."""
        year_str = current_year.value if hasattr(current_year, "value") else str(current_year or "")
        year, semester = 1, 1
        if "5th Year" in year_str or "5th" in year_str:
            year = 5
        elif "4th Year" in year_str or "4th" in year_str:
            year = 4
        elif "3rd Year" in year_str or "3rd" in year_str:
            year = 3
        elif "2nd Year" in year_str or "2nd" in year_str:
            year = 2
        if "Second Sem" in year_str or "2nd Sem" in year_str or "Sem 2" in year_str:
            semester = 2
        return year, semester

    async def get_student_details(self, student_id: str):
        student = await self.users.find_one({"role": "student", "user_id": student_id})
        if not student:
            student = await self.users.find_one({"role": "student", "id": student_id})

        if not student:
            return None

        student["_id"] = str(student.get("_id"))
        sp = student.get("student_profile") or {}

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

        enroll_query = {
            "$or": [
                {"student_id": student_id},
                {"student_user_id": student_id},
                {"user_id": student_id},
            ]
        }
        enrollments = await self.enrollments.find(enroll_query).to_list(length=200)

        # Credits: use total_credits_completed, or compute from Passed enrollments if missing
        total_credits = int(sp.get("total_credits_completed") or sp.get("total_credits") or 0)
        if total_credits == 0:
            for e in enrollments:
                if (e.get("status") or "").lower() == "passed":
                    code = e.get("course_id") or e.get("course_code")
                    if code:
                        c = await self.courses.find_one({"course_code": code})
                        if c and c.get("credits"):
                            total_credits += int(c["credits"])
        required_credits = int(sp.get("credits_required") or sp.get("creditsRequired") or 120)

        # Year/semester from current_year (same as Students List)
        curr_yr = sp.get("current_year") or "1st Year, First Sem(new)"
        try:
            year_num, sem_num = self._parse_year_semester(curr_yr)
        except Exception:
            year_num, sem_num = 1, 1

        enrollment_rows = []
        for e in enrollments:
            if "_id" in e:
                e["_id"] = str(e["_id"])

            course_code = e.get("course_id") or e.get("course_code") or ""
            course_doc = None
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
                    "grade": (e.get("grade").value if hasattr(e.get("grade"), "value") else e.get("grade")) or "-",
                    "status": (e.get("status").value if hasattr(e.get("status"), "value") else e.get("status")) or "Enrolled",
                    "semester": e.get("semesterAttend") or e.get("semester_attend") or "",
                }
            )

        # Build academic_history from actual enrollment data
        academic_history_enhanced = []
        
        # Get all enrollments for this student
        student_enrollments = await self.enrollments.find({
            "$or": [
                {"student_id": student_id},
                {"student_user_id": student_id},
                {"user_id": student_id},
            ]
        }).to_list(length=200)
        
        # Group enrollments by semester
        semester_groups = {}
        for enrollment in student_enrollments:
            semester_attend = enrollment.get("semesterAttend") or enrollment.get("semester_attend", "Unknown")
            course_code = enrollment.get("course_id") or enrollment.get("course_code", "Unknown")
            
            if semester_attend not in semester_groups:
                semester_groups[semester_attend] = []
            semester_groups[semester_attend].append(course_code)
        
        # Map to academic_history format and try to match with stored GPA data
        semester_mapping = {
            '1st Year. First Sem': 'New . First Year . First Sem',
            '1st Year. Second Sem': 'New . First Year . Second Sem', 
            '2nd Year. First Sem': 'New . Second Year . First Sem',
            '2nd Year. Second Sem': 'New . Second Year . Second Sem'
        }
        
        # Get stored academic_history for GPA data
        stored_academic_history = sp.get("academic_history", [])
        gpa_mapping = {}
        for stored_entry in stored_academic_history:
            gpa_mapping[stored_entry.get("semester")] = stored_entry.get("GPA", 0)
        
        # Build enhanced academic_history
        for actual_semester, courses in semester_groups.items():
            mapped_semester = semester_mapping.get(actual_semester, actual_semester)
            academic_history_enhanced.append({
                "semester": mapped_semester,
                "enrollments": courses,
                "GPA": gpa_mapping.get(mapped_semester, 0)
            })

        payload = {
            "id": student.get("user_id") or student.get("id") or student_id,
            "user_id": student.get("user_id") or student.get("id") or student_id,
            "name": student.get("name", "Unknown"),
            "email": student.get("email", ""),
            "major": major_id or "CS",
            "major_name": major_name or major_id or "—",
            "year": year_num,
            "semester": sem_num,
            "section": sp.get("section"),
            "gpa": float(sp.get("gpa") or sp.get("cgpa") or 0.0),
            "advisor": sp.get("advisor") or sp.get("advisor_name") or "—",
            "creditsEarned": total_credits,
            "creditsRequired": required_credits,
            "status": sp.get("academic_status") or student.get("status") or "Active",
            "avatar": sp.get("avatar") or "",
            "enrollments": enrollment_rows,
            "academic_history": academic_history_enhanced,
        }

        return payload