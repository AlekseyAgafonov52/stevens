import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated=["bcrypt"],
                          argon2__memory_cost=65536, argon2__time_cost=3, argon2__parallelism=1)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        if hashed_password.startswith(("$2a$", "$2b$", "$2y$")) and len(plain_password.encode("utf-8")) >= 72:
            return False  # Окончание старого пароля отсутствует в bcrypt-хеше, восстановить его нельзя.
        return pwd_context.verify(plain_password, hashed_password)
    except (ValueError, TypeError):
        return False

def generate_token() -> tuple[str, str, datetime]:
    """Возвращает (сырой токен, хэш токена, дата истечения)."""
    token = secrets.token_urlsafe(32)
    # Хэшируем токен, чтобы хранить в базе в безопасности
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    return token, token_hash, expires_at
