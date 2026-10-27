"""Импорт из другого календаря: файл .ics и JSON без id только добавляют записи. Только на отдельной тестовой БД."""
import asyncio
from datetime import date, timedelta
import os
import sys
import uuid

sys.path.insert(0, os.getcwd())
import httpx
from sqlalchemy import select

from app import push
from app.database import AsyncSessionLocal
from app.logic import calendar_import
from app.main import app
from app.models import Series


async def paused():
    await asyncio.Event().wait()


def ics(today: date) -> str:
    def d(n: int) -> str:
        return (today + timedelta(days=n)).strftime("%Y%m%d")
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Google Inc//Google Calendar 70.9054//EN",
        "BEGIN:VTIMEZONE", "TZID:Europe/Moscow", "END:VTIMEZONE",
        # обычная встреча в UTC: 07:00Z = 10:00 по Москве, с напоминанием за 30 минут
        "BEGIN:VEVENT", "UID:a1", f"DTSTART:{d(2)}T070000Z", f"DTEND:{d(2)}T080000Z",
        "SUMMARY:Созвон с Петей\\, по дизайну", "BEGIN:VALARM", "TRIGGER:-PT30M", "ACTION:DISPLAY", "END:VALARM",
        "END:VEVENT",
        # на весь день → задача
        "BEGIN:VEVENT", "UID:a2", f"DTSTART;VALUE=DATE:{d(3)}", f"DTEND;VALUE=DATE:{d(4)}",
        "SUMMARY:Сдать отчёт по прак", " тике", "END:VEVENT",
        # по будням с поясом, с пропущенным днём и перенесённым днём
        "BEGIN:VEVENT", "UID:a3", f"DTSTART;TZID=Europe/Moscow:{monday.strftime('%Y%m%d')}T090000",
        f"DTEND;TZID=Europe/Moscow:{monday.strftime('%Y%m%d')}T180000",
        "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", f"EXDATE;TZID=Europe/Moscow:{(monday + timedelta(days=1)).strftime('%Y%m%d')}T090000",
        "SUMMARY:Работа", "END:VEVENT",
        "BEGIN:VEVENT", "UID:a3", f"RECURRENCE-ID;TZID=Europe/Moscow:{(monday + timedelta(days=2)).strftime('%Y%m%d')}T090000",
        f"DTSTART;TZID=Europe/Moscow:{(monday + timedelta(days=2)).strftime('%Y%m%d')}T120000",
        f"DTEND;TZID=Europe/Moscow:{(monday + timedelta(days=2)).strftime('%Y%m%d')}T180000",
        "SUMMARY:Работа (с обеда)", "END:VEVENT",
        # день рождения раз в год → одна задача на год вперёд
        "BEGIN:VEVENT", "UID:a4", f"DTSTART;VALUE=DATE:{(today - timedelta(days=300)).strftime('%Y%m%d')}",
        "RRULE:FREQ=YEARLY", "SUMMARY:ДР мамы", "END:VEVENT",
        # прошедшее и отменённое — пропускаем
        "BEGIN:VEVENT", "UID:a5", f"DTSTART:{d(-5)}T100000Z", "SUMMARY:Было давно", "END:VEVENT",
        "BEGIN:VEVENT", "UID:a6", f"DTSTART:{d(5)}T100000Z", "STATUS:CANCELLED", "SUMMARY:Отменили", "END:VEVENT",
        # дело без срока
        "BEGIN:VTODO", "UID:a7", "SUMMARY:Купить лампочку", "END:VTODO",
        "END:VCALENDAR", ""])


