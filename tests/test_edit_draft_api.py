"""«Исправить» вместо «Нет» под «Верно?»: python tests/test_edit_draft_api.py"""
import asyncio, os, sys, uuid
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app.main import app

CLOCK = "2026-10-21T10:00:00+03:00"  # среда
first = lambda r: r["records"][0] if r["records"] else {}
labels = lambda r: [b["label"] for b in r["buttons"]]
fix = lambda index, **v: {"id": "edit_draft", "index": index, "values": {
    "type": "task", "text": "", "date": None, "time": None, "end_time": None, "remind_before": None, **v}}

# (фраза или действие, kind, проверка)
DIALOGS = [
    # Неуверенный разбор: «Да, верно» и «Исправить», форма записывает как ввёл человек
    [("наверное завтра в 10 позвонить в банк", "confirm", lambda r: labels(r) == ["Да, верно", "Исправить"]),
     (fix(0, text="позвонить в банк про карту", date="2026-10-23", time="11:30"), "created",
      lambda r: (first(r)["text"], first(r)["date"], first(r)["time"]) == ("Позвонить в банк про карту", "2026-10-23", "11:30")
                and "draft" not in first(r)["marks"])],
    # Смена типа в форме: встреча с напоминанием за 30 минут
    [("встреча в обед с Машей завтра", "confirm", lambda r: "Исправить" in labels(r)),
     (fix(0, type="meeting", text="Обед с Машей", date="2026-10-22", time="13:30", remind_before=30), "created",
      lambda r: first(r)["type"] == "meeting" and first(r)["time"] == "13:30" and first(r)["remind_before"] == 30)],
    # Голосом «нет» работает как раньше
    [("наверное завтра в 10 позвонить в банк", "confirm", None), ("нет", "clarify", lambda r: r["awaiting_reply"]),
     ("в 12", "created", lambda r: first(r)["time"] == "12:00")],
    # Несколько дел: правим второе, карточки обновились, вопрос остался; «да» пишет все
    [("завтра в 10 позвонить маме и в 15 купить хлеб", "confirm", lambda r: labels(r) == ["Да, записать все", "Исправить"]),
     (fix(1, text="Купить батон", date="2026-10-22", time="16:00"), "confirm",
      lambda r: r["awaiting_reply"] and [x["text"] for x in r["records"]] == ["Позвонить маме", "Купить батон"]
                and r["records"][1]["time"] == "16:00"),
     ({"id": "confirm_yes"}, "created", lambda r: len(r["records"]) == 2)],
    # Плохие поля не записываются
    [("наверное завтра в 10 позвонить в банк", "confirm", None),
     (fix(0, text="", date="2026-10-22"), "clarify", None),
     (fix(0, text="Банк", date="2026-10-22", time="25:00"), "clarify", None),
     (fix(3, text="Банк", date="2026-10-22"), "clarify", None)],
    # Без вопроса «Верно?» действие ничего не делает
    [(fix(0, text="Купить хлеб"), "clarify", None)],
]


async def main():
    fails = 0
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            login = "ed" + uuid.uuid4().hex[:10]
            token = (await c.post("/api/auth/register", json={"login": login, "password": "secret123"})).json()["token"]
            h = {"Authorization": f"Bearer {token}", "X-Stevens-Features": "d2,d3,d10"}
            for dialog in DIALOGS:
                conv = str(uuid.uuid4())
                for say, kind, check in dialog:
                    body = {"conversation_id": conv, "text": say if isinstance(say, str) else "Сохранить",
                            "source": "voice" if isinstance(say, str) else "button", "client_time": CLOCK,
                            "timezone": "Europe/Moscow", "action": None if isinstance(say, str) else say}
                    r = (await c.post("/api/chat", json=body, headers=h)).json()
                    ok = (kind is None or r["kind"] == kind) and (check is None or check(r))
                    print(("ok " if ok else "BAD"), f"«{say if isinstance(say, str) else say['id']}» → {r['kind']} {r['text']!r} "
                          f"{[(x['type'], x['text'], x['date'], x['time']) for x in r['records'][:2]]} {labels(r)[:3]}")
                    fails += not ok
    print("fails:", fails)
    sys.exit(1 if fails else 0)

asyncio.run(main())
