"""Создание записи из календаря: POST /api/records — python tests/test_calendar_create_api.py"""
import asyncio, os, sys, uuid
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app.main import app

CASES = [
    ({"type": "task", "text": " Купить молоко ", "date": "2026-11-03", "time": None}, 201,
     lambda r: r["type"] == "task" and r["text"] == "Купить молоко" and r["date_kind"] == "exact" and r["status"] == "open"),
    ({"type": "reminder", "text": "Позвонить маме", "date": "2026-11-03", "time": "10:30"}, 201,
     lambda r: r["time"] == "10:30" and r["status"] == "open"),
    ({"type": "meeting", "text": "Встреча с Иваном", "date": "2026-11-03", "time": "15:00", "remind_before": 30}, 201,
     lambda r: r["status"] is None and r["remind_before"] == 30),
    ({"type": "busy", "text": "Пары", "date": "2026-11-03", "time": "09:00", "end_time": "12:00"}, 201,
     lambda r: r["end_time"] == "12:00"),
    ({"type": "meeting", "text": "Без времени", "date": "2026-11-03", "time": None}, 422, None),
    ({"type": "busy", "text": "Без конца", "date": "2026-11-03", "time": "09:00"}, 422, None),
    ({"type": "task", "text": "  ", "date": "2026-11-03", "time": None}, 422, None),
    ({"type": "note", "text": "Заметка"}, 422, None),
    ({"type": "task", "text": "x", "date": "2026-11-03", "extra": 1}, 422, None),
]


async def main():
    failed = 0
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            h = {"X-Client-Id": str(uuid.uuid4())}
            for body, code, check in CASES:
                r = await c.post("/api/records", json=body, headers=h)
                ok = r.status_code == code and (check is None or check(r.json()["record"]))
                failed += not ok
                print("OK " if ok else "FAIL", body["text"], r.status_code, r.text[:160])
            r = await c.get("/api/records?from=2026-11-03&to=2026-11-03", headers=h)
            new = [x for x in r.json()["records"] if x["date"] == "2026-11-03" and not x["demo"]]
            ok = len(new) == 4
            failed += not ok
            print("OK " if ok else "FAIL", "в календаре", len(new))
    print("FAILED", failed) if failed else print("ALL OK")
    sys.exit(1 if failed else 0)

asyncio.run(main())
