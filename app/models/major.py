from typing import List
from pydantic import Field
from beanie import Document

class Major(Document):
    id: str = Field(..., alias="_id", description="Manual Code ID (e.g., 'SE', 'CS')")
    major_name: str
    department: str
    requirements: List[str] = []

    class Settings:
        name = "majors"
