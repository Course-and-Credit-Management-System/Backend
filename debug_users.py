import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

async def list_users():
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    # Check Users collection
    users_coll = db["Users"] # TitleCase as mandated
    count = await users_coll.count_documents({})
    print(f"Users found (Collection 'Users'): {count}")
    
    async for user in users_coll.find({}):
        print(f"User: {user.get('user_id')}, Email: {user.get('email')}, Role: {user.get('role')}")

    # Check snake_case just in case
    users_coll_snake = db["users"]
    count_snake = await users_coll_snake.count_documents({})
    if count_snake > 0:
        print(f"WARNING: Found {count_snake} users in 'users' collection.")

if __name__ == "__main__":
    asyncio.run(list_users())