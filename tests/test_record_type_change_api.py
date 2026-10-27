"""Смена типа записи с возвратом полей: PATCH /api/records/{id} {type} — python tests/test_record_type_change_api.py"""
import asyncio, os, sys, uuid
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app.main import app


async def main():
    failed = 0

    def check(name, ok, data=None):
        nonlocal failed
        failed += not ok
        print("OK " if ok else "FAIL", name, "" if ok else data)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            h = {"X-Client-Id": str(uuid.uuid4())}
            post = lambda b: c.post("/api/records", json=b, headers=h)
            patch = lambda i, b: c.patch(f"/api/records/{i}", json=b, headers=h)
            r = (await post({"type": "meeting", "text": "Созвон", "date": "2026-11-05", "time": "15:00",
                             "end_time": "16:30", "remind_before": 60})).json()["record"]
            i = r["id"]
            r = (await patch(i, {"type": "task"})).json()["record"]
            check("встреча → задача", r["type"] == "task" and r["end_time"] is None and r["remind_before"] is None
                  and r["status"] == "open" and r["time"] == "15:00" and r["stash"] == {"end_time": "16:30", "remind_before": 60}, r)
            r = (await patch(i, {"status": "done"})).json()["record"]
            r = (await patch(i, {"type": "meeting"})).json()["record"]
            check("задача → встреча: вернулись «до» и напоминание", r["type"] == "meeting" and r["end_time"] == "16:30"
                  and r["remind_before"] == 60 and r["status"] is None and r["stash"] == {"status": "done", "date_kind": "exact"}, r)
            r = (await patch(i, {"type": "task"})).json()["record"]
            check("снова задача: вернулась отметка", r["status"] == "done", r)
            r = (await patch(i, {"type": "note"})).json()["record"]
            check("задача → заметка", r["type"] == "note" and r["date"] is None and r["time"] is None, r)
            r = (await patch(i, {"type": "busy"})).json()["record"]
            check("заметка → занятость: дата, время и «до» вернулись", r["type"] == "busy" and r["date"] == "2026-11-05"
                  and r["time"] == "15:00" and r["end_time"] == "16:30", r)
            r = await patch(i, {"type": "reminder", "time": "09:00"})
            r = r.json()["record"]
            check("занятость → напоминание с новым временем", r["type"] == "reminder" and r["time"] == "09:00"
                  and r["end_time"] is None and r["status"] == "done", r)
            # Задача со сроком «до» → встреча → обратно: снова «до»
            t = (await post({"type": "task", "text": "Сдать отчёт", "date": "2026-11-06", "time": None})).json()["record"]
            await patch(t["id"], {"text": "Сдать отчёт"})
            r = await patch(t["id"], {"type": "reminder"})
            check("задача без времени → напоминание: нужно время", r.status_code == 422, r.text)
            r = await patch(t["id"], {"type": "zzz"})
            check("плохой тип", r.status_code == 422, r.text)
            # Импорт/перенос не принимает type
            from app.logic.record_validation import apply_patch
            from app.models import Record, TaskType, DateKind
            rec = Record(type=TaskType.task, text="x", date_kind=DateKind.none)
            check("apply_patch без allow_type", apply_patch(rec, {"type": "meeting"}) == "invalid_fields")
    print("FAILED", failed) if failed else print("ALL OK")
    sys.exit(1 if failed else 0)

asyncio.run(main())
