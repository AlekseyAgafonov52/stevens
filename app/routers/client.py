"""Журнал сбоев сайта (POST /api/log, Ф0). Распознавание речи — app/voice/stt.py."""
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.chatlog import enabled as log_enabled, who
from app.database import AsyncSessionLocal
from app.models import ClientLog
from app.owner import Owner, get_owner

router = APIRouter(prefix="/api", tags=["client"])


class ClientEvent(BaseModel):
    event: str = Field(min_length=1, max_length=64)
    detail: str | None = Field(default=None, max_length=2000)
    client_time: str | None = None


@router.post("/log", status_code=204)
async def client_log(body: ClientEvent, owner: Owner = Depends(get_owner)):
    """Неизвестный event не ошибка — просто пишем. Сбой журнала ответ не ломает."""
    if log_enabled():
        try:
            async with AsyncSessionLocal() as db:
                db.add(ClientLog(who=who(owner), event=body.event[:64], detail=(body.detail or "")[:2000] or None))
                await db.commit()
        except Exception as error:  # noqa: BLE001
            print(f"client log error: {error!r}")
    return Response(status_code=204)

