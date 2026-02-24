import re
from datetime import datetime
from typing import Any, Optional


def _detect_semester_kind(semester_attend: Any) -> str:
    value = str(semester_attend or "").strip().lower()
    if not value:
        return "unknown"

    # Check second-semester patterns first to avoid false matches with "semester ii".
    if (
        re.search(r"\bsecond\s*sem(?:ester)?\b", value)
        or re.search(r"\b2nd\s*sem(?:ester)?\b", value)
        or re.search(r"\bsem(?:ester)?\s*ii\b", value)
        or re.search(r"\bsem(?:ester)?\s*2\b", value)
    ):
        return "second"

    if (
        re.search(r"\bfirst\s*sem(?:ester)?\b", value)
        or re.search(r"\b1st\s*sem(?:ester)?\b", value)
        or re.search(r"\bsem(?:ester)?\s*i\b", value)
        or re.search(r"\bsem(?:ester)?\s*1\b", value)
    ):
        return "first"

    return "unknown"


def compute_enrollment_academic_year(semester_attend: Any, now: Optional[datetime] = None) -> str:
    """
    Compute enrollment academic year from semester label.
    Examples:
    - First Sem (current year 2025) => 2025-2026
    - Second Sem (current year 2025) => 2024-2025
    """
    current = now or datetime.now()
    year = int(current.year)
    semester_kind = _detect_semester_kind(semester_attend)

    if semester_kind == "first":
        start_year = year
        end_year = year + 1
    elif semester_kind == "second":
        start_year = year - 1
        end_year = year
    else:
        # Fallback to school calendar:
        # First term starts in November, second term starts in June.
        month = int(current.month)
        if month >= 11 or month <= 5:
            start_year = year
            end_year = year + 1
        else:
            start_year = year - 1
            end_year = year

    return f"{start_year}-{end_year}"
