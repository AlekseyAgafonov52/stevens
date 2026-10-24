"""Ошибки из журнала 23–24.10: вопрос во время уточнения и «удали их все» — python tests/test_log_fixes_api.py"""
import asyncio, os, sys, uuid
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app.main import app

CLOCK = "2026-10-24T10:38:00+03:00"  # суббота
texts = lambda r: [x["text"] for x in r["records"]]
labels = lambda r: [b["label"] for b in r["buttons"]]

# Вопросы во время уточнения: черновик бросаем, отвечаем на вопрос
STUCK = [
    ("сегодня с 10:00 до 23 у меня занятость подготовка к экзамену", "created", None),
    ("скажи занятость на сегодня", "list", lambda r: "Подготовка к экзамену" in r["text"] + " ".join(texts(r))),
    ("во сколько сегодня занят", "list", lambda r: "Подготовка к экзамену" in r["text"] + " ".join(texts(r))),
    ("какая у меня сегодня занятость", "list", lambda r: "Подготовка к экзамену" in r["text"] + " ".join(texts(r))),
    # Черновик с вопросом о времени, потом вопрос — не застреваем
    ("запиши занятость на завтра", "clarify", lambda r: r["awaiting_reply"]),
    ("скажи какая у меня сегодня занята", "list", lambda r: "Подготовка к экзамену" in r["text"] + " ".join(texts(r))),
    ("запиши занятость на завтра", "clarify", lambda r: r["awaiting_reply"]),
    ("Какие у меня сегодня дела", "list", lambda r: "Подготовка к экзамену" in r["text"] + " ".join(texts(r))),
    # А ответ на уточнение по-прежнему работает
    ("запиши занятость на завтра", "clarify", lambda r: r["awaiting_reply"]),
    ("с 12 до 14", "clarify", lambda r: r["awaiting_reply"]),
    ("уборка", "created", lambda r: r["records"][0]["end_time"] == "14:00"),
]

# «Удали их все» после списка недели — только показанное, не задачи без срока
# «Удали их все» после списка недели — только показанное, не задачи без срока
BULK = [
    ("купить хлеб", "created", None),
    ("позвонить маме", "created", None),
] + [(f"в следующий {day} в {h} встреча с Ивоном про {topic}", "created", None)
     for day in ("понедельник", "вторник", "четверг") for h, topic in ((9, "план"), (11, "отчёт"), (13, "бюджет"), (15, "найм"),
                                                                          (17, "сайт"), (19, "склад"), (20, "отпуск"))] + [
    ("в субботу в 12 встреча с Ариной", "created", None),
    ("что у меня на следующей неделе", "list", lambda r: "21" in r["text"]),
    ("удали их все", None, lambda r: "21" in r["text"] and "Купить хлеб" not in texts(r)),
    ("покажи задачи без срока", None, lambda r: "Купить хлеб" in texts(r) and "Позвонить маме" in texts(r)),
    ("что у меня на этой неделе", "list", lambda r: texts(r) == ["Встреча с Ариной"]),
    # «Удали вообще все записи за неделю» — вопрос об удалении именно этой недели
    ("в следующую среду в 9 встреча с Димой", "created", None),
    ("в следующую пятницу в 9 встреча с Петей", "created", None),
    ("удали вообще все записи за следующую неделю", "confirm", lambda r: len(r["records"]) == 2),
    ("да", "deleted", None),
    ("покажи задачи без срока", None, lambda r: "Купить хлеб" in texts(r)),
    ("что у меня на этой неделе", "list", lambda r: texts(r) == ["Встреча с Ариной"]),
]


async def run(c, h, dialog):
    fails = 0
    conv = str(uuid.uuid4())
    for phrase, kind, check in dialog:
        body = {"conversation_id": conv, "text": phrase, "source": "voice", "client_time": CLOCK,
                "timezone": "Europe/Moscow"}
        r = (await c.post("/api/chat", json=body, headers=h)).json()
        ok = (kind is None or r["kind"] == kind) and (check is None or check(r))
        print(("ok " if ok else "BAD"), f"«{phrase}» → {r['kind']} {r['text']!r} {texts(r)[:4]}")
        fails += not ok
    return fails


async def main():
    fails = 0
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            for dialog in (STUCK, BULK):
                login = "lg" + uuid.uuid4().hex[:10]
                token = (await c.post("/api/auth/register", json={"login": login, "password": "secret123"})).json()["token"]
                h = {"Authorization": f"Bearer {token}", "X-Stevens-Features": "d2,d3,d10"}
                fails += await run(c, h, dialog)
    print("fails:", fails)
    sys.exit(1 if fails else 0)

asyncio.run(main())
