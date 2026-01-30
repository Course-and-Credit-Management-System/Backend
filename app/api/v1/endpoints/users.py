"""User CRUD endpoints."""
from typing import List
from datetime import datetime
from fastapi import APIRouter, HTTPException, status
from bson import ObjectId

from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate, UserResponse

router = APIRouter()


def hash_password(password: str) -> str:
    """Simple password hashing - replace with proper bcrypt in production."""
    # In production, use: from passlib.context import CryptContext
    # pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return f"hashed_{password}"


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user_data: UserCreate):
    """Create a new user."""
    # Check if user with email already exists
    existing_user = await User.find_one(User.email == user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )
    
    # Check if user with username already exists
    existing_username = await User.find_one(User.username == user_data.username)
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this username already exists"
        )
    
    # Create user
    user = User(
        email=user_data.email,
        username=user_data.username,
        full_name=user_data.full_name,
        hashed_password=hash_password(user_data.password),
        is_active=user_data.is_active,
    )
    
    await user.insert()
    return user


@router.get("/", response_model=List[UserResponse])
async def get_users(skip: int = 0, limit: int = 100):
    """Retrieve all users with pagination."""
    users = await User.find().skip(skip).limit(limit).to_list()
    return users


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: str):
    """Retrieve a specific user by ID."""
    if not ObjectId.is_valid(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format"
        )
    
    user = await User.get(ObjectId(user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(user_id: str, user_update: UserUpdate):
    """Update a user by ID."""
    if not ObjectId.is_valid(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format"
        )
    
    user = await User.get(ObjectId(user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Update fields
    update_data = user_update.model_dump(exclude_unset=True)
    
    if "password" in update_data:
        update_data["hashed_password"] = hash_password(update_data.pop("password"))
    
    update_data["updated_at"] = datetime.utcnow()
    
    # Check for duplicate email/username if being updated
    if "email" in update_data and update_data["email"] != user.email:
        existing = await User.find_one(User.email == update_data["email"])
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use"
            )
    
    if "username" in update_data and update_data["username"] != user.username:
        existing = await User.find_one(User.username == update_data["username"])
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already in use"
            )
    
    # Apply updates
    for field, value in update_data.items():
        setattr(user, field, value)
    
    await user.save()
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str):
    """Delete a user by ID."""
    if not ObjectId.is_valid(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format"
        )
    
    user = await User.get(ObjectId(user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    await user.delete()
    return None
