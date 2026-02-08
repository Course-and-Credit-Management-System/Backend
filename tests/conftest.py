"""Test configuration and fixtures."""
import pytest
from httpx import AsyncClient
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import app
from app.models.user import User


@pytest.fixture
async def test_db():
    """Create test database and initialize Beanie."""
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["test_fastapi_db"]
    
    await init_beanie(database=db, document_models=[User])
    
    yield db
    
    # Cleanup after tests
    await db.drop_collection("users")
    client.close()


@pytest.fixture
async def client(test_db):
    """Create async test client."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def sample_user(test_db):
    """Create a sample user for testing."""
    user = User(
        email="test@example.com",
        username="testuser",
        full_name="Test User",
        hashed_password="hashed_password123",
        is_active=True,
    )
    await user.insert()
    return user
