"""Database configuration for MongoDB."""
import asyncio
from typing import Optional

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConfigurationError, PyMongoError

from app.core.config import get_settings
from app.models.alert import Alert
from app.models.announcement import Announcement
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.enrollment_setting import EnrollmentSetting
from app.models.major import Major
from app.models.message import Message
from app.models.student_result import StudentResultDB
from app.models.user import User

settings = get_settings()

# MongoDB client
client: AsyncIOMotorClient = None


async def init_db():
    """Initialize MongoDB connection and Beanie ODM."""
    global client

    async def _connect(url: str, attempts: int = 3) -> AsyncIOMotorClient:
        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            mongo_client = AsyncIOMotorClient(
                url,
                # Atlas/SRV discovery can be slow on some networks.
                serverSelectionTimeoutMS=15000,
                connectTimeoutMS=10000,
                socketTimeoutMS=20000,
            )
            try:
                await mongo_client.admin.command("ping")
                return mongo_client
            except (ConfigurationError, PyMongoError) as exc:
                last_error = exc
                mongo_client.close()
                if attempt < attempts:
                    await asyncio.sleep(attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError("MongoDB connection failed for an unknown reason.")

    client = None
    primary_error: Optional[Exception] = None

    try:
        client = await _connect(settings.MONGODB_URL)
        print("Successfully connected to MongoDB (primary URL).")
    except (ConfigurationError, PyMongoError) as exc:
        primary_error = exc
        fallback_url = settings.MONGODB_FALLBACK_URL
        if fallback_url:
            try:
                client = await _connect(fallback_url)
                print("Primary MongoDB connection failed, connected via fallback URL.")
            except (ConfigurationError, PyMongoError) as fallback_exc:
                raise RuntimeError(
                    "MongoDB connection failed for both primary MONGODB_URL and "
                    f"MONGODB_FALLBACK_URL. primary_error={primary_error!r}; "
                    f"fallback_error={fallback_exc!r}"
                ) from fallback_exc
        else:
            raise RuntimeError(
                "MongoDB connection failed. If you are using mongodb+srv and your network "
                "blocks DNS SRV lookups, set MONGODB_FALLBACK_URL to a reachable mongodb:// URI. "
                f"primary_error={exc!r}"
            ) from exc

    if client is None:
        raise RuntimeError("MongoDB client was not initialized.") from primary_error

    database = client[settings.MONGODB_DB_NAME]

    await database["ResetTokens"].create_index("token_hash", unique=True)
    await database["ResetTokens"].create_index([("user_id", 1), ("created_at", -1)])
    await database["ResetTokens"].create_index("expires_at")
    print("ResetTokens indexes ensured.")

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
        ],
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
