import enum
from datetime import datetime as dt

from sqlalchemy import DateTime, Enum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TaskType(str, enum.Enum):
    task = "task"
    meeting = "meeting"
    reminder = "reminder"


class TaskStatus(str, enum.Enum):
    open = "open" 
    done = "done"


class DateKind(str, enum.Enum):
    exact = "exact"      # В этот момент
    deadline = "deadline" # До этой даты
    none = "none"        # Без срока


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[TaskType] = mapped_column(
        Enum(TaskType, name="task_type"), default=TaskType.task, nullable=False
    )
    text: Mapped[str] = mapped_column(String(255), nullable=False) # <-- Было title, стало text
    date: Mapped[str | None] = mapped_column(String(10), nullable=True) # "YYYY-MM-DD"
    time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "HH:MM"
    date_kind: Mapped[DateKind] = mapped_column(
        Enum(DateKind, name="date_kind"), default=DateKind.none, nullable=False
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"), default=TaskStatus.open, nullable=False
    )
    created_at: Mapped[dt] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Task id={self.id} text={self.text!r} type={self.type}>"