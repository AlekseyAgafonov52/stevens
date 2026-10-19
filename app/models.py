import enum
from datetime import datetime as dt

from sqlalchemy import DateTime, Enum, String, Text, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True) # Пока разрешаем null для старых записей
    user: Mapped["User"] = relationship(back_populates="tasks")

    def __repr__(self) -> str:
        return f"<Task id={self.id} text={self.text!r} type={self.type}>"

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[dt] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tasks: Mapped[list["Task"]] = relationship(back_populates="user")

class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[dt] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt | None] = mapped_column(DateTime(timezone=True), nullable=True)