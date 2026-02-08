import secrets
import hashlib
from datetime import datetime, timedelta


RESET_TOKEN_EXPIRE_MINUTES = 30


def generate_reset_token():
    # raw token sent in email
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_expiry_time():
    return datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
