import os
from typing import AsyncGenerator  

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

load_dotenv()  # Явно заданное окружение сервера важнее локального .env.
DATABASE_URL = os.getenv("DATABASE_URL")

# Проверка, что URL вообще задан
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in .env file")

# Теперь Pylance точно знает, что здесь строка (str)
# pre_ping: после перезапуска PostgreSQL старые соединения не дают ошибку на первом запросе
engine = create_async_engine(DATABASE_URL, echo=os.getenv("SQL_ECHO") == "1", pool_pre_ping=True,
                             pool_size=10, max_overflow=20)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""
    pass


# Меняем тип возвращаемого значения на AsyncGenerator
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency для FastAPI: отдаёт сессию и гарантирует её закрытие."""
    async with AsyncSessionLocal() as session:
        yield session
