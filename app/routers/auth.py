from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, AuthSession
from app.security import hash_password, verify_password, generate_token
from app.deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

async def _auth_response(db: AsyncSession, user: User) -> dict:
    token, token_hash, expires_at = generate_token()
    session = AuthSession(user_id=user.id, token_hash=token_hash, expires_at=expires_at)
    db.add(session)
    await db.commit()
    return {
        "token": token, 
        "user": {"id": user.id, "email": user.email, "name": user.name}, 
        "expires_at": expires_at.isoformat()
    }

@router.post("/register")
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    email = payload.email.lower().strip()
    # Проверка на существование
    result = await db.execute(select(User).where(User.email == email))
    if result.scalars().first():
        raise HTTPException(status_code=409, detail="Пользователь с таким email уже зарегистрирован")
    
    user = User(email=email, name=payload.name.strip(), password_hash=hash_password(payload.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return await _auth_response(db, user)

@router.post("/login")
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    email = payload.email.lower().strip()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    return await _auth_response(db, user)

@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "name": user.name}