"""Stevens API по контракту v1.4 с допами (d2, d3, d10)."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import models  # noqa: F401 — таблицы для create_all
from app.database import Base, engine, get_db
from app.owner import CLIENT_ID_RE, ensure_sandbox, seed_sandbox
from app import push
from app.routers import auth, chat, records
from app.routers import push as push_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:  # type: ignore
        await conn.run_sync(Base.metadata.create_all)
    print("✅ База данных готова.")
    pusher = asyncio.create_task(push.loop())
    yield
    pusher.cancel()
    await engine.dispose()


app = FastAPI(title="Stevens API", version="1.4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
app.include_router(records.router)
app.include_router(push_router.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


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


@app.get("/")
async def root():
    return {"message": "Stevens API is running"}