async def main():
    push.loop = paused
    failures = []

    def check(name, ok, extra=""):
        print("OK  " if ok else "FAIL", name, "" if ok else extra)
        if not ok:
            failures.append(name)

    today = date.today()
    items, skipped = calendar_import.convert(ics(today), today, calendar_import.zone("Europe/Moscow"))
    by_text = {i["text"]: i for i in items}
    meet = by_text.get("Созвон с Петей, по дизайну", {})
    check("UTC → Москва, конец и напоминание", meet.get("time") == "10:00" and meet.get("end_time") == "11:00"
          and meet.get("remind_before") == 30 and meet.get("type") == "meeting", meet)
    check("весь день → задача, перенос строки склеен",
          by_text.get("Сдать отчёт по практике", {}).get("type") == "task"
          and by_text["Сдать отчёт по практике"]["time"] is None, items)
    work = by_text.get("Работа", {})
    check("по будням → повтор", work.get("repeat") == {"weekdays": [0, 1, 2, 3, 4], "until": None}
          and work.get("time") == "09:00" and len(work.get("_except", [])) == 2, work)
    check("перенесённый день — отдельно", by_text.get("Работа (с обеда)", {}).get("time") == "12:00")
    check("раз в год → год назад и год вперёд", sum(1 for i in items if i["text"] == "ДР мамы") == 2)
    check("отменённое пропущено, прошедшее оставлено", skipped == 1 and "Было давно" in by_text and "Отменили" not in by_text)
    check("дело без срока", by_text.get("Купить лампочку", {}).get("date") is None)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            reg = (await c.post("/api/auth/register", json={"login": "ics" + uuid.uuid4().hex[:10],
                                                             "password": "test-password"})).json()
            h = {"Authorization": "Bearer " + reg["token"]}

            async def export():
                return (await c.get("/api/records/export", headers=h)).json()["records"]

            mine = {"type": "task", "text": "Моё старое дело", "date": None}
            first = await c.post("/api/records/import/apply", headers=h, json={"records": [mine]})
            check("JSON без id добавляет", first.status_code == 200 and first.json()["add"] == 1, first.text)
            body = {"ics": ics(today), "timezone": "Europe/Moscow"}
            preview = (await c.post("/api/records/import/preview", headers=h, json=body)).json()
            check("предпросмотр .ics", preview.get("add") == 8 and preview.get("delete") == 0
                  and preview.get("skipped") == 1 and preview.get("past") == 2 and not preview.get("errors"), preview)
            detailed = (await c.post("/api/records/import/preview", headers=h, json={**body, "details": True})).json()
            check("подробности для окна", detailed.get("kinds") == {"repeat": 1, "meeting": 3, "task": 4}
                  and len(detailed.get("items", [])) == 8, detailed)
            done = await c.post("/api/records/import/apply", headers=h, json=body)
            rows = await export()
            check("применили .ics, старое на месте", done.status_code == 200 and done.json()["add"] == 8
                  and any(r["text"] == "Моё старое дело" for r in rows), done.text)
            old = [r for r in rows if r["text"] in ("Было давно", "ДР мамы") and r["date"] < today.isoformat()]
            check("прошедшее — выполненным", len(old) == 2 and all(r["status"] == "done" for r in old), old)
            work_days = [r for r in rows if r["text"] == "Работа"]
            check("повтор создан на год вперёд", len(work_days) > 200 and all(r["repeat"] for r in work_days))
            again = (await c.post("/api/records/import/preview", headers=h, json=body)).json()
            check("второй раз — «уже есть», без дублей", again.get("add") == 0 and again.get("same") == 8, again)
            ai = await c.post("/api/records/import/preview", headers=h, json={"records": [
                {"type": "busy", "text": "Пары", "date": (today + timedelta(days=1)).isoformat(), "time": "10:00",
                 "end_time": "13:20", "repeat": {"weekdays": [1, 3], "until": None}}]})
            check("JSON из ИИ с повтором", ai.json().get("add") == 1 and ai.json().get("delete") == 0, ai.text)
            undone = await c.post("/api/records/import/undo", headers=h, json={"undo_id": done.json()["undo_id"]})
            rows = await export()
            async with AsyncSessionLocal() as db:
                ended = (await db.execute(select(Series).where(Series.account_id == reg["user"]["id"]))).scalars().all()
            check("отмена убирает всё из файла и останавливает повтор", undone.status_code == 200
                  and [r["text"] for r in rows] == ["Моё старое дело"] and ended and all(s.ended for s in ended),
                  undone.text)
            bad = await c.post("/api/records/import/preview", headers=h, json={"ics": "просто текст"})
            check("не .ics — понятная ошибка", bad.status_code == 422 and bad.json().get("error") == "bad_ics")

    print("\nFAILED:" if failures else "\nALL OK", ", ".join(failures))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
