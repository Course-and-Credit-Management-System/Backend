"""Tests for user CRUD operations."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_user(client: AsyncClient):
    """Test creating a new user."""
    user_data = {
        "email": "newuser@example.com",
        "username": "newuser",
        "full_name": "New User",
        "password": "securepassword123",
        "is_active": True,
    }
    
    response = await client.post("/api/v1/users/", json=user_data)
    
    assert response.status_code == 201
    data = response.json()
    
    assert data["email"] == user_data["email"]
    assert data["username"] == user_data["username"]
    assert data["full_name"] == user_data["full_name"]
    assert data["is_active"] == user_data["is_active"]
    assert "_id" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_user_duplicate_email(client: AsyncClient, sample_user):
    """Test creating user with duplicate email fails."""
    user_data = {
        "email": sample_user.email,  # Same email
        "username": "differentuser",
        "full_name": "Different User",
        "password": "securepassword123",
    }
    
    response = await client.post("/api/v1/users/", json=user_data)
    
    assert response.status_code == 400
    assert "email" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_users(client: AsyncClient, sample_user):
    """Test retrieving all users."""
    response = await client.get("/api/v1/users/")
    
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["email"] == sample_user.email


@pytest.mark.asyncio
async def test_get_user_by_id(client: AsyncClient, sample_user):
    """Test retrieving a specific user by ID."""
    user_id = str(sample_user.id)
    response = await client.get(f"/api/v1/users/{user_id}")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["email"] == sample_user.email
    assert data["username"] == sample_user.username


@pytest.mark.asyncio
async def test_get_user_not_found(client: AsyncClient):
    """Test retrieving non-existent user returns 404."""
    fake_id = "507f1f77bcf86cd799439011"
    response = await client.get(f"/api/v1/users/{fake_id}")
    
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_user_invalid_id(client: AsyncClient):
    """Test retrieving user with invalid ID format."""
    response = await client.get("/api/v1/users/invalid-id")
    
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_update_user(client: AsyncClient, sample_user):
    """Test updating a user."""
    user_id = str(sample_user.id)
    update_data = {
        "full_name": "Updated Name",
        "is_active": False,
    }
    
    response = await client.put(f"/api/v1/users/{user_id}", json=update_data)
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["full_name"] == "Updated Name"
    assert data["is_active"] == False
    assert data["email"] == sample_user.email  # Unchanged


@pytest.mark.asyncio
async def test_update_user_not_found(client: AsyncClient):
    """Test updating non-existent user returns 404."""
    fake_id = "507f1f77bcf86cd799439011"
    update_data = {"full_name": "Updated Name"}
    
    response = await client.put(f"/api/v1/users/{fake_id}", json=update_data)
    
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_user(client: AsyncClient, sample_user):
    """Test deleting a user."""
    user_id = str(sample_user.id)
    response = await client.delete(f"/api/v1/users/{user_id}")
    
    assert response.status_code == 204
    
    # Verify user is deleted
    get_response = await client.get(f"/api/v1/users/{user_id}")
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_user_not_found(client: AsyncClient):
    """Test deleting non-existent user returns 404."""
    fake_id = "507f1f77bcf86cd799439011"
    response = await client.delete(f"/api/v1/users/{fake_id}")
    
    assert response.status_code == 404
