"""Снимки для отмены атомарного импорта: только данные владельца операции."""
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ImportOperation(Base):
    __tablename__ = "import_operations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_key: Mapped[str] = mapped_column(String(80), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    snapshot: Mapped[str] = mapped_column(Text)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
