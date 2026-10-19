from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import hashlib
from datetime import datetime, timezone

from app.database import get_db
from app.models import User, AuthSession

# Схема авторизации (Bearer Token)
security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Проверяет токен из заголовка Authorization и возвращает объект пользователя.
    """
    token = credentials.credentials
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    # Ищем активную сессию по хэшу токена
    stmt = select(AuthSession).where(
        AuthSession.token_hash == token_hash,
        AuthSession.revoked_at.is_(None),
        AuthSession.expires_at > datetime.now(timezone.utc)
    )
    result = await db.execute(stmt)
    session = result.scalars().first()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или истекший токен",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    # Получаем пользователя по ID из сессии
    user = await db.get(User, session.user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    return user 