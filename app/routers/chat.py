from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4
from datetime import datetime
import dateparser

from app.database import get_db
from app.schemas import ChatRequest, ChatResponse, Record, Button, ButtonSend, Action
from app.models import Task, TaskType, DateKind, TaskStatus
from brain import parse_user_input

router = APIRouter(prefix="/api", tags=["chat"])

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest, db: AsyncSession = Depends(get_db)):
    
    # 1. Отправляем текст в нейросеть
    parsed_intent = parse_user_input(payload.text)
    
    if not parsed_intent:
        return ChatResponse(
            message_id=f"m-{uuid4().hex[:6]}", kind="error",
            text="Извините, у меня сбой. Попробуйте еще раз."
        )

    # 2. Обрабатываем создание задачи/встречи/напоминания
    if parsed_intent.intent in ["create_task", "create_meeting", "create_reminder"]:
        
        # Определяем тип
        task_type = TaskType.task
        if parsed_intent.intent == "create_meeting":
            task_type = TaskType.meeting
        elif parsed_intent.intent == "create_reminder":
            task_type = TaskType.reminder

        # Парсим дату (с учетом client_time)
        dt_str = payload.client_time
        date_str = None
        time_str = parsed_intent.time
        date_kind = DateKind.exact

        if parsed_intent.date:
            base_dt = datetime.fromisoformat(dt_str)
            parsed_date = dateparser.parse(
                parsed_intent.date, # <-- ИСПОЛЬЗУЕМ НОВОЕ ПОЛЕ
                languages=['ru'],
                settings={'RELATIVE_BASE': base_dt}
            )
            if parsed_date:
                date_str = parsed_date.strftime("%Y-%m-%d")
        
        # Если даты нет, но просят "до конца недели" — ставим deadline
        if "до " in payload.text.lower():
            date_kind = DateKind.deadline
        elif not date_str and not time_str:
            date_kind = DateKind.none

        # Если просят встречу без времени — уточняем
        if task_type == TaskType.meeting and not time_str:
            return ChatResponse(
                message_id=f"m-{uuid4().hex[:6]}", kind="clarify",
                text="Во сколько встреча?", awaiting_reply=True,
                buttons=[
                    Button(label="10:00", send=ButtonSend(text="в 10:00")),
                    Button(label="15:00", send=ButtonSend(text="в 15:00")),
                    Button(label="Отменить", send=ButtonSend(action=Action(id="cancel")), style="secondary")
                ]
            )

        # Сохраняем в БД
        new_task = Task(
            type=task_type,
            text=parsed_intent.text or payload.text,
            date=date_str,
            time=time_str,
            date_kind=date_kind,
            status=TaskStatus.open
        )
        db.add(new_task)
        await db.commit()
        await db.refresh(new_task)

        # Формируем ответ (пока жестко зашитый шаблон)
        when_str = f"{new_task.date} в {new_task.time}" if new_task.time else (new_task.date or "без срока")
        
        return ChatResponse(
            message_id=f"m-{uuid4().hex[:6]}",
            kind="created",
            text=f"Записал: «{new_task.text}», {when_str}.",
            records=[
                Record(
                    id=new_task.id, type=new_task.type, text=new_task.text,
                    date=new_task.date, time=new_task.time, 
                    date_kind=new_task.date_kind, status=new_task.status,
                    marks=["new"]
                )
            ],
            awaiting_reply=False,
            buttons=[]
        )

    # 3. Обработка списка (упрощенно)
    elif parsed_intent.intent == "list_events":
        return ChatResponse(
            message_id=f"m-{uuid4().hex[:6]}",
            kind="list",
            text="Сегодня планов нет. Ближайшее — завтра в 10:00: «Позвонить Ивану».",
            records=[],
            awaiting_reply=False
        )

    # 4. Неизвестный запрос
    return ChatResponse(
        message_id=f"m-{uuid4().hex[:6]}", kind="not_understood",
        text="Боюсь, не понял. Можно, например, так:",
        buttons=[
            Button(label="Напомни завтра в 10 позвонить", send=ButtonSend(text="Напомни завтра в 10 позвонить")),
            Button(label="Что у меня сегодня?", send=ButtonSend(text="Что у меня сегодня?"))
        ]
    )