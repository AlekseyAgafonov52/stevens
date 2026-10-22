"""Подписка на пуш-уведомления: ключ сервера, подписаться, отписаться."""
from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import push
from app.database import get_db
from app.models import PushSubscription
from app.owner import Owner, get_owner

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
    if not isinstance(endpoint, str) or not endpoint.startswith("https://") or len(endpoint) > 1000:
        return JSONResponse(status_code=422, content={"error": "invalid_subscription"})
    if not isinstance(keys.get("p256dh"), str) or not isinstance(keys.get("auth"), str):
        return JSONResponse(status_code=422, content={"error": "invalid_subscription"})
    sub = (await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))).scalars().first()
    if not sub:
        sub = PushSubscription(endpoint=endpoint)
        db.add(sub)
    # Тот же браузер мог войти в аккаунт после песочницы — подписка переезжает к новому владельцу
    sub.account_id = owner.account.id if owner.account else None
    sub.sandbox_id = None if owner.account else owner.sandbox_id
    sub.p256dh = keys["p256dh"][:200]
    sub.auth = keys["auth"][:100]
    sub.timezone = str(tz)[:64]
    await db.commit()
    return Response(status_code=204)


@router.post("/unsubscribe", status_code=204)
async def unsubscribe(body: dict = Body(...), db: AsyncSession = Depends(get_db)):
    endpoint = body.get("endpoint")
    if isinstance(endpoint, str):
        await db.execute(delete(PushSubscription).where(PushSubscription.endpoint == endpoint))
        await db.commit()
    return Response(status_code=204)
