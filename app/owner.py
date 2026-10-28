"""Заголовок режима: Authorization: Bearer <token> в аккаунте или
X-Client-Id: <uuid> в песочнице. Пришли оба — используется Authorization.
Не пришло ни одного — общая демо-база.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, Header, HTTPException
from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.models import (Account, AuthToken, DateKind, PushSnooze, PushSubscription, Record, Sandbox, Series,
                        TaskStatus, TaskType)

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


async def clear_sandbox(db: AsyncSession, client_id: str) -> None:
    """Remove sandbox records and repeats without filling it with demo data again."""
    await db.execute(delete(PushSnooze).where(PushSnooze.sandbox_id == client_id))
    await db.execute(delete(Record).where(Record.sandbox_id == client_id))
    await db.execute(delete(Series).where(Series.sandbox_id == client_id))


async def seed_sandbox(db: AsyncSession, client_id: str) -> None:
    # Сброс — одна транзакция; незавершенные повторы не должны возродить удаленные записи.
    await clear_sandbox(db, client_id)
    await db.execute(insert(Record), [{**row, "sandbox_id": client_id} for row in demo_rows()])


async def ensure_sandbox(db: AsyncSession, client_id: str) -> None:
    """Неизвестный id → заводим песочницу и копируем в неё демо-данные."""
    if box := await db.get(Sandbox, client_id):
        now = datetime.now(timezone.utc)
        if box.seen_at is None or box.seen_at < now - SEEN_STEP:
            await db.execute(update(Sandbox).where(Sandbox.client_id == client_id).values(seen_at=now))
            await db.commit()
        return
    # Первые запросы новой вкладки идут разом: песочницу заводит только один из них
    created = await db.execute(
        pg_insert(Sandbox).values(client_id=client_id).on_conflict_do_nothing().returning(Sandbox.client_id)
    )
    if created.scalar() is None:
        return
    await seed_sandbox(db, client_id)
    await db.commit()


SEEN_STEP = timedelta(hours=1)
CLEAN_EVERY = 6 * 3600


def sandbox_days() -> int:
    """Удалять песочницы, в которые не заходили столько дней: по умолчанию 30, STEVENS_SANDBOX_DAYS=0 — не удалять."""
    try:
        return max(0, int(os.getenv("STEVENS_SANDBOX_DAYS", "30")))
    except ValueError:
        return 0


async def clean_sandboxes(db: AsyncSession, days: int) -> int:
    """Каждая новая вкладка — 1000 демо-записей: заброшенные песочницы удаляем целиком. Общую не трогаем."""
    old = select(Sandbox.client_id).where(Sandbox.seen_at < datetime.now(timezone.utc) - timedelta(days=days),
                                          Sandbox.client_id != SHARED_SANDBOX)
    ids = list((await db.execute(old)).scalars().all())
    if not ids:
        return 0
    for table in (PushSnooze, PushSubscription, Record, Series):
        await db.execute(delete(table).where(table.sandbox_id.in_(ids)))
    await db.execute(delete(Sandbox).where(Sandbox.client_id.in_(ids)))
    await db.commit()
    return len(ids)


async def clean_loop() -> None:
    while days := sandbox_days():
        try:
            async with AsyncSessionLocal() as db:
                if removed := await clean_sandboxes(db, days):
                    print(f"🧹 Удалено заброшенных песочниц: {removed}")
        except Exception as error:  # noqa: BLE001
            print(f"⚠️ Чистка песочниц: {error}")
        await asyncio.sleep(CLEAN_EVERY)


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
    if authorization is not None and not token:
        raise HTTPException(status_code=401, detail={"error": "invalid_token"})
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
    raise HTTPException(status_code=422, detail={"error": "mode_required"})
