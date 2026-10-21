from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from uuid import uuid4
from datetime import datetime, timedelta
import dateparser
from app.deps import get_current_user
from app.models import User

from app.database import get_db
from app.models import Task, TaskType, DateKind, TaskStatus
from app.schemas import (
    ChatRequest, ChatResponse, Record, Button, ButtonSend, Action
)
from app.templates import get_template
from brain import parse_user_input

router = APIRouter(prefix="/api", tags=["chat"])


def format_date_for_user(date_str: str | None, time_str: str | None) -> str:
    """Вспомогательная функция для красивого вывода даты в ответе."""
    if not date_str: return "без срока"
    when = date_str
    if time_str:
        when += f" в {time_str}"
    return when


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    payload: ChatRequest, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user) # <-- ТРЕБУЕМ АВТОРИЗАЦИЮ
):
    
    # 1. Получаем разбор от нейросети
    intent = parse_user_input(payload.text)
    
    if not intent or intent.intent == "unknown":
        return ChatResponse(
            message_id=f"m-{uuid4().hex[:6]}",
            kind="not_understood",
            text=get_template("not_understood"),
            awaiting_reply=False,
            buttons=[
                Button(label="Напомни завтра в 10 позвонить", send=ButtonSend(text="Напомни завтра в 10 позвонить")),
                Button(label="Что у меня сегодня?", send=ButtonSend(text="Что у меня сегодня?"))
            ]
        )

    # 2. Обработка НЕ-создания (help, thanks, off_topic)
    if intent.intent in ["help", "thanks", "off_topic"]:
        return ChatResponse(
            message_id=f"m-{uuid4().hex[:6]}",
            kind=intent.intent,
            text=get_template(intent.intent),
            awaiting_reply=False
        )

    # 3. Обработка ПОИСКА (search)
    if intent.intent == "search":
        # Ищем только задачи текущего пользователя
        stmt = select(Task).where(Task.user_id == current_user.id)
        
        if intent.keyword:
            stmt = stmt.where(Task.text.ilike(f"%{intent.keyword}%"))
            
        # Сортируем по дате (сначала ближайшие)
        stmt = stmt.order_by(Task.date.desc()).limit(5)
        
        result = await db.execute(stmt)
        tasks = result.scalars().all()
        
        if not tasks:
            return ChatResponse(
                message_id=f"m-{uuid4().hex[:6]}", kind="found", 
                text=get_template("found_none")
            )
            
        records = [
            Record(
                id=t.id, type=t.type, text=t.text, date=t.date, time=t.time,
                date_kind=t.date_kind, status=t.status, highlight="date"
            ) for t in tasks
        ]
        return ChatResponse(
            message_id=f"m-{uuid4().hex[:6]}", kind="found",
            text=get_template("found_some", count=len(records)),
            total=len(records), records=records
        )

    # 4. Обработка СПИСКА (list)
    if intent.intent == "list":
        base_dt = datetime.fromisoformat(payload.client_time)
        target_date = base_dt.strftime("%Y-%m-%d")
        
        # Логика периодов
        if intent.period == "tomorrow":
            target_date = (base_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        elif intent.period == "this_week":
            target_date = base_dt.strftime("%Y-%m-%d")
        elif intent.period and intent.period.startswith("2026-"): 
            target_date = intent.period

        # Ищем в БД (только для текущего пользователя + ilike для надежности)
        stmt = select(Task).where(
            Task.user_id == current_user.id,
            Task.date.ilike(f"{target_date}%") # Ищем по началу даты
        ).order_by(Task.time)
        
        if intent.filter_type:
            stmt = stmt.where(Task.type == intent.filter_type)
            
        result = await db.execute(stmt)
        tasks = result.scalars().all()
        
        if not tasks:
            period_key = intent.period or ""
            period_ru = {
                "today": "сегодня",
                "tomorrow": "завтра",
                "this_week": "на этой неделе",
                "next_week": "на следующей неделе"
            }.get(period_key, intent.period or "этот период")
            
            return ChatResponse(
                message_id=f"m-{uuid4().hex[:6]}", kind="list",
                text=get_template("list_empty_none", period=period_ru)
            )
            
        records = [
            Record(
                id=t.id, type=t.type, text=t.text, date=t.date, time=t.time,
                date_kind=t.date_kind, status=t.status
            ) for t in tasks
        ]
        
        # Переводим период для красивого ответа
        # Используем `or ""`, чтобы Pylance видел строку, а не None
        period_key = intent.period or "" 
        
        period_ru = {
            "today": "сегодня",
            "tomorrow": "завтра",
            "this_week": "на этой неделе",
            "next_week": "на следующей неделе"
        }.get(period_key, intent.period or "этот период")
        
        return ChatResponse(
            message_id=f"m-{uuid4().hex[:6]}", kind="list",
            text=get_template("list_some", period=period_ru, count=len(records)),
            total=len(records), records=records
        )

    # 5. Обработка СОЗДАНИЯ (create_task, create_meeting, create_reminder)
    if intent.intent.startswith("create_"):
        
        # А) Валидация (не хватает данных)
        if "time" in intent.missing and intent.intent == "create_meeting":
            return ChatResponse(
                message_id=f"m-{uuid4().hex[:6]}", kind="clarify",
                text=get_template("clarify_meeting_time"), awaiting_reply=True,
                buttons=[
                    Button(label="10:00", send=ButtonSend(text="в 10:00")),
                    Button(label="15:00", send=ButtonSend(text="в 15:00")),
                    Button(label="Отменить", send=ButtonSend(action=Action(id="cancel")), style="secondary")
                ]
            )
        if "date" in intent.missing and intent.intent == "create_reminder":
            return ChatResponse(
                message_id=f"m-{uuid4().hex[:6]}", kind="clarify",
                text=get_template("clarify_reminder_when"), awaiting_reply=True
            )

        # Б) Вычисление даты
        date_str = None
        base_dt = datetime.fromisoformat(payload.client_time)
        
        if intent.date:
            # Обработка "end_of_week" (до воскресенья)
            if intent.date == "end_of_week":
                days_ahead = 6 - base_dt.weekday()
                if days_ahead <= 0: days_ahead += 7
                date_str = (base_dt + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
            
            # Обработка "today" (если dateparser тупит)
            elif intent.date.lower() == "today":
                date_str = base_dt.strftime("%Y-%m-%d")
                
            # Обработка "tomorrow"
            elif intent.date.lower() == "tomorrow":
                date_str = (base_dt + timedelta(days=1)).strftime("%Y-%m-%d")
                
            # Для всех остальных ("пятница", "2026-10-23")
            else:
                parsed_dt = dateparser.parse(
                    intent.date, languages=['ru'], 
                    settings={'RELATIVE_BASE': base_dt}
                )
                if parsed_dt:
                    date_str = parsed_dt.strftime("%Y-%m-%d")
                else:
                    # Если dateparser не справился, ставим дату клиента
                    date_str = base_dt.strftime("%Y-%m-%d")

        # В) Определение типа
        type_map = {
            "create_task": TaskType.task,
            "create_meeting": TaskType.meeting,
            "create_reminder": TaskType.reminder
        }
        task_type = type_map[intent.intent]
        
        # Г) Сохранение в БД
        new_task = Task(
        type=task_type,
        text=intent.text or payload.text,
        date=date_str,
        time=intent.time,
        date_kind=DateKind(intent.date_kind),
        status=TaskStatus.open,
        user_id=current_user.id # <-- ПРИВЯЗЫВАЕМ К ЮЗЕРУ
        )
        db.add(new_task)
        await db.commit()
        await db.refresh(new_task)

        # Д) Формирование ответа по шаблону
        # Переводим токены периодов на русский
        period_map = {
            "today": "сегодня",
            "tomorrow": "завтра",
            "this_week": "на этой неделе",
            "next_week": "на следующей неделе"
        }
        
        # Форматируем дату для пользователя (без null)
        if date_str:
            # Если есть точная дата, можно вывести её красиво (пока просто YYYY-MM-DD)
            # Но так как фронт сам отрисует карточку, в тексте лучше использовать русские слова
            if intent.date in period_map:
                when_str = period_map[intent.date]
            else:
                when_str = date_str
            if intent.time:
                when_str += f" в {intent.time}"
        else:
            when_str = "без срока"

        # Выбираем правильный шаблон
        if task_type == TaskType.task and intent.date_kind == "deadline":
            template_key = "created_task_nodeadline"
            when_str = f"до {date_str}" if date_str else "без срока"
        elif not intent.time:
            template_key = "created_no_time"
        else:
            template_key = f"created_{task_type.value}"

        return ChatResponse(
            message_id=f"m-{uuid4().hex[:6]}",
            kind="created",
            text=get_template(template_key, text=new_task.text, when=when_str),
            records=[
                Record(
                    id=new_task.id, type=new_task.type, text=new_task.text,
                    date=new_task.date, time=new_task.time, 
                    date_kind=new_task.date_kind, status=new_task.status,
                    marks=["new"]
                )
            ],
            awaiting_reply=False
        )

    # 6. Fallback (если ничего не подошло)
    return ChatResponse(
        message_id=f"m-{uuid4().hex[:6]}",
        kind="error",
        text=get_template("error_backend")
    )