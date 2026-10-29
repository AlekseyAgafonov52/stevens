"""Public chat request plus a lightweight internal dialogue input."""
from typing import Literal, Optional

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, Field, field_validator


class Action(BaseModel):
    id: str
    record_id: Optional[int] = None
    index: Optional[int] = None      # edit_draft: какой черновик в ответе (по порядку карточек без id)
    values: Optional[dict] = None    # edit_draft: поля из формы правки


class ChatRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=128)
    text: str = Field(default="", max_length=300)
    source: Literal["voice", "text", "button"] = "text"
    action: Optional[Action] = None
    client_time: Optional[str] = None
    timezone: Optional[str] = None
    raw_text: Optional[str] = Field(default=None, max_length=600)  # голос до поправок ослышки — только для журнала


class ChatPayload(ChatRequest):
    """Public request; internal dialogue helpers may use ChatRequest defaults."""
    text: str = Field(max_length=300)
    source: Literal["voice", "text", "button"] = Field(...)
    client_time: str = Field(...)
    timezone: str = Field(...)

    @field_validator("conversation_id")
    @classmethod
    def valid_conversation(cls, value: str) -> str:
        UUID(value)
        return value

    @field_validator("client_time")
    @classmethod
    def valid_client_time(cls, value: str) -> str:
        if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Timezone offset required")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Invalid timezone") from error
        return value
