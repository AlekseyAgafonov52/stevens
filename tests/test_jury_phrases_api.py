"""Фразы из ТЗ отбора и их пересказы, как их скажет жюри: python tests/test_jury_phrases_api.py

Каждая группа — отдельный разговор в чистой песочнице (1000 событий датасета). Проверяем вид ответа
и кусок текста ответа или первой записи; None — не проверяем.
"""
import asyncio, os, sys, uuid
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app.main import app

CLOCK = "2026-10-28T12:00:00+03:00"  # среда
DIALOGS = [
    # 1. Создание задачи или напоминания (ТЗ)
    [("Напомни мне завтра в 10 утра позвонить Ивану", "created", "Позвонить Ивану"),
     ("В пятницу нужно отправить отчет", "created", "Отправить отчет"),
     ("Поставь задачу купить билеты до конца недели", "created", "Купить билеты"),
     ("Напомни через два часа выпить таблетки", "created", "Выпить таблетки"),
     ("поздравить Веру с днём рождения в пятницу", "created", "с днём рождения"),
     ("Внеси на 01.11.2026 напоминание помыть мультиварку", "clarify", None)],
    # 2. Создание встречи (ТЗ) и уточнение времени
    [("В четверг в 11 у меня встреча с дизайнером", "created", "Встреча с дизайнером")],
    [("Поставь встречу с Иваном завтра", "clarify", None), ("в 12", "created", "Встреча с Иваном")],
    [("Завтра в 9 созвон с заказчиком и напомни в 18 забрать посылку", "confirm", "2 дела")],
    # 3. События за период (ТЗ) и пересказы
    [("Что у меня сегодня?", "list", None), ("Какие планы на сегодня?", "list", None),
     ("Покажи мои встречи на сегодня", "list", None), ("Есть ли у меня встречи сегодня?", "list", None),
     ("Какие задачи у меня на завтра?", "list", None), ("Что запланировано на эту неделю?", "list", "неделе"),
     ("Покажи все дела", "list", "ближайший год"), ("Покажи все мои встречи", "list", "ближайший год"),
     ("Какие у меня дела на сегодня и завтра", "list", "сегодня и завтра"),
     ("какие дела в ближайшие 10 дней", "list", "10 дней"),
     ("Покажи невыполненные задачи", "list", None), ("Какие задачи просрочены?", "list", "росрочен")],
    # 4. Поиск старых записей (ТЗ) и поиск по смыслу
    [("Найди задачу про презентацию", "found", None),
     ("Когда у меня была встреча с Иваном?", "found", "Встреча с Иваном"),
     ("Я когда-то ставил задачу по договору, найди ее", "found", None),
     ("Найди задачи про деньги", "found", None), ("Найди задачу про контракт", "found", "договор"),
     ("Найди задачу про слайды", "found", "презентац"), ("Есть что-нибудь про бюджет?", "found", None),
     ("Есть задача про CRM?", "found", "CRM"), ("Где я обсуждал бюджет?", "found", None),
     ("Найди встречи с Ваней", "found", "Иван")],
    # Уточнение не застревает: новая команда отвечается, черновик ждёт
    [("Поставь встречу с Петром завтра", "clarify", None), ("привет", "help", None),
     ("в 16", "created", "Встреча с Петром")],
    [("Напомни купить молоко", "clarify", None), ("Отметь что я купил молоко", "found", None),
     ("завтра в 9", "created", "Купить молоко")],
    # Отметка, удаление
    [("Напомни завтра в 10 позвонить Ивану", "created", None), ("Я позвонил Ивану", "completed", "Позвонить Ивану")],
]


async def main():
    fails = 0
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            for dialog in DIALOGS:
                h = {"X-Client-Id": "jury-" + uuid.uuid4().hex[:12]}
                await c.post("/api/sandbox/reset", headers=h)
                conv = str(uuid.uuid4())
                for phrase, kind, piece in dialog:
                    body = {"conversation_id": conv, "text": phrase, "source": "voice", "client_time": CLOCK,
                            "timezone": "Europe/Moscow"}
                    r = (await c.post("/api/chat", json=body, headers=h)).json()
                    first = r["records"][0]["text"] if r.get("records") else ""
                    ok = r["kind"] == kind and (piece is None or piece in r["text"] or piece in first)
                    if not ok:
                        fails += 1
                        print(f"BAD «{phrase}» → {r['kind']}: {r['text']!r} [{first}], ждали {kind} {piece!r}")
    print("fails:", fails)
    sys.exit(1 if fails else 0)

asyncio.run(main())
