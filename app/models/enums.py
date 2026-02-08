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
    FIRST_YEAR_FIRST_SEM_NEW = "1st Year, First Sem(new)"
    FIRST_YEAR_SECOND_SEM_NEW = "1st Year, Second Sem(new)"
    SECOND_YEAR_FIRST_SEM_NEW = "2nd Year, First Sem(new)"
    SECOND_YEAR_SECOND_SEM_NEW = "2nd Year, Second Sem(new)"
    THIRD_YEAR_FIRST_SEM_NEW = "3rd Year, First Sem(new)"
    THIRD_YEAR_SECOND_SEM_NEW = "3rd Year, Second Sem(new)"
    FOURTH_YEAR_FIRST_SEM_NEW = "4th Year, First Sem(new)"
    FOURTH_YEAR_SECOND_SEM_NEW = "4th Year, Second Sem(new)"
    FIRST_YEAR_FIRST_SEM_OLD = "1st Year, First Sem(old)"
    FIRST_YEAR_SECOND_SEM_OLD = "1st Year, Second Sem(old)"
    SECOND_YEAR_FIRST_SEM_OLD = "2nd Year, First Sem(old)"
    SECOND_YEAR_SECOND_SEM_OLD = "2nd Year, Second Sem(old)"
    THIRD_YEAR_FIRST_SEM_OLD = "3rd Year, First Sem(old)"
    THIRD_YEAR_SECOND_SEM_OLD = "3rd Year, Second Sem(old)"
    FOURTH_YEAR_FIRST_SEM_OLD = "4th Year, First Sem(old)"
    FOURTH_YEAR_SECOND_SEM_OLD = "4th Year, Second Sem(old)"
    FIFTH_YEAR_FIRST_SEM_OLD = "5th Year, First Sem(old)"
    FIFTH_YEAR_SECOND_SEM_OLD = "5th Year, Second Sem(old)"
