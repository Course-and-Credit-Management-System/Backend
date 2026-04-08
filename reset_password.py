import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Load env before importing app config
load_dotenv(Path(__file__).resolve().parent / ".env")

from app.core.config import settings
from app.core.security import hash_password


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset a user's password in AuthCredentials.")
    parser.add_argument("user_id", help="User ID to update, for example TNT-8808")
    parser.add_argument("password", help="New plain-text password to hash and store")
    return parser.parse_args()


async def reset_pwd(user_id: str, new_password: str) -> None:
    print(f"Connecting to DB: {settings.MONGODB_DB_NAME}")
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]

    try:
        creds = db["AuthCredentials"]

        hashed = hash_password(new_password)

        result = await creds.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "password_hash": hashed,
                    "must_reset_password": False,
                }
            },
            upsert=True,
        )

        print(f"Password updated for '{user_id}'.")
        print(
            f"Matched: {result.matched_count}, Modified: {result.modified_count}, "
            f"Upserted: {result.upserted_id}"
        )
    finally:
        client.close()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(reset_pwd(args.user_id, args.password))
