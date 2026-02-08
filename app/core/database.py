"""Database configuration for MongoDB."""
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from app.core.config import get_settings
from app.models.user import User
from app.models.major import Major
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.announcement import Announcement
from app.models.message import Message
from app.models.student_result import StudentResultDB

settings = get_settings()

# MongoDB client
client: AsyncIOMotorClient = None


async def init_db():
    """Initialize MongoDB connection and Beanie ODM."""
    global client
    
    # Use connection string from environment
    # For Atlas, the connection string should include tls parameters
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    database = client[settings.MONGODB_DB_NAME]
    
    # Test connection
    await client.admin.command('ping')
    print("Successfully connected to MongoDB!")
    
    # Initialize Beanie with document models
    await init_beanie(
        database=database,
        document_models=[
            User,
            Major,
            Course,
            Enrollment,
            Announcement,
            Message,
            StudentResultDB,
        ]
    )


async def close_db():
    """Close MongoDB connection."""
    if client:
        client.close()


async def get_db():
    """Get MongoDB database instance."""
    if client is None:
        await init_db()
    return client[settings.MONGODB_DB_NAME]


async def get_database():
    """
    Compatibility alias used by endpoints/services.
    Returns the MongoDB database instance.
    """
    return await get_db()
