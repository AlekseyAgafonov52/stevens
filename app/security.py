from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["argon2"], argon2__memory_cost=65536, argon2__time_cost=3, argon2__parallelism=1)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except (ValueError, TypeError):
        return False
