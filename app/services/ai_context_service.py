"""Structured context builders for reusable AI orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import json
import re

from app.core.database import get_database


async def _get_collection(possible_names: List[str]):
    db = await get_database()
    names = await db.list_collection_names()
    for name in possible_names:
        if name in names:
            return db[name]
    return db[possible_names[0]]


def enforce_context_scope(current_user: Dict[str, Any], requested_context_type: str) -> bool:
    """Strict role/user scoped access check for structured context providers."""
    role = (current_user.get("role") or "").lower()
    if role not in {"student", "admin"}:
        return False

    if role == "student":
        return requested_context_type in {
            "user_profile",
            "courses",
            "majors",
            "announcements",
            "enrollments",
        }

    # Admin scope can be further constrained by access level / permissions.
    admin_profile = current_user.get("admin_profile") or {}
    permissions = set(admin_profile.get("permissions") or [])
    if not permissions:
        # If no explicit permissions are provided in token payload, allow admin defaults.
        return True

    permission_map = {
        "courses": {"manage_courses"},
        "majors": {"manage_courses"},
        "announcements": {"manage_courses"},
        "enrollments": {"approve_enrollment", "grade_students"},
        "user_profile": {"approve_enrollment", "grade_students", "manage_courses"},
        "students": {"approve_enrollment", "grade_students", "manage_courses"},
    }
    required = permission_map.get(requested_context_type)
    if not required:
        return True
    return bool(required.intersection(permissions))


async def _build_student_user_context(user_id: str) -> Dict[str, Any]:
    users = await _get_collection(["Users", "users"])
    user = await users.find_one({"user_id": user_id}, {"password_hash": 0})
    if not user:
        return {}

    student_profile = user.get("student_profile") or {}
    return {
        "user_id": user.get("user_id"),
        "name": user.get("name"),
        "role": user.get("role"),
        "major_id": student_profile.get("major_id"),
        "academic_status": student_profile.get("academic_status"),
        "current_year": student_profile.get("current_year"),
        "gpa": student_profile.get("gpa"),
        "cgpa": student_profile.get("cgpa"),
        "total_credits_completed": student_profile.get("total_credits_completed"),
        "current_sem_earned_credits": student_profile.get("current_sem_earned_credits"),
        "is_major_student": student_profile.get("is_major_student"),
    }


async def _build_admin_user_context(user_id: str) -> Dict[str, Any]:
    users = await _get_collection(["Users", "users"])
    user = await users.find_one({"user_id": user_id}, {"password_hash": 0})
    if not user:
        return {}
    admin_profile = user.get("admin_profile") or {}
    return {
        "user_id": user.get("user_id"),
        "name": user.get("name"),
        "role": user.get("role"),
        "department": admin_profile.get("department"),
        "access_level": admin_profile.get("access_level"),
        "permissions": admin_profile.get("permissions") or [],
    }


async def build_user_context(current_user: Dict[str, Any], intent: str) -> Dict[str, Any]:
    """Build user-scoped profile context for the request."""
    if not enforce_context_scope(current_user, "user_profile"):
        return {}

    role = (current_user.get("role") or "").lower()
    user_id = current_user.get("user_id") or ""
    if not user_id:
        return {}

    if role == "student":
        return await _build_student_user_context(user_id)
    return await _build_admin_user_context(user_id)


async def _build_enrollment_context(current_user: Dict[str, Any]) -> Dict[str, Any]:
    if not enforce_context_scope(current_user, "enrollments"):
        return {}

    role = (current_user.get("role") or "").lower()
    enrollments = await _get_collection(["Enrollments", "enrollments"])

    if role == "student":
        student_id = current_user.get("user_id")
        docs = await enrollments.find(
            {"student_id": student_id},
            {
                "_id": 0,
                "course_id": 1,
                "status": 1,
                "grade": 1,
                "semesterAttend": 1,
                "is_retake": 1,
            },
        ).to_list(length=100)
        retakes = [d.get("course_id") for d in docs if (d.get("status") or "").lower() == "failed"]
        return {"student_enrollments": docs, "retake_candidates": retakes}

    # Admin gets high-level summary only in base context.
    total = await enrollments.count_documents({})
    pending = await enrollments.count_documents({"status": "Pending"})
    conflict = await enrollments.count_documents({"status": "Conflict"})
    return {
        "enrollment_summary": {
            "total": total,
            "pending": pending,
            "conflict": conflict,
        }
    }


async def _build_course_context(current_user: Dict[str, Any]) -> Dict[str, Any]:
    if not enforce_context_scope(current_user, "courses"):
        return {}

    courses = await _get_collection(["Courses", "courses"])
    projection = {
        "_id": 0,
        "course_code": 1,
        "title": 1,
        "credits": 1,
        "type": 1,
        "prerequisites": 1,
        "major_specific": 1,
        "semester": 1,
    }

    role = (current_user.get("role") or "").lower()
    limit = 50 if role == "student" else 100
    docs = await courses.find({}, projection).to_list(length=limit)
    return {"courses": docs}


def _normalize_status(status: Any, grade: Any) -> str:
    s = str(status or "").strip().lower()
    g = str(grade or "").strip().upper()
    if s in {"passed", "completed"}:
        return "completed"
    if s in {"failed"} or g == "F":
        return "failed"
    if s in {"dropped", "withdrawn"}:
        return "withdrawn"
    if s:
        return s
    return "unknown"


async def _build_academic_history_context(current_user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build enriched academic history by joining `academic_history.course_code`
    with `Courses.course_code`.
    """
    if not enforce_context_scope(current_user, "user_profile"):
        return {}
    role = (current_user.get("role") or "").lower()
    if role != "student":
        return {}

    users = await _get_collection(["Users", "users"])
    courses = await _get_collection(["Courses", "courses"])

    user = await users.find_one(
        {"user_id": current_user.get("user_id")},
        {"academic_history": 1, "student_profile": 1},
    )
    history = (user or {}).get("academic_history") or []
    if not history:
        return {
            "academic_history_summary": {
                "total_attempted": 0,
                "completed_count": 0,
                "failed_count": 0,
                "withdrawn_count": 0,
            },
            "completed_courses": [],
            "failed_courses": [],
        }

    course_codes = sorted(
        {
            str(h.get("course_code")).strip()
            for h in history
            if isinstance(h, dict) and h.get("course_code")
        }
    )

    course_map: Dict[str, Dict[str, Any]] = {}
    if course_codes:
        course_docs = await courses.find(
            {"course_code": {"$in": course_codes}},
            {
                "_id": 0,
                "course_code": 1,
                "title": 1,
                "credits": 1,
                "type": 1,
                "prerequisites": 1,
                "semester": 1,
                "major_specific": 1,
            },
        ).to_list(length=len(course_codes))
        course_map = {str(c.get("course_code")): c for c in course_docs}

    completed_courses: List[Dict[str, Any]] = []
    failed_courses: List[Dict[str, Any]] = []
    withdrawn_courses: List[Dict[str, Any]] = []
    other_attempts: List[Dict[str, Any]] = []

    for h in history:
        if not isinstance(h, dict):
            continue
        code = str(h.get("course_code") or "").strip()
        if not code:
            continue
        linked = course_map.get(code) or {}
        normalized_status = _normalize_status(h.get("status"), h.get("grade"))
        item = {
            "course_code": code,
            "course_title": h.get("course_title") or linked.get("title"),
            "semester": h.get("semester"),
            "credits": h.get("credits") if h.get("credits") is not None else linked.get("credits"),
            "grade": h.get("grade"),
            "status": normalized_status,
            "course_type": linked.get("type"),
            "prerequisites": linked.get("prerequisites") or [],
            "major_specific": linked.get("major_specific"),
        }

        if normalized_status == "completed":
            completed_courses.append(item)
        elif normalized_status == "failed":
            failed_courses.append(item)
        elif normalized_status == "withdrawn":
            withdrawn_courses.append(item)
        else:
            other_attempts.append(item)

    return {
        "academic_history_summary": {
            "total_attempted": len(completed_courses) + len(failed_courses) + len(withdrawn_courses) + len(other_attempts),
            "completed_count": len(completed_courses),
            "failed_count": len(failed_courses),
            "withdrawn_count": len(withdrawn_courses),
        },
        "completed_courses": completed_courses,
        "failed_courses": failed_courses,
        "withdrawn_courses": withdrawn_courses,
        "other_attempts": other_attempts,
    }


