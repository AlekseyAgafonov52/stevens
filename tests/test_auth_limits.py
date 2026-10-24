"""Пароли Argon2/старый bcrypt и ограничения запросов без внешних служб."""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.getcwd())
import httpx
from sqlalchemy import select
from starlette.responses import Response
from app.database import AsyncSessionLocal
from app.logic.request_limits import RequestLimits
from app.main import app
from app.models import Account
from app.security import hash_password, pwd_context, verify_password
from app import push


async def paused():
    await asyncio.Event().wait()


async def main():
    fails = []
    def check(name, ok):
        print("OK  " if ok else "FAIL", name)
        if not ok:
            fails.append(name)
    for prefix in ("a" * 72, "я" * 36):
        hashed = hash_password(prefix + "first")
        check("Argon2 проверяет окончание пароля", hashed.startswith("$argon2id$")
              and verify_password(prefix + "first", hashed) and not verify_password(prefix + "other", hashed))
        legacy = pwd_context.hash(prefix + "first", scheme="bcrypt")
        check("длинный старый bcrypt отклоняется", not verify_password(prefix + "first", legacy)
              and not verify_password(prefix + "other", legacy) and not verify_password(prefix, legacy))
    push.loop = paused
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            login = "old" + uuid.uuid4().hex[:12]
            async with AsyncSessionLocal() as db:
                db.add(Account(login=login, login_lower=login, password_hash=pwd_context.hash("old-password", scheme="bcrypt")))
                await db.commit()
            r = await c.post("/api/auth/login", json={"login": login, "password": "old-password"})
            async with AsyncSessionLocal() as db:
                row = (await db.execute(select(Account).where(Account.login_lower == login))).scalar_one()
                check("короткий bcrypt обновляется при входе", r.status_code == 200 and row.password_hash.startswith("$argon2id$"))
            login = "new" + uuid.uuid4().hex[:12]
            r = await c.post("/api/auth/register", json={"login": login, "password": "я" * 128})
            r2 = await c.post("/api/auth/login", json={"login": login, "password": "я" * 127 + "б"})
            check("128 символов сохраняются целиком", r.status_code == 200 and r2.status_code == 401)
    async def dummy(scope, receive, send):
        await Response(status_code=204)(scope, receive, send)
    limiter = RequestLimits(dummy)
    previous = os.environ.get("STEVENS_RATE_LIMIT")
    os.environ["STEVENS_RATE_LIMIT"] = "1"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=limiter, client=("203.0.113.1", 1)), base_url="http://t") as c:
            codes = [(await c.post("/api/auth/login", json={})).status_code for _ in range(30)]
            denied = await c.post("/api/auth/login", json={}, headers={"X-Forwarded-For": "198.51.100.1"})
            check("429 и Retry-After, spoofed IP не помогает", codes == [204] * 30 and denied.status_code == 429
                  and int(denied.headers["Retry-After"]) >= 1)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=limiter, client=("203.0.113.2", 1)), base_url="http://t") as c:
            check("другой IP не заблокирован", (await c.post("/api/auth/login", json={})).status_code == 204)
            check("большое тело auth не читается обработчиком", (await c.post("/api/auth/login", content=b"x" * 5000)).status_code == 422)
            chunks = []
            async def audio():
                for i in range(8):
                    chunks.append(i)
                    yield b"x" * (512 * 1024)
            r = await c.post("/api/stt", content=audio(), headers={"Content-Type": "audio/ogg"})
            check("аудио ограничено во время чтения потока", r.status_code == 413 and len(chunks) == 3)
        for i in range(11000):
            limiter.hit(("bounded", i), 1)
        check("память лимитера ограничена", len(limiter.windows) <= 10000)
    finally:
        if previous is None:
            os.environ.pop("STEVENS_RATE_LIMIT", None)
        else:
            os.environ["STEVENS_RATE_LIMIT"] = previous
    print("fails:", len(fails))
    return bool(fails)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
