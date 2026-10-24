"""Удаление и правка фразой, массовое удаление с подтверждением: python tests/test_edit_delete_api.py"""
import asyncio, os, sys, uuid
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app.main import app

CLOCK = "2026-10-21T10:00:00+03:00"
first = lambda r: r["records"][0] if r["records"] else {}
texts = lambda r: [x["text"] for x in r["records"]]
# (фраза или ("", действие)), kind, проверка ответа
DIALOG = [
    # Одиночное удаление с «Вернуть»
    ("Запиши встречу с Иваном 5 января 2031 в 15", "created", None),
    ("Удали встречу с Иваном 5 января 2031", "deleted", lambda r: first(r)["text"] == "Встреча с Иваном"
                                                                and r["buttons"][0]["send"]["action"]["id"] == "restore"),
    (("", "restore"), "created", lambda r: first(r)["text"] == "Встреча с Иваном"),
    ("Напомни 5 января 2031 в 12 про презентацию", "created", None),
    ("убери напоминание про презентацию", "deleted", lambda r: first(r)["type"] == "reminder"),
    # Массовое: сначала спрашивает и показывает, что удалится
    ("Запиши купить хлеб 5 января 2031", "created", None),
    ("удали все дела на 5 января 2031", "confirm", lambda r: r["total"] == 2 and "2 дела" in r["text"]
                                                             and all(x["date"] == "2031-01-05" for x in r["records"])),
    ("нет", "cancelled", None),
    ("что у меня 5 января 2031", "list", lambda r: r["total"] == 2),
    ("Стив, очисти 5 января 2031", "confirm", None),
    ("да, удаляй", "deleted", lambda r: r["total"] == 2 and r["buttons"][0]["send"]["action"]["id"] == "restore_all"),
    (("", "restore_all"), "created", lambda r: r["total"] == 2),
    ("удали все встречи на 5 января 2031", "deleted", lambda r: first(r)["text"] == "Встреча с Иваном"),
    ("удали все встречи на 5 января 2031", "found", lambda r: "нечего" in r["text"]),
    ("убери все дела за все дни", "confirm", lambda r: r["total"] > 900 and "за все дни" in r["text"]),
    (("", "confirm_yes"), "deleted", lambda r: r["total"] > 900),
    (("", "restore_all"), "created", lambda r: r["total"] > 900),
    # Правка: название, тип, заметка, слово
    ("Запиши встречу с Иваном послезавтра в 11", "created", None),
    ("переименуй её в созвон с Иваном", "updated", lambda r: first(r)["text"] == "Созвон с Иваном"),
    ("добавь к ней заметку взять ноутбук", "updated", lambda r: first(r)["text"] == "Созвон с Иваном — взять ноутбук"),
    ("поменяй Ивана на Петра", "updated", lambda r: first(r)["text"] == "Созвон с Петром — взять ноутбук"),
    ("сделай её задачей", "updated", lambda r: first(r)["type"] == "task" and first(r)["status"] == "open"),
    ("Запиши подготовить отчёт", "created", None),
    ("сделай задачу про отчёт напоминанием", "clarify", lambda r: first(r)["type"] == "reminder"),
    ("завтра в 9", "updated", lambda r: first(r)["date"] == "2026-10-22" and first(r)["time"] == "09:00"),
    ("Запиши встречу с Машей 30 декабря в 15", "created", None),
    ("Запиши задачу купить молоко", "created", None),
    ("добавь к встрече с Машей заметку обсудить бюджет", "updated",
     lambda r: first(r)["text"] == "Встреча с Машей — обсудить бюджет"),
    ("переименуй встречу с Машей в демо проекта", "updated", lambda r: first(r)["text"] == "Демо проекта"),
    ("поменяй её на завтра в 18", "updated", lambda r: first(r)["date"] == "2026-10-22" and first(r)["time"] == "18:00"),
    # После поиска «её» — найденная запись; несколько — спрашивает какую
    ("Найди задачу купить молоко", "found", lambda r: r["total"] == 1),
    ("переименуй её в купить кефир", "updated", lambda r: first(r)["text"] == "Купить кефир"),
    ("Найди встречи с Ваней", "found", lambda r: r["total"] > 1),
    ("удали её", "clarify", lambda r: r["buttons"][0]["send"]["action"]["id"] == "delete"),
    ("Найди встречи с Ваней", "found", None),
    ("переименуй её в созвон", "clarify", lambda r: r["buttons"][0]["send"]["action"]["id"] == "edit"),
    (("", "edit"), "updated", lambda r: first(r)["text"] == "Созвон"),
    ("Найди задачу купить кефир", "found", None),
    ("удали её", "deleted", lambda r: first(r)["text"] == "Купить кефир"),
]


async def main():
    fails = 0
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            h = {"X-Client-Id": "ed-" + uuid.uuid4().hex[:12], "X-Stevens-Features": "d2,d3,d10"}
            await c.post("/api/sandbox/reset", headers=h)
            conv = str(uuid.uuid4())
            last = None
            for phrase, kind, check in DIALOG:
                body = {"conversation_id": conv, "text": phrase, "source": "text", "client_time": CLOCK,
                        "timezone": "Europe/Moscow"}
                if isinstance(phrase, tuple):
                    assert last is not None, "Button action requires a previous answer"
                    btn = next((b for b in last["buttons"] if b["send"].get("action", {}).get("id") == phrase[1]), None)
                    if not btn:
                        fails += 1
                        print(f"BAD нет кнопки {phrase[1]}")
                        continue
                    body.update(text=btn["label"], source="button", action=btn["send"]["action"])
                r = (await c.post("/api/chat", json=body, headers=h)).json()
                last = r
                ok = r["kind"] == kind and (check is None or check(r))
                if not ok:
                    fails += 1
                    print(f"BAD «{phrase}» → {r['kind']} {r['text']!r} {texts(r)[:3]} {[b['label'] for b in r['buttons']][:3]}")
    print("fails:", fails)
    sys.exit(1 if fails else 0)

asyncio.run(main())
