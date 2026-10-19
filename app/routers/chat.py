from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from app.database import get_db
from app.schemas import ChatRequest, ChatResponse, Record, Button, ButtonSend
from app.models import TaskType, DateKind, TaskStatus

router = APIRouter(prefix="/api", tags=["chat"])

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    Заглушка для общения с ассистентом Стивенсом.
    Пока просто возвращает список задач из БД (если спросили "что у меня сегодня").
    """
    
    # Простейшая логика на завтрак: если в тексте есть "сегодня", покажем фейковый список
    if "сегодня" in payload.text.lower():
        return ChatResponse(
            message_id=f"m-{uuid4().hex[:6]}",
            kind="list",
            text="Сегодня планов нет. Ближайшее — завтра в 10:00: «Позвонить Ивану».",
            speech="На сегодня планов нет.",
            records=[],
            nearest=Record(
                id=1001, 
                type=TaskType.reminder,    
                text="Позвонить Ивану", 
                date="2026-10-20", 
                time="10:00", 
                date_kind=DateKind.exact,   
                status=TaskStatus.open      
            ),
            total=0,
            awaiting_reply=False,
            buttons=[]
        )

    # Для всех остальных запросов — просим уточнить
    return ChatResponse(
        message_id=f"m-{uuid4().hex[:6]}",
        kind="clarify",
        text="Во сколько встреча?",
        speech=None,
        records=[],
        awaiting_reply=True,
        buttons=[
            Button(label="10:00", send=ButtonSend(text="в 10:00")), # <-- Создаем объект ButtonSend
            Button(label="15:00", send=ButtonSend(text="в 15:00")),
            Button(
                label="Отменить", 
                send=ButtonSend(action={"id": "cancel"}), # type: ignore
                style="secondary"
            )
        ]
    )