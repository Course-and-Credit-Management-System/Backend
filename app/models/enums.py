from enum import Enum

class Role(str, Enum):
    STUDENT = "student"
    ADMIN = "admin"

class AcademicStatus(str, Enum):
    ACTIVE = "Active"
    PROBATION = "Probation"
    SUSPENDED = "Suspended"
    GRADUATED = "Graduated"
    MAJOR_CHANGE = "majorChange"

class AccessLevel(str, Enum):
    SUPER_ADMIN = "super_admin"
    REGISTRAR = "registrar"
    INSTRUCTOR = "instructor"

class AcademicYear(str, Enum):
    # New Curriculum
    FIRST_YEAR_FIRST_SEM_NEW = "New . 1st Year . First Sem"
    FIRST_YEAR_SECOND_SEM_NEW = "New . 1st Year . Second Sem"
    SECOND_YEAR_FIRST_SEM_NEW = "New . 2nd Year . First Sem"
    SECOND_YEAR_SECOND_SEM_NEW = "New . 2nd Year . Second Sem"
    THIRD_YEAR_FIRST_SEM_NEW = "New . 3rd Year . First Sem"
    THIRD_YEAR_SECOND_SEM_NEW = "New . 3rd Year . Second Sem"
    FOURTH_YEAR_FIRST_SEM_NEW = "New . 4th Year . First Sem"
    FOURTH_YEAR_SECOND_SEM_NEW = "New . 4th Year . Second Sem"
    
    # Old Curriculum
    FIRST_YEAR_FIRST_SEM_OLD = "Old . 1st Year . First Sem"
    FIRST_YEAR_SECOND_SEM_OLD = "Old . 1st Year . Second Sem"
    SECOND_YEAR_FIRST_SEM_OLD = "Old . 2nd Year . First Sem"
    SECOND_YEAR_SECOND_SEM_OLD = "Old . 2nd Year . Second Sem"
    THIRD_YEAR_FIRST_SEM_OLD = "Old . 3rd Year . First Sem"
    THIRD_YEAR_SECOND_SEM_OLD = "Old . 3rd Year . Second Sem"
    FOURTH_YEAR_FIRST_SEM_OLD = "Old . 4th Year . First Sem"
    FOURTH_YEAR_SECOND_SEM_OLD = "Old . 4th Year . Second Sem"
    FIFTH_YEAR_FIRST_SEM_OLD = "Old . 5th Year . First Sem"
    FIFTH_YEAR_SECOND_SEM_OLD = "Old . 5th Year . Second Sem"
