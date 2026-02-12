from passlib.context import CryptContext

# Support both argon2 and bcrypt for verification.
# New hashes will use argon2 (stronger), but existing bcrypt hashes remain valid.
pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)
