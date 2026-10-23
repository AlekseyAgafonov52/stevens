"""Поиск с падежами и правка по контексту диалога: python tests/test_context_api.py"""
import asyncio, os, sys, uuid
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app.main import app

CLOCK = "2026-10-21T10:00:00+03:00"
# фраза → kind, текст первой записи (None — не проверяем), дата, время
DIALOG = [
    ("Найди встречи с Ваней", "found", "Встреча с Иваном по бюджету", None, None),
    ("Когда у меня была встреча с Иваном?", "found", "Встреча с Иваном по презентации", "2026-03-05", "15:45"),
    ("когда я последний раз звонил Ивану", "found", "Позвонить Иваном", "2026-06-27", "10:30"),
    ("найди созвон с Петром", "found", None, None, None),
    ("Запиши встречу с Ваней завтра в 15:00", "created", "Встреча с Ваней", "2026-10-22", "15:00"),
    # День без времени — то же время; время без дня — тот же день
    ("перенеси её на пятницу", "updated", "Встреча с Ваней", "2026-10-23", "15:00"),
    ("перенеси её на 14", "updated", "Встреча с Ваней", "2026-10-23", "14:00"),
    ("перенеси её на 15:00", "updated", "Встреча с Ваней", "2026-10-23", "15:00"),
    ("сдвинь на час позже", "updated", "Встреча с Ваней", "2026-10-23", "16:00"),
    ("Напомни завтра в 10 позвонить маме", "created", "Позвонить маме", "2026-10-22", "10:00"),
    ("отметь её выполненной", "completed", "Позвонить маме", None, None),
    ("удали её", "deleted", "Позвонить маме", None, None),
    ("Запиши купить хлеб", "created", "Купить хлеб", None, None),
    ("перенеси это", "clarify", "Купить хлеб", None, None),
    ("на завтра", "updated", "Купить хлеб", "2026-10-22", None),
    ("что у меня с Ваней?", "person", "Встреча с Ваней", "2026-10-23", "16:00"),
    ("перенеси её на субботу", "updated", "Встреча с Ваней", "2026-10-24", "16:00"),
    ("перенеси её", "clarify", "Встреча с Ваней", "2026-10-24", "16:00"),
    ("на вторник через неделю", "updated", "Встреча с Ваней", "2026-11-03", "16:00"),
    ("перенеси её на 12:00", "updated", "Встреча с Ваней", "2026-11-03", "12:00"),
    ("что у меня с Машей на этой неделе", "person", "Встреча с Марией по презентации", "2026-10-21", "08:00"),
    ("досье на Аркадия", "person", None, None, None),
    ("Найди встречу с Марией по сайту", "found", "Встреча с Марией по сайту", "2027-03-08", "17:00"),
    ("перенеси её на завтра в 18", "updated", "Встреча с Марией по сайту", "2026-10-22", "18:00"),
    # Ослышка после отправки: «исправь и вам на Иваном», «не …, а …»
    ("Запиши встречу с и вам завтра в 12", "created", "Встреча с и вам", "2026-10-22", "12:00"),
    ("исправь и вам на Иваном", "updated", "Встреча с Иваном", "2026-10-22", "12:00"),
    ("Напомни купить хлеб", "clarify", None, None, None),
    ("Стив, не хлеб, а молоко", "clarify", None, None, None),
    ("завтра в 9", "created", "Купить молоко", "2026-10-22", "09:00"),
    ("не молоко, а кефир", "updated", "Купить кефир", "2026-10-22", "09:00"),
    ("исправь вертолёт на самолёт", "not_understood", None, None, None),
]


async def main():
    fails = 0
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            h = {"X-Client-Id": "ctx-" + uuid.uuid4().hex[:12], "X-Stevens-Features": "d2,d3,d10"}
            await c.post("/api/sandbox/reset", headers=h)
            conv = str(uuid.uuid4())
            for phrase, kind, text, day, time in DIALOG:
                body = {"conversation_id": conv, "text": phrase, "source": "text", "client_time": CLOCK,
                        "timezone": "Europe/Moscow"}
                r = (await c.post("/api/chat", json=body, headers=h)).json()
                first = r["records"][0] if r["records"] else {}
                got = (r["kind"], first.get("text"), first.get("date"), first.get("time"))
                want = (kind, text, day, time)
                ok = all(w is None or g == w for g, w in zip(got, want)) and (text is not None or not r["records"])
                if not ok:
                    fails += 1
                    print(f"«{phrase}» → {r['text']!r} {got}, ждали {want}")
    print("fails:", fails)
    sys.exit(1 if fails else 0)

asyncio.run(main())
