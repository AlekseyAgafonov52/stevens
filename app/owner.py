"""Заголовок режима (раздел 14): Authorization: Bearer <token> в аккаунте или
X-Client-Id: <uuid> в песочнице. Пришли оба — используется Authorization.
Не пришло ни одного — общая демо-база.
"""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, Header, HTTPException
from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Account, AuthToken, DateKind, Record, Sandbox, TaskStatus, TaskType

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "events_1000.csv"
SHARED_SANDBOX = "shared-demo"
CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
MEETING_FIRST_WORDS = {"встреча", "созвон", "демо"}


@dataclass
class Owner:
    account: Account | None = None
    sandbox_id: str | None = None

    @property
    def key(self) -> str:
        return f"a:{self.account.id}" if self.account else f"s:{self.sandbox_id}"

    def owns(self, record: Record) -> bool:
        if self.account:
            return record.account_id == self.account.id
        return record.sandbox_id == self.sandbox_id

    def filter(self):
        return Record.account_id == self.account.id if self.account else Record.sandbox_id == self.sandbox_id

    def new_record(self, **fields) -> Record:
        if self.account:
            return Record(account_id=self.account.id, **fields)
        return Record(sandbox_id=self.sandbox_id, **fields)


def demo_rows() -> list[dict]:
    """1000 записей CSV организаторов. Тип угадываем по первому слову (О-01)."""
    rows = []
    # Время создания есть у каждой записи: у демо — момент, когда песочницу заполнили
    created = datetime.now(timezone.utc)
    with CSV_PATH.open(encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            first = row["text"].split(" ", 1)[0].lower()
            meeting = first in MEETING_FIRST_WORDS
            rows.append({
                "type": TaskType.meeting if meeting else TaskType.task,
                "text": row["text"].strip(),
                "date": row["date"] or None,
                "time": row["time"] or None,
                "date_kind": DateKind.exact if row["date"] else DateKind.none,
                "status": None if meeting else TaskStatus.open,
                "created_at": created,
                "demo": True,
            })
    return rows


async def seed_sandbox(db: AsyncSession, client_id: str) -> None:
    await db.execute(delete(Record).where(Record.sandbox_id == client_id))
    await db.execute(insert(Record), [{**row, "sandbox_id": client_id} for row in demo_rows()])


async def ensure_sandbox(db: AsyncSession, client_id: str) -> None:
    """Неизвестный id → заводим песочницу и копируем в неё демо-данные."""
    if await db.get(Sandbox, client_id):
        return
    # Первые запросы новой вкладки идут разом: песочницу заводит только один из них
    created = await db.execute(
        pg_insert(Sandbox).values(client_id=client_id).on_conflict_do_nothing().returning(Sandbox.client_id)
    )
    if created.scalar() is None:
        return
    await seed_sandbox(db, client_id)
    await db.commit()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def account_by_token(db: AsyncSession, token: str) -> Account | None:
    row = (await db.execute(select(AuthToken).where(AuthToken.token_hash == token_hash(token)))).scalars().first()
    if not row or row.revoked_at is not None:
        return None
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        return None
    return await db.get(Account, row.account_id)


def bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


async def get_owner(
    authorization: str | None = Header(default=None),
    x_client_id: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Owner:
    token = bearer(authorization)
    if token:
        account = await account_by_token(db, token)
        if not account:
            raise HTTPException(status_code=401, detail={"error": "invalid_token"})
        return Owner(account=account)
    client_id = (x_client_id or "").strip()
    if client_id:
        if not CLIENT_ID_RE.match(client_id):
            raise HTTPException(status_code=422, detail={"error": "invalid_client_id"})
        await ensure_sandbox(db, client_id)
        return Owner(sandbox_id=client_id)
    await ensure_sandbox(db, SHARED_SANDBOX)
    return Owner(sandbox_id=SHARED_SANDBOX)
