from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from jose import jwt

from app.core.config import settings
from app.core.database import get_database
from app.core.security import hash_password, verify_password
from app.api.v1.deps.auth import get_current_user
from pydantic import BaseModel, EmailStr
from passlib.hash import bcrypt

from app.core.email import send_reset_email
from app.core.reset_tokens import generate_reset_token, hash_token, get_expiry_time


router = APIRouter(prefix="/auth", tags=["auth"])

async def _get_col(db, names: list[str]):
    cols = await db.list_collection_names()
    for n in names:
        if n in cols:
            return db[n]
    # default to first name
    return db[names[0]]
class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordWithTokenRequest(BaseModel):
    token: str
    new_password: str


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
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    role = (payload.get("role") or "").strip()

    if not username or not password or not role:
        raise HTTPException(status_code=422, detail="username, password, role are required")

    db = await get_database()
    users = await _get_col(db, ["Users", "users"])
    creds = await _get_col(db, ["AuthCredentials", "authcredentials"])

    user = await users.find_one(
        {
            "$and": [
                {"$or": [{"user_id": username}, {"email": username}]},
                {"role": {"$regex": f"^{role}$", "$options": "i"}},
            ]
        }
    )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

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
        "access_token": access_token,
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


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, db=Depends(get_database)):
    # Always return success to avoid user enumeration
    email = payload.email.strip().lower()

    user = await db["Users"].find_one({"email": email})
    if not user:
        return {"message": "If the account exists, we sent an email."}

    user_id = user["user_id"]

    raw_token = generate_reset_token()
    token_hash = hash_token(raw_token)
    expires_at = get_expiry_time()

    # ✅ OPTIONAL: invalidate older tokens for this user (recommended)
    await db["ResetTokens"].update_many(
        {"user_id": user_id, "used": False},
        {"$set": {"used": True, "used_at": datetime.utcnow()}},
    )

    # ✅ Create a new reset token record
    await db["ResetTokens"].insert_one(
        {
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "used": False,
            "created_at": datetime.utcnow(),
            "used_at": None,
        }
    )

    try:
        send_reset_email(to_email=email, reset_token=raw_token)
    except Exception:
        # Don't leak details
        return {"message": "If the account exists, we sent an email."}

    return {"message": "If the account exists, we sent an email."}


@router.post("/reset-password-with-token")
async def reset_password_with_token(payload: ResetPasswordWithTokenRequest, db=Depends(get_database)):
    token = payload.token.strip()
    new_password = payload.new_password

    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    if len(new_password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="Password too long (bcrypt max 72 bytes).")

    token_hash = hash_token(token)

    # ✅ Lookup token in ResetTokens
    reset_doc = await db["ResetTokens"].find_one({"token_hash": token_hash})
    if not reset_doc:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")

    if reset_doc.get("used") is True:
        raise HTTPException(status_code=400, detail="Reset token already used.")

    expires_at = reset_doc.get("expires_at")
    if not expires_at or expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")

    user_id = reset_doc["user_id"]

    # ✅ Ensure user has credentials row
    creds = db["AuthCredentials"]
    cred = await creds.find_one({"user_id": user_id})
    if not cred:
        raise HTTPException(status_code=400, detail="No credentials found for this user.")

    # ✅ Hash & update password
    new_hash = hash_password(new_password)

    await creds.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "password_hash": new_hash,
                "must_reset_password": False,
                "updated_at": datetime.utcnow(),
            }
        },
    )

    # ✅ Mark token used
    await db["ResetTokens"].update_one(
        {"_id": reset_doc["_id"]},
        {"$set": {"used": True, "used_at": datetime.utcnow()}},
    )

    return {"message": "Password reset successfully. Please log in."}
