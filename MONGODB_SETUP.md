# MongoDB Atlas Setup Instructions

## Schema & Collections
This project assumes strict collection naming. Ensure your collections are named:
- `Courses`
- `Enrollments`

## Option 1: MongoDB Atlas (Recommended for Cloud)
1. Go to https://www.mongodb.com/atlas and sign up for free
2. Create a new cluster (free tier available)
3. In Database Access, create a new user with password
4. In Network Access, add your IP or allow all (0.0.0.0/0)
5. Click "Connect" → "Drivers" → "Python"
6. Copy the connection string and update your .env file:

```
MONGODB_URL=mongodb+srv://<username>:<password>@<cluster>.mongodb.net
```

## Option 2: Local MongoDB
Install MongoDB locally:
```bash
# Using winget
winget install MongoDB.Server

# Or download from https://www.mongodb.com/try/download/community
```

## Option 3: Docker (Fastest for local)
```bash
docker run -d -p 27017:27017 --name mongodb mongo:latest
```

## Running the App

```bash
# Set Python path and run
export PATH="/c/Users/USER/AppData/Local/Programs/Python/Python311:/c/Users/USER/AppData/Local/Programs/Python/Python311/Scripts:$PATH"

# Run the application
uvicorn app.main:app --reload

# Or run tests
pytest
```

## API Endpoints

Once running, access:
- http://localhost:8000/docs - Interactive API documentation
- http://localhost:8000/api/v1/health/health - Health check
- http://localhost:8000/api/v1/users/ - User CRUD operations
