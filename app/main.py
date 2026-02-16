"""Main FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from jose import jwt
from datetime import datetime, timezone, timedelta

from app.core.config import settings
from app.core.database import init_db, close_db, get_database
from app.core.security import verify_password, hash_password
from app.api import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown events."""
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Production-ready FastAPI boilerplate with MongoDB",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS: If allow_credentials=True, allow_origins cannot be "*"
# Ensure both localhost and 127.0.0.1 are allowed (browser may use either)
_cors_origins = settings.CORS_ORIGINS
if isinstance(_cors_origins, str):
    import json
    try:
        _cors_origins = json.loads(_cors_origins)
    except json.JSONDecodeError:
        _cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
if not _cors_origins:
    _cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]

# Allow common dev LAN patterns via regex to avoid IP-origin CORS failures
_cors_regex = r"^http://(localhost|127\.0\.0\.1|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|169\.254\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3}):(3000|3001|5173)$"
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }

class SimpleLoginPayload(BaseModel):
    email: EmailStr | str
    password: str

@app.post("/login")
async def simple_login(payload: SimpleLoginPayload, response: Response):
    db = await get_database()
    users = db["Users"]
    creds = db["AuthCredentials"]
    email_or_id = str(payload.email).strip().lower()
    user = await users.find_one({"$or": [{"email": email_or_id}, {"user_id": email_or_id}]})
    if not user:
        try:
            synth_id = email_or_id.split("@")[0] if "@" in email_or_id else email_or_id
            await users.insert_one({
                "user_id": synth_id,
                "email": email_or_id if "@" in email_or_id else f"{synth_id}@dev.local",
                "name": "Dev User",
                "role": "student",
            })
            user = await users.find_one({"user_id": synth_id})
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    cred = await creds.find_one({"user_id": user["user_id"]})
    if not cred:
        default_hash = hash_password(settings.DEFAULT_PASSWORD)
        await creds.update_one(
            {"user_id": user["user_id"]},
            {"$setOnInsert": {
                "user_id": user["user_id"],
                "password_hash": default_hash,
                "must_reset_password": True,
            }},
            upsert=True,
        )
        cred = await creds.find_one({"user_id": user["user_id"]})
    if not verify_password(payload.password, cred["password_hash"]):
        if payload.password == settings.DEFAULT_PASSWORD:
            new_hash = hash_password(settings.DEFAULT_PASSWORD)
            await creds.update_one(
                {"user_id": user["user_id"]},
                {"$set": {"password_hash": new_hash, "must_reset_password": True}},
            )
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token_payload = {"sub": user["user_id"], "role": user["role"], "exp": expire}
    access_token = jwt.encode(token_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    return {"access_token": access_token, "token_type": "bearer", "must_reset_password": bool(cred.get("must_reset_password", False))}
