from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings
from app.core.database import get_database

security = HTTPBearer(auto_error=False)  # ✅ don't auto-throw if header missing


def _get_token_from_request(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    # ✅ 1) Prefer cookie auth (your main architecture)
    cookie_token = request.cookies.get(settings.COOKIE_NAME)  # "access_token"
    if cookie_token:
        return cookie_token

    # ✅ 2) Fallback: allow Authorization: Bearer for Swagger/manual testing
    if credentials:
        return credentials.credentials

    return None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    token = _get_token_from_request(request, credentials)

    if not token:
        raise HTTPException(status_code=403, detail="Not authenticated")

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token (no sub)")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    db = await get_database()
    user = await db["Users"].find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    cred = await db["AuthCredentials"].find_one({"user_id": user_id})
    user["must_reset_password"] = bool(cred.get("must_reset_password")) if cred else False

    user.pop("password_hash", None)
    user["_id"] = str(user.get("_id"))
    return user


async def require_admin(current_user=Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
