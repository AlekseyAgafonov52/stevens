"""Таблицы по контракту v1.4: аккаунты по логину (раздел 14), песочницы по
X-Client-Id, записи с мягким удалением (15.4).

Имена таблиц новые (accounts, records…): старые таблицы прежней версии
(users, tasks) в той же базе не мешают и не используются.
"""
import enum
from datetime import datetime as dt

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TaskType(str, enum.Enum):
    task = "task"
    meeting = "meeting"
    reminder = "reminder"
    note = "note"          # заметка: без даты и времени, вне расписания


class TaskStatus(str, enum.Enum):
    open = "open"
    done = "done"


class DateKind(str, enum.Enum):
    exact = "exact"        # в этот момент
    deadline = "deadline"  # до этой даты
    none = "none"          # без срока


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Храним как ввели, сравниваем в нижнем регистре (Р-189)
    login: Mapped[str] = mapped_column(String(32), nullable=False)
    login_lower: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[dt] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[dt] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Sandbox(Base):
    """Песочница: своя копия демо-данных на устройство (раздел 14)."""
    __tablename__ = "sandboxes"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[dt] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Record(Base):
    __tablename__ = "records"
    __table_args__ = (
        Index("ix_records_account_date", "account_id", "date"),
        Index("ix_records_sandbox_date", "sandbox_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Владелец — ровно один из двух
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    sandbox_id: Mapped[str | None] = mapped_column(ForeignKey("sandboxes.client_id"), nullable=True)

    type: Mapped[TaskType | None] = mapped_column(Enum(TaskType, name="record_type"), nullable=True)
    text: Mapped[str] = mapped_column(String(300), nullable=False)
    date: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "YYYY-MM-DD"
    time: Mapped[str | None] = mapped_column(String(5), nullable=True)   # "HH:MM"
    date_kind: Mapped[DateKind] = mapped_column(Enum(DateKind, name="record_date_kind"), nullable=False)
    status: Mapped[TaskStatus | None] = mapped_column(Enum(TaskStatus, name="record_status"), nullable=True)
    created_at: Mapped[dt | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[dt | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_contract(self, marks: list[str] | None = None, highlight: str | None = None) -> dict:
        """Record из раздела 6 контракта."""
        return {
            "id": self.id,
            "type": self.type.value if self.type else None,
            "text": self.text,
            "date": self.date,
            "time": self.time,
            "date_kind": self.date_kind.value,
            "status": self.status.value if self.status else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "marks": marks if marks is not None else (["deleted"] if self.deleted_at else []),
            "highlight": highlight,
        }


class PushSubscription(Base):
    """Подписка браузера на пуш-уведомления (Web Push). Владелец — как у записей."""
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True, index=True)
    sandbox_id: Mapped[str | None] = mapped_column(ForeignKey("sandboxes.client_id"), nullable=True, index=True)
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(String(200), nullable=False)
    auth: Mapped[str] = mapped_column(String(100), nullable=False)
    # Часовой пояс браузера: записи хранятся в местном времени
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PushSent(Base):
    """Уже отправленные пуши: запись и момент, на который она стояла."""
    __tablename__ = "push_sent"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    sent_at: Mapped[dt] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PushSnooze(Base):
    """«Через 10 минут» в пуше: когда напомнить о записи ещё раз."""
    __tablename__ = "push_snoozes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True, index=True)
    sandbox_id: Mapped[str | None] = mapped_column(ForeignKey("sandboxes.client_id"), nullable=True, index=True)
    record_id: Mapped[int] = mapped_column(nullable=False)
    at: Mapped[dt] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class AppSetting(Base):
    """Настройки сервера, которые нужно помнить между запусками (ключи VAPID)."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(4000), nullable=False)
