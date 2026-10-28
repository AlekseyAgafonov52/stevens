"""Вход по логину и паролю."""
import asyncio
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Header
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Account, AuthToken
from app.owner import account_by_token, bearer, token_hash
from app.security import hash_password, pwd_context, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOGIN_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9._-]{3,32}$")
TOKEN_DAYS = 30  # живёт не меньше 30 дней


def error(status: int, code: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code})


def _credentials(payload: object) -> tuple[str, str] | JSONResponse:
    if not isinstance(payload, dict):
        return error(422, "invalid_login")
    login, password = payload.get("login"), payload.get("password")
    if not isinstance(login, str) or not LOGIN_RE.match(login.strip()):
        return error(422, "invalid_login")
    if not isinstance(password, str) or not 5 <= len(password) <= 128:
        return error(422, "invalid_password")
    try:
        password.encode("utf-8")
    except UnicodeError:
        return error(422, "invalid_password")
    return login.strip(), password


async def _issue(db: AsyncSession, account: Account) -> dict:
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(
        account_id=account.id,
        token_hash=token_hash(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS),
    ))
    await db.commit()
    return {"token": token, "user": {"id": account.id, "login": account.login}}


@router.post("/register")
async def register(payload: object = Body(default=None), db: AsyncSession = Depends(get_db)):
    checked = _credentials(payload)
    if isinstance(checked, JSONResponse):
        return checked
    login, password = checked
    exists = (await db.execute(select(Account).where(Account.login_lower == login.lower()))).scalars().first()
    if exists:
        return error(409, "login_taken")
    # argon2 считает ~0,2 с: в отдельном потоке, чтобы чат других не ждал
    account = Account(login=login, login_lower=login.lower(), password_hash=await asyncio.to_thread(hash_password, password))
    db.add(account)
    try:
        await db.flush()
    except IntegrityError:  # двойной клик «Зарегистрироваться»: логин занял соседний запрос
        await db.rollback()
        return error(409, "login_taken")
    # Аккаунт создаётся пустым: песочница не переносится
    return await _issue(db, account)


@router.post("/login")
async def login(payload: object = Body(default=None), db: AsyncSession = Depends(get_db)):
    if not isinstance(payload, dict) or not isinstance(payload.get("login"), str) or not isinstance(payload.get("password"), str):
        return error(401, "invalid_credentials")
    if not 5 <= len(payload["password"]) <= 128:
        return error(401, "invalid_credentials")
    account = (await db.execute(
        select(Account).where(Account.login_lower == payload["login"].strip().lower())
    )).scalars().first()
    # И при неверном пароле, и при несуществующем логине — одна ошибка
    if not account or not await asyncio.to_thread(verify_password, payload["password"], account.password_hash):
        return error(401, "invalid_credentials")
    if pwd_context.needs_update(account.password_hash):
        account.password_hash = await asyncio.to_thread(hash_password, payload["password"])
    return await _issue(db, account)


@router.post("/logout", status_code=204)
async def logout(authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    token = bearer(authorization)
    if token:
        row = (await db.execute(select(AuthToken).where(AuthToken.token_hash == token_hash(token)))).scalars().first()
        if row and row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            await db.commit()
    return Response(status_code=204)


@router.get("/me")
async def me(authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    token = bearer(authorization)
    account = await account_by_token(db, token) if token else None
    if not account:
        return error(401, "invalid_token")
    return {"user": {"id": account.id, "login": account.login}}