async def _build_course_stats_context(current_user: Dict[str, Any]) -> Dict[str, Any]:
    """Build lightweight course statistics for count/summary questions."""
    if not enforce_context_scope(current_user, "courses"):
        return {}

    courses = await _get_collection(["Courses", "courses"])
    total_courses = await courses.count_documents({})
    major_specific_courses = await courses.count_documents({"major_specific": True})
    with_prereq_courses = await courses.count_documents(
        {"prerequisites.0": {"$exists": True}}
    )

    by_type: Dict[str, int] = {}
    cursor = courses.aggregate(
        [
            {"$group": {"_id": "$type", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
    )
    async for row in cursor:
        key = row.get("_id") or "Unknown"
        by_type[str(key)] = int(row.get("count", 0))

    sample_courses = await courses.find(
        {},
        {"_id": 0, "course_code": 1, "title": 1, "type": 1, "credits": 1},
    ).limit(8).to_list(length=8)

    return {
        "course_stats": {
            "total_courses": total_courses,
            "by_type": by_type,
            "major_specific_courses": major_specific_courses,
            "courses_with_prerequisites": with_prereq_courses,
            "sample_courses": sample_courses,
        }
    }


def _normalize_enrollment_course_ids(primary: str, alternatives: List[Any]) -> List[str]:
    ids: List[str] = []
    for value in [primary, *alternatives]:
        s = str(value or "").strip()
        if s and s not in ids:
            ids.append(s)
    return ids


def _is_history_completed(status: Any, grade: Any) -> bool:
    normalized_status = str(status or "").strip().lower()
    normalized_grade = str(grade or "").strip().upper()
    if normalized_status in {"passed", "completed"}:
        return True
    if normalized_grade in {"A+", "A", "A-", "B+", "B", "B-", "C+", "C", "D"}:
        return True
    return False


async def _build_course_advisor_context(
    current_user: Dict[str, Any],
    course_id: Optional[str],
) -> Dict[str, Any]:
    if not course_id or not str(course_id).strip():
        return {"course_advisor": {"found": False, "error": "course_id is required"}}

    if not enforce_context_scope(current_user, "courses") or not enforce_context_scope(current_user, "enrollments"):
        return {}

    requested_course_id = str(course_id).strip()
    courses = await _get_collection(["Courses", "courses"])
    enrollments = await _get_collection(["Enrollments", "enrollments"])
    users = await _get_collection(["Users", "users"])

    course = await courses.find_one(
        {"$or": [{"course_code": requested_course_id}, {"_id": requested_course_id}]},
        {
            "_id": 1,
            "course_code": 1,
            "title": 1,
            "credits": 1,
            "type": 1,
            "prerequisites": 1,
            "major_specific": 1,
            "semester": 1,
            "schedule": 1,
            "description": 1,
            "department": 1,
            "instructor": 1,
            "room": 1,
        },
    )
    if not course:
        return {
            "course_advisor": {
                "requested_course_id": requested_course_id,
                "found": False,
                "error": "course not found",
            }
        }

    canonical_course_id = str(course.get("course_code") or requested_course_id)
    enrollment_course_ids = _normalize_enrollment_course_ids(
        canonical_course_id,
        [requested_course_id, course.get("_id")],
    )
    match_filter = {"course_id": {"$in": enrollment_course_ids}}

    total_enrolled = int(await enrollments.count_documents(match_filter))
    active_enrolled = int(
        await enrollments.count_documents(
            {
                "$and": [
                    match_filter,
                    {"status": {"$in": ["Enrolled", "Pending", "Waitlisted", "Conflict"]}},
                ]
            }
        )
    )
    passed_count = int(
        await enrollments.count_documents(
            {"$and": [match_filter, {"status": {"$in": ["Passed", "Completed"]}}]}
        )
    )
    failed_count = int(
        await enrollments.count_documents(
            {
                "$and": [
                    match_filter,
                    {
                        "$or": [
                            {"status": "Failed"},
                            {"grade": "F"},
                        ]
                    },
                ]
            }
        )
    )
    withdrawn_count = int(
        await enrollments.count_documents(
            {"$and": [match_filter, {"status": {"$in": ["Dropped", "Withdrawn"]}}]}
        )
    )

    avg_points = await enrollments.aggregate(
        [
            {"$match": {"$and": [match_filter, {"points": {"$type": "number"}}]}},
            {"$group": {"_id": None, "avg": {"$avg": "$points"}}},
        ]
    ).to_list(length=1)
    avg_scores = await enrollments.aggregate(
        [
            {"$match": {"$and": [match_filter, {"scores": {"$type": "number"}}]}},
            {"$group": {"_id": None, "avg": {"$avg": "$scores"}}},
        ]
    ).to_list(length=1)

    status_distribution_rows = await enrollments.aggregate(
        [
            {"$match": match_filter},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
    ).to_list(length=50)
    grade_distribution_rows = await enrollments.aggregate(
        [
            {"$match": {"$and": [match_filter, {"grade": {"$exists": True, "$ne": None}}]}},
            {"$group": {"_id": "$grade", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
    ).to_list(length=50)

    status_distribution = {
        str(row.get("_id") or "Unknown"): int(row.get("count", 0))
        for row in status_distribution_rows
    }
    grade_distribution = {
        str(row.get("_id") or "Unknown"): int(row.get("count", 0))
        for row in grade_distribution_rows
    }

    student_fit: Dict[str, Any] = {}
    role = (current_user.get("role") or "").lower()
    if role == "student":
        student_id = str(current_user.get("user_id") or "").strip()
        user = await users.find_one(
            {"user_id": student_id},
            {"student_profile": 1, "academic_history": 1, "_id": 0},
        )
        student_profile = (user or {}).get("student_profile") or {}
        history = (user or {}).get("academic_history") or []

        completed_codes = {
            str(h.get("course_code") or "").strip()
            for h in history
            if isinstance(h, dict) and _is_history_completed(h.get("status"), h.get("grade"))
        }
        completed_codes = {c for c in completed_codes if c}

        prerequisites = [str(p).strip() for p in (course.get("prerequisites") or []) if str(p).strip()]
        missing_prerequisites = [p for p in prerequisites if p not in completed_codes]
        major_specific = bool(course.get("major_specific"))
        major_id = student_profile.get("major_id")
        major_match = True if not major_specific else bool(major_id)
        fit_reasons: List[str] = []
        if missing_prerequisites:
            fit_reasons.append("missing_prerequisites")
        if major_specific and not major_match:
            fit_reasons.append("major_required")
        fit_score = max(0.0, 1.0 - (0.5 if missing_prerequisites else 0.0) - (0.5 if (major_specific and not major_match) else 0.0))

        student_fit = {
            "student_id": student_id,
            "student_major_id": major_id,
            "course_major_specific": major_specific,
            "prerequisites": prerequisites,
            "missing_prerequisites": missing_prerequisites,
            "major_match": major_match,
            "is_suitable": not fit_reasons,
            "fit_score": round(fit_score, 2),
            "reasons": fit_reasons,
        }

    return {
        "course_advisor": {
            "requested_course_id": requested_course_id,
            "found": True,
            "course": {
                "course_code": course.get("course_code"),
                "title": course.get("title"),
                "credits": course.get("credits"),
                "type": course.get("type"),
                "prerequisites": course.get("prerequisites") or [],
                "major_specific": bool(course.get("major_specific")),
                "semester": course.get("semester") or [],
                "schedule": course.get("schedule") or [],
                "description": course.get("description"),
                "department": course.get("department"),
                "instructor": course.get("instructor"),
                "room": course.get("room"),
            },
            "enrollment_stats": {
                "total_records": total_enrolled,
                "active_enrolled_count": active_enrolled,
                "passed_count": passed_count,
                "failed_count": failed_count,
                "withdrawn_or_dropped_count": withdrawn_count,
                "average_grade_points": round(float(avg_points[0]["avg"]), 2) if avg_points and avg_points[0].get("avg") is not None else None,
                "average_scores": round(float(avg_scores[0]["avg"]), 2) if avg_scores and avg_scores[0].get("avg") is not None else None,
                "status_distribution": status_distribution,
                "grade_distribution": grade_distribution,
            },
            "student_fit": student_fit,
        }
    }


async def _build_major_requirement_courses_context(current_user: Dict[str, Any]) -> Dict[str, Any]:
    """Join major requirement course codes to Courses for richer major answers."""
    if not enforce_context_scope(current_user, "majors"):
        return {}
    role = (current_user.get("role") or "").lower()
    if role != "student":
        return {}

    users = await _get_collection(["Users", "users"])
    majors = await _get_collection(["Majors", "majors"])
    courses = await _get_collection(["Courses", "courses"])

    user = await users.find_one({"user_id": current_user.get("user_id")}, {"student_profile.major_id": 1})
    major_id = ((user or {}).get("student_profile") or {}).get("major_id")
    if not major_id:
        return {"major_requirement_courses": []}

    major = await majors.find_one({"_id": major_id}, {"_id": 1, "major_name": 1, "requirements": 1})
    requirements = (major or {}).get("requirements") or []
    if not requirements:
        return {"major_requirement_courses": [], "major_requirement_summary": {"required_count": 0, "mapped_count": 0}}

    course_docs = await courses.find(
        {"course_code": {"$in": requirements}},
        {"_id": 0, "course_code": 1, "title": 1, "credits": 1, "type": 1, "prerequisites": 1},
    ).to_list(length=len(requirements))
    mapped = {str(c.get("course_code")): c for c in course_docs}
    enriched = [mapped.get(code, {"course_code": code, "title": None, "credits": None, "type": None, "prerequisites": []}) for code in requirements]

    return {
        "major_requirement_summary": {
            "major_id": major_id,
            "major_name": (major or {}).get("major_name"),
            "required_count": len(requirements),
            "mapped_count": len(course_docs),
        },
        "major_requirement_courses": enriched,
    }


async def _build_major_context(current_user: Dict[str, Any]) -> Dict[str, Any]:
    if not enforce_context_scope(current_user, "majors"):
        return {}

    users = await _get_collection(["Users", "users"])
    majors = await _get_collection(["Majors", "majors"])
    role = (current_user.get("role") or "").lower()

    if role == "student":
        user = await users.find_one({"user_id": current_user.get("user_id")}, {"student_profile.major_id": 1})
        major_id = ((user or {}).get("student_profile") or {}).get("major_id")
        if not major_id:
            return {"major": None}
        major = await majors.find_one({"_id": major_id}, {"_id": 1, "major_name": 1, "department": 1, "requirements": 1})
        return {"major": major}

    major_list = await majors.find({}, {"_id": 1, "major_name": 1, "department": 1}).to_list(length=50)
    return {"majors": major_list}


async def _build_announcement_context(current_user: Dict[str, Any]) -> Dict[str, Any]:
    if not enforce_context_scope(current_user, "announcements"):
        return {}

    announcements = await _get_collection(["Announcements", "announcements"])
    now = datetime.now(timezone.utc)
    role = (current_user.get("role") or "").lower()

    base_filter: Dict[str, Any] = {
        "$or": [
            {"expiry_date": None},
            {"expiry_date": {"$exists": False}},
            {"expiry_date": {"$gte": now}},
        ]
    }

    if role == "student":
        audience_filter = {
            "$or": [
                {"target_audience": {"$regex": "^All$", "$options": "i"}},
                {"target_audience": {"$regex": "^Students?$", "$options": "i"}},
                {"target_audience": {"$regex": "student", "$options": "i"}},
            ]
        }
        query = {"$and": [base_filter, audience_filter]}
    else:
        query = base_filter

    docs = await announcements.find(
        query,
        {
            "_id": 0,
            "title": 1,
            "content": 1,
            "type": 1,
            "target_audience": 1,
            "posted_by": 1,
            "date_posted": 1,
            "created_at": 1,
            "expiry_date": 1,
        },
    ).sort([("date_posted", -1), ("created_at", -1)]).to_list(length=30)
    return {"announcements": docs}


def _student_projection() -> Dict[str, int]:
    return {
        "_id": 0,
        "user_id": 1,
        "name": 1,
        "email": 1,
        "role": 1,
        "student_profile.major_id": 1,
        "student_profile.current_year": 1,
        "student_profile.academic_status": 1,
        "student_profile.gpa": 1,
        "student_profile.cgpa": 1,
        "student_profile.total_credits_completed": 1,
        "student_profile.current_sem_earned_credits": 1,
        "academic_history": 1,
    }


async def _build_admin_student_context(
    current_user: Dict[str, Any],
) -> Dict[str, Any]:
    role = (current_user.get("role") or "").lower()
    if role != "admin" or not enforce_context_scope(current_user, "students"):
        return {}

    users = await _get_collection(["Users", "users"])
    student_role_filter: Dict[str, Any] = {"role": {"$regex": "^student$", "$options": "i"}}
    students = await users.find(student_role_filter, _student_projection()).sort([("user_id", 1)]).to_list(length=None)

    total_students = await users.count_documents(student_role_filter)
    by_status: Dict[str, int] = {}
    cursor = users.aggregate(
        [
            {"$match": student_role_filter},
            {"$group": {"_id": "$student_profile.academic_status", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
    )
    async for row in cursor:
        key = row.get("_id") or "Unknown"
        by_status[str(key)] = int(row.get("count", 0))

    return {
        "student_summary": {
            "total_students": int(total_students),
            "students_in_context": len(students),
            "by_academic_status": by_status,
        },
        "students_academic_data": students,
    }


def _keyword_tokens(question: str) -> List[str]:
    q = (question or "").lower()
    raw = re.findall(r"[a-zA-Z0-9_+-]{3,}", q)
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "what",
        "when",
        "where",
        "which",
        "there",
        "have",
        "your",
        "about",
    }
    tokens = [t for t in raw if t not in stop]
    if not tokens:
        # Fallback for non-Latin scripts (e.g., Myanmar) where regex above may return nothing.
        split_tokens = [w.strip("၊။!?.,:;\"'()[]{}") for w in q.split()]
        tokens = [t for t in split_tokens if len(t) >= 2][:8]
    return tokens[:8]


async def _search_courses_realtime(question: str, limit: int = 20) -> List[Dict[str, Any]]:
    courses = await _get_collection(["Courses", "courses"])
    tokens = _keyword_tokens(question)
    code_hits = re.findall(r"\b[A-Za-z]{2,6}-\d{3,5}\b", question or "")

    if code_hits:
        return await courses.find(
            {"course_code": {"$in": code_hits}},
            {
                "_id": 0,
                "course_code": 1,
                "title": 1,
                "credits": 1,
                "type": 1,
                "prerequisites": 1,
                "semester": 1,
                "major_specific": 1,
            },
        ).to_list(length=limit)

    if not tokens:
        return []

    or_terms: List[Dict[str, Any]] = []
    for t in tokens[:5]:
        pattern = {"$regex": re.escape(t), "$options": "i"}
        or_terms.extend(
            [
                {"course_code": pattern},
                {"title": pattern},
                {"description": pattern},
                {"department": pattern},
            ]
        )

    return await courses.find(
        {"$or": or_terms},
        {
            "_id": 0,
            "course_code": 1,
            "title": 1,
            "credits": 1,
            "type": 1,
            "prerequisites": 1,
            "semester": 1,
            "major_specific": 1,
        },
    ).to_list(length=limit)


async def _search_announcements_realtime(question: str, current_user: Dict[str, Any], limit: int = 15) -> List[Dict[str, Any]]:
    if not enforce_context_scope(current_user, "announcements"):
        return []
    announcements = await _get_collection(["Announcements", "announcements"])
    tokens = _keyword_tokens(question)
    if not tokens:
        return []

    now = datetime.now(timezone.utc)
    base_filter: Dict[str, Any] = {
        "$or": [
            {"expiry_date": None},
            {"expiry_date": {"$exists": False}},
            {"expiry_date": {"$gte": now}},
        ]
    }
    role = (current_user.get("role") or "").lower()
    role_filter: Dict[str, Any] = {}
    if role == "student":
        role_filter = {
            "$or": [
                {"target_audience": {"$regex": "^All$", "$options": "i"}},
                {"target_audience": {"$regex": "^Students?$", "$options": "i"}},
                {"target_audience": {"$regex": "student", "$options": "i"}},
            ]
        }

    text_or: List[Dict[str, Any]] = []
    for t in tokens[:5]:
        pattern = {"$regex": re.escape(t), "$options": "i"}
        text_or.extend([{"title": pattern}, {"content": pattern}, {"type": pattern}])

    query: Dict[str, Any] = {"$and": [base_filter, {"$or": text_or}]}
    if role_filter:
        query["$and"].append(role_filter)

    return await announcements.find(
        query,
        {
            "_id": 0,
            "title": 1,
            "content": 1,
            "type": 1,
            "target_audience": 1,
            "posted_by": 1,
            "date_posted": 1,
            "created_at": 1,
            "expiry_date": 1,
        },
    ).sort([("date_posted", -1), ("created_at", -1)]).to_list(length=limit)


async def _search_students_realtime(
    question: str,
    current_user: Dict[str, Any],
    limit: int = 20,
) -> List[Dict[str, Any]]:
    role = (current_user.get("role") or "").lower()
    if role != "admin" or not enforce_context_scope(current_user, "students"):
        return []

    users = await _get_collection(["Users", "users"])
    student_role_filter: Dict[str, Any] = {"role": {"$regex": "^student$", "$options": "i"}}

    tokens = _keyword_tokens(question)
    user_id_hits = re.findall(r"\b[A-Za-z]{1,6}\d{2,10}\b", question or "")
    if user_id_hits:
        query = {"$and": [student_role_filter, {"user_id": {"$in": user_id_hits[:8]}}]}
        return await users.find(query, _student_projection()).to_list(length=limit)

    if not tokens:
        return []

    or_terms: List[Dict[str, Any]] = []
    for token in tokens[:5]:
        pattern = {"$regex": re.escape(token), "$options": "i"}
        or_terms.extend(
            [
                {"user_id": pattern},
                {"name": pattern},
                {"email": pattern},
                {"student_profile.major_id": pattern},
                {"student_profile.academic_status": pattern},
            ]
        )

    query = {"$and": [student_role_filter, {"$or": or_terms}]}
    return await users.find(query, _student_projection()).to_list(length=limit)


async def _build_admin_student_counts_realtime(
    question: str,
    current_user: Dict[str, Any],
) -> Dict[str, Any]:
    role = (current_user.get("role") or "").lower()
    if role != "admin" or not enforce_context_scope(current_user, "students"):
        return {}

    users = await _get_collection(["Users", "users"])
    student_role_filter: Dict[str, Any] = {"role": {"$regex": "^student$", "$options": "i"}}
    q = (question or "").lower()

    counts: Dict[str, Any] = {
        "total_students": int(await users.count_documents(student_role_filter))
    }

    status_keywords = ["active", "probation", "suspended", "graduated", "dismissed"]
    requested_statuses = [status_value for status_value in status_keywords if status_value in q]
    for status_value in requested_statuses:
        counts[f"{status_value}_students"] = int(
            await users.count_documents(
                {
                    "$and": [
                        student_role_filter,
                        {
                            "student_profile.academic_status": {
                                "$regex": f"^{re.escape(status_value)}$",
                                "$options": "i",
                            }
                        },
                    ]
                }
            )
        )

    return {"student_counts_realtime": counts}


async def build_domain_context(
    intent: str,
    current_user: Dict[str, Any],
    course_id: Optional[str] = None,
    include_admin_student_data: bool = False,
) -> Dict[str, Any]:
    """Build intent-aware domain context from live MongoDB data."""
    context: Dict[str, Any] = {}
    role = (current_user.get("role") or "").lower()

    if intent in {"academic_progress", "course_selection"}:
        context.update(await _build_academic_history_context(current_user))
        context.update(await _build_enrollment_context(current_user))
        context.update(await _build_course_stats_context(current_user))
        context.update(await _build_course_context(current_user))
        context.update(await _build_major_requirement_courses_context(current_user))
        context.update(await _build_major_context(current_user))
        context.update(await _build_announcement_context(current_user))
    elif intent == "course_stats":
        context.update(await _build_course_stats_context(current_user))
    elif intent == "course_advisor":
        context.update(await _build_course_advisor_context(current_user, course_id=course_id))
    elif intent == "major_requirements":
        context.update(await _build_course_stats_context(current_user))
        context.update(await _build_major_context(current_user))
        context.update(await _build_major_requirement_courses_context(current_user))
        context.update(await _build_course_context(current_user))
    elif intent == "announcements":
        context.update(await _build_announcement_context(current_user))
    elif intent == "policy_general":
        context.update(await _build_academic_history_context(current_user))
        context.update(await _build_enrollment_context(current_user))
        context.update(await _build_course_stats_context(current_user))
        context.update(await _build_major_context(current_user))
        context.update(await _build_major_requirement_courses_context(current_user))
        context.update(await _build_announcement_context(current_user))
    else:
        # Default auto mode.
        context.update(await _build_academic_history_context(current_user))
        context.update(await _build_enrollment_context(current_user))
        context.update(await _build_course_stats_context(current_user))
        context.update(await _build_major_context(current_user))
        context.update(await _build_major_requirement_courses_context(current_user))
        context.update(await _build_announcement_context(current_user))

    if include_admin_student_data and role == "admin":
        context.update(await _build_admin_student_context(current_user=current_user))
    return context


def _has_meaningful_context(ctx: Dict[str, Any]) -> bool:
    for v in ctx.values():
        if isinstance(v, dict) and v:
            return True
        if isinstance(v, list) and len(v) > 0:
            return True
        if isinstance(v, (str, int, float, bool)) and v not in {"", 0, False}:
            return True
    return False


async def build_realtime_context(
    question: str,
    current_user: Dict[str, Any],
    intent: str,
    course_id: Optional[str] = None,
    existing_context: Dict[str, Any] | None = None,
    include_admin_student_data: bool = False,
) -> Dict[str, Any]:
    """
    Additional real-time fetch layer used when base context is sparse or
    question demands more specific operational data.
    """
    q = (question or "").lower()
    existing_context = existing_context or {}
    realtime: Dict[str, Any] = {}

    need_history = any(
        k in q
        for k in [
            "academic history",
            "history",
            "completed",
            "failed",
            "passed",
            "retake",
            "ပြီးဆုံး",
            "ကျရှုံး",
            "အောင်",
            "မအောင်",
            "မှတ်တမ်း",
        ]
    )
    need_courses = any(
        k in q
        for k in [
            "course",
            "courses",
            "subject",
            "prerequisite",
            "schedule",
            "instructor",
            "credits",
            "သင်တန်း",
            "ဘာသာ",
        ]
    )
    need_majors = any(k in q for k in ["major", "requirement", "department", "မေဂျာ", "ဌာန", "လိုအပ်ချက်"])
    need_ann = any(k in q for k in ["announcement", "notice", "event", "urgent", "ကြေညာ", "အသိပေး", "အရေးပေါ်"])

    need_students = any(
        k in q
        for k in [
            "student",
            "students",
            "user",
            "users",
            "how many",
            "number of",
            "count",
            "total",
            "gpa",
            "cgpa",
            "academic status",
        ]
    )
    need_course_advisor = bool(course_id and str(course_id).strip()) or any(
        k in q
        for k in [
            "this course",
            "that course",
            "particular course",
            "enrolled",
            "passed",
            "failed",
            "average grade",
            "suited",
            "suitable",
            "fit",
        ]
    )

    context_sparse = not _has_meaningful_context(existing_context)
    role = (current_user.get("role") or "").lower()
    should_expand = (
        context_sparse
        or need_history
        or need_courses
        or need_course_advisor
        or need_majors
        or need_ann
        or (include_admin_student_data and role == "admin" and need_students)
    )
    if not should_expand:
        return realtime

    if need_history or intent == "academic_progress":
        realtime.update(await _build_academic_history_context(current_user))
        realtime.update(await _build_enrollment_context(current_user))

    if need_courses or intent in {"course_selection", "course_stats"}:
        realtime.update(await _build_course_stats_context(current_user))
        matched_courses = await _search_courses_realtime(question)
        if matched_courses:
            realtime["matched_courses_realtime"] = matched_courses
        else:
            realtime.update(await _build_course_context(current_user))

    if need_course_advisor or intent == "course_advisor":
        realtime.update(await _build_course_advisor_context(current_user, course_id=course_id))

    if need_majors or intent == "major_requirements":
        realtime.update(await _build_major_context(current_user))
        realtime.update(await _build_major_requirement_courses_context(current_user))

    if need_ann or intent == "announcements":
        matched_ann = await _search_announcements_realtime(question, current_user=current_user)
        if matched_ann:
            realtime["matched_announcements_realtime"] = matched_ann
        else:
            realtime.update(await _build_announcement_context(current_user))

    if include_admin_student_data and role == "admin":
        if need_students or context_sparse:
            realtime.update(await _build_admin_student_counts_realtime(question, current_user))
            matched_students = await _search_students_realtime(
                question=question,
                current_user=current_user,
            )
            if matched_students:
                realtime["matched_students_realtime"] = matched_students

    return realtime


def serialize_context_for_prompt(ctx: Dict[str, Any]) -> str:
    """Serialize structured context into stable prompt-friendly JSON text."""
    if not ctx:
        return ""
    return json.dumps(ctx, ensure_ascii=False, default=str, indent=2)
