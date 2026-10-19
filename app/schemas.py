from datetime import datetime as dt
from typing import Optional, Literal, Union
from pydantic import BaseModel, ConfigDict, Field

from app.models import TaskStatus, TaskType, DateKind

# --- Внутренние схемы (для эндпоинта /tasks) ---
class TaskCreate(BaseModel):
    type: TaskType = TaskType.task
    text: str = Field(..., min_length=1, max_length=255)
    date: Optional[str] = None
    time: Optional[str] = None
    date_kind: DateKind = DateKind.none

class TaskUpdate(BaseModel):
    text: Optional[str] = Field(None, min_length=1, max_length=255)
    date: Optional[str] = None
    time: Optional[str] = None
    date_kind: Optional[DateKind] = None
    status: Optional[TaskStatus] = None

class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    type: TaskType
    text: str
    date: Optional[str]
    time: Optional[str]
    date_kind: DateKind
    status: TaskStatus
    created_at: dt

# ==========================================
# СХЕМЫ ДЛЯ КОНТРАКТА /api/chat (Раздел 4, 5, 6)
# ==========================================

class Action(BaseModel):
    id: str
    record_id: Optional[int] = None

class ButtonSend(BaseModel):
    text: Optional[str] = None
    action: Optional[Action] = None

class Button(BaseModel):
    label: str
    send: ButtonSend
    style: Literal["primary", "secondary"] = "primary"

class Record(BaseModel):
    id: Optional[int] = None
    type: Optional[str] = None      
    text: str
    date: Optional[str] = None
    time: Optional[str] = None
    date_kind: str = "none"         
    status: Optional[str] = None    
    created_at: Optional[dt] = None
    marks: list[str] = []
    highlight: Optional[str] = None

class ChatRequest(BaseModel):
    conversation_id: str
    text: str = Field(..., max_length=300)
    source: Literal["voice", "text", "button"]
    action: Optional[Action] = None
    client_time: str
    timezone: str

class ChatResponse(BaseModel):
    message_id: str
    kind: str # created, list, found, clarify, confirm, conflict, cancelled, not_understood, off_topic, help, thanks, error
    text: str
    speech: Optional[str] = None
    records: list[Record] = []
    nearest: Optional[Record] = None
    total: Optional[int] = None
    awaiting_reply: bool = False
    buttons: list[Button] = []