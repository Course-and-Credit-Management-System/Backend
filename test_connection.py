# test_connection.py
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

# Get the MongoDB URL from environment variables
mongodb_url = os.getenv("MONGODB_URL")

# Check if the environment variable is set
if not mongodb_url:
    print("❌ Connection failed: MONGODB_URL environment variable not set.")
    print("Please create a .env file in the 'Backend' directory and add your MongoDB connection string to it.")
    print("Example: MONGODB_URL=mongodb://localhost:27017/")
    exit() # Exit the script if the URL is not found

try:
    client = MongoClient(mongodb_url)
    db = client["academic_system"]
    # Test connection
    db.command("ping")
    print("✅ Successfully connected to MongoDB!")
    
    # List collections
    print("Collections:", db.list_collection_names())
    
except Exception as e:
    print(f"❌ Connection failed: {e}")