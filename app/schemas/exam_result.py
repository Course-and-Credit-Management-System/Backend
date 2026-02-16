from pydantic import BaseModel, Field, model_validator
from typing import Optional, Literal

Section = Literal["A", "B", "C"]
Semester = Literal[1, 2]
Major = Literal["SE", "KE", "HPC", "CSec", "CN", "BIS", "ES", "CS", "CT"]

class ExamResultUpsertIn(BaseModel):
    student_id: str
    course_code: str
    year: int = Field(ge=1, le=5)
    semester: Semester
    major: Optional[Major] = None  # Required for year 4-5, CS/CT for year 3
    section: Optional[Section] = None  # Required for year 1-3 only
    exam_score: float = Field(ge=0, le=100)

    @model_validator(mode='after')
    def validate_section_and_major(self):
        """Validate section and major based on year:
        - Year 1-2: section required (A/B/C), no major
        - Year 3: section required (A/B/C), major required (CS/CT)
        - Year 4-5: major required (SE/KE/etc.), no section
        """
        if self.year in [1, 2]:
            if not self.section:
                raise ValueError(f"Section (A/B/C) is required for year {self.year}")
            if self.major:
                raise ValueError(f"Major should not be set for year {self.year}")
        elif self.year == 3:
            if not self.section:
                raise ValueError("Section (A/B/C) is required for year 3")
            if not self.major:
                raise ValueError("Major (CS/CT) is required for year 3")
            if self.major not in ["CS", "CT"]:
                raise ValueError("Year 3 major must be CS or CT")
        elif self.year in [4, 5]:
            if self.section:
                raise ValueError(f"Section should not be set for year {self.year}")
            if not self.major:
                raise ValueError(f"Major is required for year {self.year}")
        return self

class ExamResultOut(BaseModel):
    student_id: str
    student_name: Optional[str] = None
    course_code: str
    year: int
    semester: int  # 1 or 2
    major: Optional[str] = None
    section: Optional[str] = None  # A, B, C, or null - accept any to avoid dropping records
    exam_score: float
    grade: str
    grade_point: float
    status: str
