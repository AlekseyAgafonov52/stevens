from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base
# Импортируем роутер задач
from app.routers import tasks, chat, auth 
# Импортируем модели, чтобы SQLAlchemy знала о них при создании таблиц
from app import models  # noqa: F401 

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управляет жизненным циклом приложения.
    Всё, что до yield — выполняется при запуске.
    Всё, что после — при остановке.
    """
   # Создаём таблицы в БД (если их нет)
    async with engine.begin() as conn:  # type: ignore
        await conn.run_sync(Base.metadata.create_all)
    
    print("✅ База данных готова, таблицы созданы.")
    yield
    # Корректно закрываем пул соединений при выключении
    await engine.dispose()
    print("🛑 Соединение с базой закрыто.")

# Создаём экземпляр приложения
app = FastAPI(
    title="Voice Assistant API", 
    version="1.0.0",
    lifespan=lifespan
)

# Настраиваем CORS (чтобы позже фронтенд мог делать запросы)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем наши роуты
app.include_router(tasks.router)
app.include_router(chat.router)  
app.include_router(auth.router)

@app.get("/")
async def root():
    return {"message": "Voice Assistant API is running!"}

@app.get("/api/health")
async def health():
    return {"status": "ok"}