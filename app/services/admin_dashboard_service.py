from app.core.database import get_database

class AdminDashboardService:
    def __init__(self):
        db = get_database()
        self.users = db["Users"]
        self.enrollments = db["Enrollments"]
        self.majors = db["Majors"]

    async def statistics(self):
        total_students = await self.users.count_documents({"role": "student"})
        graduated_count = await self.users.count_documents({
            "role": "student",
            "student_profile.academic_status": "Graduated"
        })

        # Retake requirement: count enrollments that are retakes and pending/active
        retake_requirement = await self.enrollments.count_documents({
            "is_retake": True,
            "status": {"$in": ["Pending", "Enrolled", "Conflict", "Waitlisted"]}
        })

        # Average GPA
        pipeline = [
            {"$match": {"role": "student", "student_profile.gpa": {"$exists": True}}},
            {"$group": {"_id": None, "avgGpa": {"$avg": "$student_profile.gpa"}}}
        ]
        res = await self.users.aggregate(pipeline).to_list(length=1)
        avg_gpa = float(res[0]["avgGpa"]) if res else 0.0

        return {
            "totalStudents": total_students,
            "graduatedCount": graduated_count,
            "retakeRequirement": retake_requirement,
            "averageGPA": round(avg_gpa, 2),
        }

    async def major_distribution(self):
        pipeline = [
            {"$match": {"role": "student", "student_profile.major_id": {"$exists": True}}},
            {"$group": {"_id": "$student_profile.major_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        rows = await self.users.aggregate(pipeline).to_list(length=200)

        output = []
        for r in rows:
            major_id = r["_id"]
            major_doc = await self.majors.find_one({"_id": major_id})
            major_name = major_doc["major_name"] if major_doc else major_id
            output.append({"major": major_name, "count": r["count"]})
        return output

    async def pending_actions(self):
        # Your DB schema doesn’t define where these are stored yet,
        # so return correct format now; you can wire it later.
        return {
            "majorChanges": [],
            "creditOverloads": [],
            "scheduleConflicts": [],
        }
