"""Заметки без времени: «запиши идею: …», «покажи заметки»: python tests/test_notes_api.py"""
import asyncio, os, sys, uuid
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app.main import app

CLOCK = "2026-10-21T10:00:00+03:00"
first = lambda r: r["records"][0] if r["records"] else {}
texts = lambda r: [x["text"] for x in r["records"]]
DIALOG = [
    ("покажи заметки", "found", lambda r: r["total"] == 0 and "нет" in r["text"]),
    ("Запиши идею: открыть кофейню у дома", "created",
     lambda r: first(r)["type"] == "note" and first(r)["text"] == "Открыть кофейню у дома" and first(r)["date"] is None
               and first(r)["status"] is None),
    ("Стив, заметка: купить подарок маме", "created", lambda r: first(r)["text"] == "Купить подарок маме"),
    ("сохрани в заметки пароль от вайфая на даче 1234", "created", lambda r: first(r)["type"] == "note"),
    ("запиши мысль что нужно больше спать", "created", lambda r: first(r)["text"] == "Нужно больше спать"),
    ("Запиши идею", "clarify", lambda r: r["awaiting_reply"]),
    ("подкаст про стартапы", "created", lambda r: first(r)["type"] == "note" and first(r)["text"] == "Подкаст про стартапы"),
    # Список: свежие сверху
    ("покажи мои заметки", "found", lambda r: r["total"] == 5 and texts(r)[0] == "Подкаст про стартапы"
                                              and all(x["type"] == "note" for x in r["records"])),
    ("какие у меня идеи", "found", lambda r: r["total"] == 5),
    ("заметки про кофейню", "found", lambda r: texts(r) == ["Открыть кофейню у дома"]),
    ("найди заметку про подарок", "found", lambda r: texts(r) == ["Купить подарок маме"]),
    # В расписание заметки не попадают
    ("что у меня сегодня", "list", lambda r: all(x["type"] != "note" for x in r["records"])),
    ("что у меня на этой неделе", "list", lambda r: all(x["type"] != "note" for x in r["records"])),
    # Обычные записи — как раньше
    ("Запиши купить хлеб", "created", lambda r: first(r)["type"] == "task"),
    ("добавь к ней заметку белый", "updated", lambda r: first(r)["text"] == "Купить хлеб — белый"),
    # Удаление
    ("удали заметку про вайфай", "deleted", lambda r: first(r)["type"] == "note"),
    ("покажи заметки", "found", lambda r: r["total"] == 4),
    ("удали все заметки", "confirm", lambda r: r["total"] == 4),
    ("да", "deleted", lambda r: r["total"] == 4),
    ("покажи заметки", "found", lambda r: r["total"] == 0),
]


async def main():
    fails = 0
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            h = {"X-Client-Id": "nt-" + uuid.uuid4().hex[:12], "X-Stevens-Features": "d2,d3,d10"}
            await c.post("/api/sandbox/reset", headers=h)
            conv = str(uuid.uuid4())
            for phrase, kind, check in DIALOG:
                body = {"conversation_id": conv, "text": phrase, "source": "text", "client_time": CLOCK,
                        "timezone": "Europe/Moscow"}
                r = (await c.post("/api/chat", json=body, headers=h)).json()
                ok = r["kind"] == kind and (check is None or check(r))
                if not ok:
                    fails += 1
                    print(f"BAD «{phrase}» → {r['kind']} {r['text']!r} {texts(r)[:3]} {[b['label'] for b in r['buttons']][:3]}")
            # REST: дату заметке не поставить
            r = (await c.post("/api/chat", json={"conversation_id": conv, "text": "заметка: тест", "source": "text",
                                                  "client_time": CLOCK, "timezone": "Europe/Moscow"}, headers=h)).json()
            rid = first(r)["id"]
            bad = await c.patch(f"/api/records/{rid}", json={"date": "2026-10-22"}, headers=h)
            good = await c.patch(f"/api/records/{rid}", json={"text": "тест 2"}, headers=h)
            if bad.status_code != 422 or good.status_code != 200:
                fails += 1
                print("BAD REST", bad.status_code, good.status_code)
    print("fails:", fails)
    sys.exit(1 if fails else 0)

asyncio.run(main())
