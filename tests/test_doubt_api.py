"""«Верно понял?» при неуверенном разборе: python tests/test_doubt_api.py"""
import asyncio, os, sys, uuid
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app.main import app

CLOCK = "2026-10-21T10:00:00+03:00"  # среда
first = lambda r: r["records"][0] if r["records"] else {}
labels = lambda r: [b["label"] for b in r["buttons"]]
asks = lambda r: r["awaiting_reply"] and "Да, верно" in labels(r) and first(r).get("marks") == ["draft"]

# Каждый диалог — с чистого листа
DIALOGS = [
    # Опечатка в дне: исправляем и переспрашиваем
    [("зватра в 10 встреча с Иваном", "confirm",
      lambda r: asks(r) and "«зватра»" in r["text"] and first(r)["date"] == "2026-10-22" and first(r)["time"] == "10:00"
                and first(r)["text"] == "Встреча с Иваном"),
     ("да", "created", lambda r: first(r)["date"] == "2026-10-22")],
    # Два варианта — берём первый, «нет, в четверг» правит сразу
    [("встреча с Иваном в пятницу или в субботу в 12", "confirm",
      lambda r: asks(r) and "два варианта" in r["text"] and first(r)["date"] == "2026-10-23"
                and first(r)["text"] == "Встреча с Иваном"),
     ("нет, в субботу", "created", lambda r: first(r)["date"] == "2026-10-24" and first(r)["time"] == "12:00")],
    # Передумал на ходу — берём последнее время
    [("позвонить в банк завтра в 10 а нет в 11", "confirm",
      lambda r: asks(r) and first(r)["time"] == "11:00" and first(r)["text"] == "Позвонить в банк"),
     ("верно", "created", lambda r: first(r)["time"] == "11:00")],
    # Расплывчатое время: угадываем
    [("встреча в обед с Машей завтра", "confirm",
      lambda r: asks(r) and "«в обед»" in r["text"] and "13:00" in r["text"] and first(r)["time"] == "13:00"),
     ("нет, в 14", "created", lambda r: first(r)["time"] == "14:00")],
    [("напомни завтра вечерком полить цветы", "confirm",
      lambda r: asks(r) and first(r)["time"] == "19:00" and first(r)["text"] == "Полить цветы")],
    # «Попозже» у напоминания: спросит время, после ответа не переспрашивает
    [("напомни попозже позвонить маме", "clarify", lambda r: r["awaiting_reply"]),
     ("сегодня в 18", "created", lambda r: first(r)["text"] == "Позвонить маме" and first(r)["time"] == "18:00")],
    # «На днях» у задачи — без срока, спрашиваем
    [("надо купить молоко на днях", "confirm",
      lambda r: asks(r) and "«на днях»" in r["text"] and first(r)["text"] == "Купить молоко")],
    # Сомнение в голосе
    [("наверное завтра в 10 позвонить в банк", "confirm",
      lambda r: asks(r) and first(r)["text"] == "Позвонить в банк"),
     ("нет", "clarify", lambda r: r["awaiting_reply"]),
     ("в 12", "created", lambda r: first(r)["time"] == "12:00")],
    # «Нет, …» с новым текстом — дата и время остаются
    [("завтра в 10 сделать что-то с отчётом", "confirm", asks),
     ("нет, дописать отчёт", "created",
      lambda r: first(r)["text"] == "Дописать отчёт" and first(r)["date"] == "2026-10-22" and first(r)["time"] == "10:00")],
    # Голосом «нет» по кнопке
    [("встреча с Иваном может в пятницу в 12", "confirm", asks),
     ("неа", "clarify", lambda r: r["awaiting_reply"])],
    # Уверенные фразы — сразу записываем, без вопроса
    [("позвонить маме завтра в 10", "created", None)],
    [("купить чай или кофе", "created", None)],
    [("купить 2 литра молока завтра", "created", None)],
    [("напомни завтра в 9 про завтрак", "created", lambda r: first(r)["text"] == "Завтрак")],
    # Опечатка в списке — просто показываем
    [("что у меня зватра", "list", None)],
]


async def main():
    fails = 0
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            login = "db" + uuid.uuid4().hex[:10]
            token = (await c.post("/api/auth/register", json={"login": login, "password": "secret123"})).json()["token"]
            h = {"Authorization": f"Bearer {token}", "X-Stevens-Features": "d2,d3,d10"}
            for dialog in DIALOGS:
                conv = str(uuid.uuid4())
                for phrase, kind, check in dialog:
                    body = {"conversation_id": conv, "text": phrase, "source": "voice", "client_time": CLOCK,
                            "timezone": "Europe/Moscow"}
                    r = (await c.post("/api/chat", json=body, headers=h)).json()
                    ok = (kind is None or r["kind"] == kind) and (check is None or check(r))
                    print(("ok " if ok else "BAD"), f"«{phrase}» → {r['kind']} {r['text']!r} | {r.get('speech')!r} "
                          f"{[(x['text'], x['date'], x['time']) for x in r['records'][:2]]} {labels(r)[:3]}")
                    fails += not ok
    print("fails:", fails)
    sys.exit(1 if fails else 0)

asyncio.run(main())
