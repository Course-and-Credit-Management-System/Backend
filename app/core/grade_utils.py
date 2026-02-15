from typing import Tuple

# Returns: (grade, grade_point, status)
def calculate_grade(score: float) -> Tuple[str, float, str]:
    if score is None:
        score = 0

    score = float(score)
    score = max(0, min(100, score))  # clamp 0..100

    # Based on your flowchart
    if score >= 90:
        return "A+", 4.0, "Passed"
    if score >= 80:
        return "A", 4.0, "Passed"
    if score >= 75:
        return "A-", 3.7, "Passed"
    if score >= 70:
        return "B+", 3.3, "Passed"
    if score >= 65:
        return "B", 3.0, "Passed"
    if score >= 60:
        return "B-", 2.7, "Passed"
    if score >= 55:
        return "C+", 2.3, "Probation"
    if score >= 50:
        return "C", 2.0, "Probation"
    if score >= 40:
        return "D", 1.0, "Failed"
    return "F", 0.0, "Failed"
