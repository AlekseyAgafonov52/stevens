"""Подписка на пуш-уведомления: ключ сервера, подписаться, отписаться, отложить на 10 минут."""
from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse, Response
from datetime import datetime, timedelta, timezone
import hmac

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import push
from app.database import get_db
from app.models import PushSnooze, PushSubscription, Record
from app.owner import Owner, get_owner
from app.logic.push_targets import allowed_endpoint, valid_keys

router = APIRouter(prefix="/api/push", tags=["push"])


@router.get("/key")
async def key():
    return {"key": await push.public_key()}


@router.post("/subscribe", status_code=204)
async def subscribe(
    body: dict = Body(...),
    owner: Owner = Depends(get_owner),
    db: AsyncSession = Depends(get_db),
):
    endpoint = body.get("endpoint")
    keys = body.get("keys") or {}
    tz = body.get("timezone") or "UTC"
    if not allowed_endpoint(endpoint) or not valid_keys(keys):
        return JSONResponse(status_code=422, content={"error": "invalid_subscription"})
    await db.execute(pg_insert(PushSubscription).values(endpoint=endpoint, p256dh=keys["p256dh"], auth=keys["auth"],
        timezone=str(tz)[:64], account_id=owner.account.id if owner.account else None, sandbox_id=owner.sandbox_id)
        .on_conflict_do_nothing(index_elements=[PushSubscription.endpoint]))
    sub = (await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint).with_for_update())).scalar_one()
    if not (hmac.compare_digest(sub.p256dh.rstrip("="), keys["p256dh"].rstrip("="))
            and hmac.compare_digest(sub.auth.rstrip("="), keys["auth"].rstrip("="))):
        await db.rollback()
        return JSONResponse(status_code=422, content={"error": "invalid_subscription"})
    # Тот же браузер мог войти в аккаунт после песочницы — подписка переезжает к новому владельцу
    sub.account_id = owner.account.id if owner.account else None
    sub.sandbox_id = None if owner.account else owner.sandbox_id
    sub.p256dh = keys["p256dh"][:200]
    sub.auth = keys["auth"][:100]
    sub.timezone = str(tz)[:64]
    sub.seen_at = datetime.now(timezone.utc)
    await db.commit()
    return Response(status_code=204)


@router.post("/unsubscribe", status_code=204)
async def unsubscribe(body: dict = Body(...), db: AsyncSession = Depends(get_db)):
    endpoint = body.get("endpoint")
    if isinstance(endpoint, str):
        await db.execute(delete(PushSubscription).where(PushSubscription.endpoint == endpoint))
        await db.commit()
    return Response(status_code=204)


@router.post("/snooze", status_code=204)
async def snooze(body: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """Кнопка «Через 10 минут» в пуше и «Напомнить позже» в чате (minutes — через сколько, по умолчанию 10).
    Service worker не знает токена входа, поэтому браузер узнаём по адресу его подписки — он есть только у него самого.
    Новое время заменяет прежнее отложенное по этой записи."""
    endpoint, record_id = body.get("endpoint"), body.get("record_id")
    minutes = body.get("minutes", int(push.SNOOZE.total_seconds() // 60))
    if not isinstance(endpoint, str) or isinstance(record_id, bool) or not isinstance(record_id, int) or not 1 <= record_id <= 2147483647:
        return JSONResponse(status_code=422, content={"error": "invalid_snooze"})
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= push.SNOOZE_MAX_MINUTES:
        return JSONResponse(status_code=422, content={"error": "invalid_snooze"})
    sub = (await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))).scalars().first()
    record = await db.get(Record, record_id)
    if not sub or not record or (record.account_id, record.sandbox_id) != (sub.account_id, sub.sandbox_id):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    await db.execute(delete(PushSnooze).where(PushSnooze.record_id == record_id))
    db.add(PushSnooze(
        account_id=sub.account_id, sandbox_id=sub.sandbox_id, record_id=record_id,
        at=datetime.now(timezone.utc) + timedelta(minutes=minutes),
    ))
    await db.commit()
    return Response(status_code=204)
