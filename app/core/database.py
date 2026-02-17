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
from app.models.alert import Alert
from app.models.enrollment_setting import EnrollmentSetting

settings = get_settings()

# MongoDB client
client: AsyncIOMotorClient = None


async def init_db():
    """Initialize MongoDB connection and Beanie ODM."""
    global client
    
    # Use connection string from environment
    # For Atlas, the connection string should include tls parameters
    client = AsyncIOMotorClient(
        settings.MONGODB_URL,
        serverSelectionTimeoutMS=5000,  # 5 second timeout
        connectTimeoutMS=10000,  # 10 second connection timeout
        socketTimeoutMS=20000  # 20 second socket timeout
    )
    database = client[settings.MONGODB_DB_NAME]
    
    # Test connection
    await client.admin.command('ping')
    print("Successfully connected to MongoDB!")
    
        # 🔐 CREATE INDEXES FOR PASSWORD RESET TOKENS (NEW)
    await database["ResetTokens"].create_index("token_hash", unique=True)
    await database["ResetTokens"].create_index([("user_id", 1), ("created_at", -1)])
    await database["ResetTokens"].create_index("expires_at")

    print("ResetTokens indexes ensured.")

    
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
            Alert,
            EnrollmentSetting,
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
