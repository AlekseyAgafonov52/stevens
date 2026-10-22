"""Уточнения живыми ответами и несколько дел по очереди: python tests/test_clarify_api.py"""
import asyncio, os, sys, uuid
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app.main import app

CLOCK = "2026-10-21T10:00:00+03:00"
# Диалоги: фраза → kind, кусок текста ответа (None — не проверяем), (текст, дата, время) записи с меткой new
DIALOGS = [
    [
        ("Напомни мне завтра встретиться с Машей и через неделю встретиться с Иваном", "clarify",
         "Во сколько встреча с Машей завтра?", None),
        ("10", "clarify", "Во сколько встреча с Иваном 28 октября?", None),
        ("есть 10 место есть поставь 10 стой убери всё и поставь 10", "created", None,
         ("Встреча с Машей", "2026-10-22", "10:00")),
    ],
    [
        ("Поставь встречу с Петей завтра", "clarify", None, None),
        ("ну", "clarify", None, None),
        ("есть 11 место есть поставь 11 стой убери всё и поставь 11", "created", None,
         ("Встреча с Петей", "2026-10-22", "11:00")),
    ],
    [
        ("Поставь встречу с Олегом завтра", "clarify", None, None),
        ("стой", "cancelled", None, None),
    ],
    [
        ("Напомни мне завтра встретиться с Машей и через неделю встретиться с Иваном", "clarify", None, None),
        ("убери всё", "cancelled", None, None),
    ],
]


async def main():
    fails = 0
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            h = {"X-Client-Id": "clr-" + uuid.uuid4().hex[:12], "X-Stevens-Features": "d2,d3,d10"}
            await c.post("/api/sandbox/reset", headers=h)
            for dialog in DIALOGS:
                conv = str(uuid.uuid4())
                for phrase, kind, says, record in dialog:
                    body = {"conversation_id": conv, "text": phrase, "source": "text", "client_time": CLOCK,
                            "timezone": "Europe/Moscow"}
                    r = (await c.post("/api/chat", json=body, headers=h)).json()
                    new = [(x["text"], x["date"], x["time"]) for x in r["records"] if "new" in x["marks"]]
                    ok = r["kind"] == kind and (says is None or says in r["text"]) and (record is None or record in new)
                    if kind == "clarify" and not r["awaiting_reply"]:
                        ok = False
                    if not ok:
                        fails += 1
                        print(f"«{phrase}» → {r['kind']} {r['text']!r} {new}, ждали {kind} {says!r} {record}")
    print("fails:", fails)
    sys.exit(1 if fails else 0)

asyncio.run(main())
