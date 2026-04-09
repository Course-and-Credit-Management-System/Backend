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

        # Pre-fetch all passed enrollments for all students at once
        student_ids = [s.get("user_id") or s.get("id") for s in students if (s.get("user_id") or s.get("id"))]
        
        all_passed = []
        if student_ids:
            all_passed = await self.enrollments.find(
                {"student_id": {"$in": student_ids}, "status": {"$in": ["Passed", "Pass"]}}
            ).to_list(length=None)
            
        # Pre-fetch all courses to map credits
        course_codes = list({e.get("course_id") for e in all_passed if e.get("course_id")})
        course_credits_map = {}
        if course_codes:
            courses = await self.courses.find({"course_code": {"$in": course_codes}}, {"course_code": 1, "credits": 1}).to_list(length=None)
            for c in courses:
                if c.get("course_code") and c.get("credits"):
                    course_credits_map[c["course_code"]] = int(c["credits"])
                    
        # Group earned credits by student_id
        student_credits = {}
        for e in all_passed:
            sid = e.get("student_id")
            code = e.get("course_id")
            if sid and code and code in course_credits_map:
                student_credits[sid] = student_credits.get(sid, 0) + course_credits_map[code]

        for s in students:
            if "_id" in s:
                s["_id"] = str(s["_id"])

            sid = s.get("user_id") or s.get("id")
            sp = s.get("student_profile") or {}

            # compute earned credits from pre-calculated map
            earned = student_credits.get(sid, 0)

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
        enrollments = await self.enrollments.find(enroll_query).to_list(length=500)

        # Bulk-load course metadata once to avoid per-row DB calls.
        course_tokens: set[str] = set()
        for e in enrollments:
            token = str(e.get("course_id") or e.get("course_code") or "").strip()
            if token:
                course_tokens.add(token)

        course_cache: Dict[str, Dict[str, Any]] = {}
        if course_tokens:
            course_docs = await self.courses.find(
                {"$or": [{"course_code": {"$in": list(course_tokens)}}, {"_id": {"$in": list(course_tokens)}}]}
            ).to_list(length=500)
            for c in course_docs:
                code_key = str(c.get("course_code") or "").strip()
                id_key = str(c.get("_id") or "").strip()
                if code_key:
                    course_cache[code_key] = c
                if id_key:
                    course_cache[id_key] = c

        # Credits: use total_credits_completed, or compute from Passed enrollments if missing
        total_credits = int(sp.get("total_credits_completed") or sp.get("total_credits") or 0)
        if total_credits == 0:
            for e in enrollments:
                if (e.get("status") or "").lower() == "passed":
                    code = str(e.get("course_id") or e.get("course_code") or "").strip()
                    if code:
                        c = course_cache.get(code)
                        if c and c.get("credits"):
                            total_credits += int(c["credits"])
        required_credits = int(sp.get("credits_required") or sp.get("creditsRequired") or 120)

        # Year/semester from current_year (same as Students List)
        curr_yr = sp.get("current_year") or "1st Year, First Sem(new)"
        try:
            year_num, sem_num = self._parse_year_semester(curr_yr)
        except Exception:
            year_num, sem_num = 1, 1

        def _grade_point(grade: str) -> float:
            grade_norm = str(grade or "").strip().upper()
            table = {
                "A+": 4.0,
                "A": 4.0,
                "A-": 3.67,
                "B+": 3.33,
                "B": 3.0,
                "B-": 2.67,
                "C+": 2.33,
                "C": 2.0,
                "C-": 1.67,
                "D+": 1.33,
                "D": 1.0,
                "F": 0.0,
            }
            return float(table.get(grade_norm, 0.0))

        def _semester_sort_key(sem_label: str) -> tuple[int, int]:
            text = str(sem_label or "").lower()
            year = 99
            sem = 99
            if "1st year" in text or "first year" in text:
                year = 1
            elif "2nd year" in text or "second year" in text:
                year = 2
            elif "3rd year" in text or "third year" in text:
                year = 3
            elif "4th year" in text or "fourth year" in text:
                year = 4
            elif "5th year" in text or "fifth year" in text:
                year = 5

            if "first sem" in text or "semester 1" in text:
                sem = 1
            elif "second sem" in text or "semester 2" in text:
                sem = 2
            return (year, sem)

        enrollment_rows = []
        semester_groups: Dict[str, List[Dict[str, Any]]] = {}
        passed_statuses = {"passed", "completed"}
        for e in enrollments:
            if "_id" in e:
                e["_id"] = str(e.get("_id"))

            course_token = str(e.get("course_id") or e.get("course_code") or "").strip()
            course_doc = course_cache.get(course_token, {})
            course_code = str(course_doc.get("course_code") or course_token or "-")
            title = str(course_doc.get("title") or course_doc.get("name") or course_code or "-")
            credits = float(course_doc.get("credits") or e.get("credits") or 3)

            grade = (e.get("grade").value if hasattr(e.get("grade"), "value") else e.get("grade")) or "-"
            status = (e.get("status").value if hasattr(e.get("status"), "value") else e.get("status")) or "Enrolled"
            semester_label = str(e.get("semesterAttend") or e.get("semester_attend") or "Unknown")

            gp = _grade_point(grade)
            passed = str(status).strip().lower() in passed_statuses and str(grade).strip().upper() != "F"
            earned_credits = credits if passed else 0.0
            gpe = gp * earned_credits if passed else 0.0

            enrollment_rows.append(
                {
                    "id": str(e.get("_id") or ""),
                    "code": course_code,
                    "name": title,
                    "credits": int(credits),
                    "grade": grade,
                    "status": status,
                    "semester": semester_label,
                    "grade_points": gp,
                    "grade_points_earned": gpe,
                }
            )

            semester_groups.setdefault(semester_label, []).append(
                {
                    "course_code": course_code,
                    "course_title": title,
                    "grade": grade,
                    "status": status,
                    "credits": int(credits),
                    "grade_points": gp,
                    "grade_points_earned": gpe,
                    "credits_earned": earned_credits,
                }
            )

        academic_history_enhanced = []
        cgpa_credits = 0.0
        cgpa_points = 0.0
        for sem_label, courses_in_sem in sorted(semester_groups.items(), key=lambda kv: _semester_sort_key(kv[0])):
            sem_credits_earned = float(sum(float(c.get("credits_earned") or 0.0) for c in courses_in_sem))
            sem_points_earned = float(sum(float(c.get("grade_points_earned") or 0.0) for c in courses_in_sem))
            sem_gpa = round((sem_points_earned / sem_credits_earned), 2) if sem_credits_earned > 0 else 0.0

            cgpa_credits += sem_credits_earned
            cgpa_points += sem_points_earned

            academic_history_enhanced.append(
                {
                    "semester": sem_label,
                    "courses": courses_in_sem,
                    # Keep legacy key for compatibility with older frontend consumers.
                    "enrollments": [c["course_code"] for c in courses_in_sem],
                    "total_credits_earned": int(sem_credits_earned),
                    "total_grade_points": sem_points_earned,
                    "gpa": sem_gpa,
                    "GPA": sem_gpa,
                }
            )

        calculated_cgpa = round((cgpa_points / cgpa_credits), 2) if cgpa_credits > 0 else 0.0

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
            "gpa": float(sp.get("gpa") or calculated_cgpa or sp.get("cgpa") or 0.0),
            "cgpa": float(sp.get("cgpa") or calculated_cgpa or sp.get("gpa") or 0.0),
            "advisor": sp.get("advisor") or sp.get("advisor_name") or "—",
            "creditsEarned": total_credits,
            "creditsRequired": required_credits,
            "status": sp.get("academic_status") or student.get("status") or "Active",
            "avatar": sp.get("avatar") or "",
            "enrollments": enrollment_rows,
            "academic_history": academic_history_enhanced,
        }

        return payload
