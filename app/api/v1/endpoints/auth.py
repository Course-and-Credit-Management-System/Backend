from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from jose import jwt

from app.core.config import settings
from app.core.database import get_database
from app.core.security import hash_password, verify_password
from app.api.v1.deps.auth import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie_params():
    """
    Centralize cookie settings.
    - Local dev (HTTP): secure=False, samesite="lax"
    - Production (HTTPS): secure=True, samesite="none" (if frontend+backend different domains)
    """
    # For most local demos (same IP, different ports), Lax works.
    # If you deploy with frontend+backend on different domains, use SameSite=None + Secure=True.
    return dict(
        key=settings.COOKIE_NAME,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        # domain=settings.COOKIE_DOMAIN,  # only if you add it in config (usually not needed)
    )


@router.post("/login")
async def login(payload: dict, response: Response):
    username = payload.get("username")
    password = payload.get("password")
    role = payload.get("role")
    
    print(f"LOGIN DEBUG: Attempting login for user='{username}', role='{role}'")

    if not username or not password or not role:
        print("LOGIN DEBUG: Missing fields")
        raise HTTPException(status_code=422, detail="username, password, role are required")

    db = await get_database()
    users = db["Users"]
    creds = db["AuthCredentials"]

    user = await users.find_one(
        {"$or": [{"user_id": username}, {"email": username}], "role": role}
    )
    if not user:
        # Try finding without role to see if it's a role mismatch
        user_check = await users.find_one({"$or": [{"user_id": username}, {"email": username}]})
        if user_check:
             print(f"LOGIN DEBUG: User found but ROLE MISMATCH. DB role: '{user_check.get('role')}', Request role: '{role}'")
        else:
             print("LOGIN DEBUG: User NOT found in 'Users' collection")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    print(f"LOGIN DEBUG: User found: {user.get('_id')}")
    cred = await creds.find_one({"user_id": user["user_id"]})

    # First-time bootstrap: create credentials with DEFAULT_PASSWORD
    if not cred:
        if len(settings.DEFAULT_PASSWORD.encode("utf-8")) > 72:
            raise HTTPException(status_code=500, detail="DEFAULT_PASSWORD too long (bcrypt max 72 bytes)")

        default_hash = hash_password(settings.DEFAULT_PASSWORD)

        cred = {
            "user_id": user["user_id"],
            "password_hash": default_hash,
            "must_reset_password": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        await creds.insert_one(cred)

    if not verify_password(password, cred["password_hash"]):
        print(f"LOGIN DEBUG: Password verification failed for user {username}")
        # print(f"  Input: {password}")
        # print(f"  Hash:  {cred['password_hash']}")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token_payload = {"sub": user["user_id"], "role": user["role"], "exp": expire}
    access_token = jwt.encode(token_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    # ✅ Set HttpOnly cookie (this is the REALISTIC method)
    response.set_cookie(
        **_cookie_params(),
        value=access_token,
    )

    user_out = dict(user)
    user_out["_id"] = str(user_out.get("_id"))

    return {
        "token_type": "cookie",
        "must_reset_password": bool(cred.get("must_reset_password", False)),
        "user": user_out,
    }


@router.get("/me")
async def me(current_user=Depends(get_current_user)):
    return current_user


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key=settings.COOKIE_NAME, path="/")
    return {"message": "Logged out"}


@router.post("/reset-password")
async def reset_password(payload: dict, current_user=Depends(get_current_user)):
    old_password = payload.get("old_password")
    new_password = payload.get("new_password")

    if not old_password or not new_password:
        raise HTTPException(status_code=422, detail="old_password and new_password are required")

    if len(new_password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="Password too long (bcrypt max 72 bytes)")

    db = await get_database()
    creds = db["AuthCredentials"]

    cred = await creds.find_one({"user_id": current_user["user_id"]})
    if not cred:
        raise HTTPException(status_code=400, detail="No credentials found for this user")

    if not verify_password(old_password, cred["password_hash"]):
        raise HTTPException(status_code=401, detail="Old password incorrect")

    new_hash = hash_password(new_password)

    await creds.update_one(
        {"user_id": current_user["user_id"]},
        {"$set": {
            "password_hash": new_hash,
            "must_reset_password": False,
            "updated_at": datetime.now(timezone.utc)
        }},
    )

    return {"message": "Password updated successfully"}
