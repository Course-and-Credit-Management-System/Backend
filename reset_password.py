import asyncio
import os
from dotenv import load_dotenv

# Load env before importing app config
load_dotenv("c:/FastApi/Backend/.env")

from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
from app.core.security import hash_password

async def reset_pwd():
    print(f"Connecting to DB: {settings.MONGODB_DB_NAME}")
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    creds = db["AuthCredentials"]
    
    user_id = "ADM-005"
    new_password = "mtt"
    
    # Generate new hash
    hashed = hash_password(new_password)
    
    # Update
    result = await creds.update_one(
        {"user_id": user_id},
        {"$set": {"password_hash": hashed, "must_reset_password": False}},
        upsert=True
    )
    
    print(f"Successfully set password for '{user_id}' to '{new_password}'")
    print(f"Matched: {result.matched_count}, Modified: {result.modified_count}, Upserted: {result.upserted_id}")

if __name__ == "__main__":
    asyncio.run(reset_pwd())