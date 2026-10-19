import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def generate_token() -> tuple[str, str, datetime]:
    """Возвращает (сырой токен, хэш токена, дата истечения)."""
    token = secrets.token_urlsafe(32)
    # Хэшируем токен, чтобы хранить в базе в безопасности
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7) # Токен живет 7 дней
    return token, token_hash, expires_at