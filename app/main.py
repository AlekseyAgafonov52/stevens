"""Stevens API: FastAPI-приложение, таблицы, фоновые пуши и очистка песочниц."""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import models  # noqa: F401 — таблицы для create_all
from app.database import Base, engine, get_db
from app.owner import CLIENT_ID_RE, clean_loop, clear_sandbox, ensure_sandbox, seed_sandbox
from app import push
from app import features
from app.routers import auth, chat, client, imports, records
from app.routers import push as push_router
from app.logic.request_limits import RequestLimits
from app.voice.stt import router as stt_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ База данных готова.")
    pusher = asyncio.create_task(push.loop())
    cleaner = asyncio.create_task(clean_loop())
    try:
        yield
    finally:
        pusher.cancel()
        cleaner.cancel()
        await asyncio.gather(pusher, cleaner, return_exceptions=True)
        await engine.dispose()


app = FastAPI(title="Stevens API", version="1.6.0", lifespan=lifespan)
app.add_middleware(RequestLimits)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[s.strip() for s in os.getenv("STEVENS_CORS_ORIGINS", "http://localhost:8080").split(",") if s.strip()],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    # Ошибки по контракту — {"error": "<код>"}
    content = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": "invalid_request"})


app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(imports.router)
app.include_router(records.router)
app.include_router(push_router.router)
app.include_router(client.router)
app.include_router(stt_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "features": features.enabled()}


@app.post("/api/sandbox/reset", status_code=204)
async def sandbox_reset(x_client_id: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    client_id = (x_client_id or "").strip()
    if not CLIENT_ID_RE.match(client_id):
        return JSONResponse(status_code=422, content={"error": "client_id_required"})
    await ensure_sandbox(db, client_id)
    await seed_sandbox(db, client_id)
    await db.commit()
    chat.forget(f"s:{client_id}")
    return Response(status_code=204)


@app.post("/api/sandbox/clear", status_code=204)
async def sandbox_clear(x_client_id: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    client_id = (x_client_id or "").strip()
    if not CLIENT_ID_RE.fullmatch(client_id):
        return JSONResponse(status_code=422, content={"error": "client_id_required"})
    await clear_sandbox(db, client_id)
    await db.commit()
    chat.forget(f"s:{client_id}")
    return Response(status_code=204)

