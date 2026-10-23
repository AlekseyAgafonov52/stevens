"""Повторы, задачи без срока к списку, заметки и время создания: python tests/test_repeat_api.py"""
import asyncio, os, sys, uuid
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app.main import app

CLOCK = "2026-10-21T10:00:00+03:00"  # среда
first = lambda r: r["records"][0] if r["records"] else {}
texts = lambda r: [x["text"] for x in r["records"]]
labels = lambda r: [b["label"] for b in r["buttons"]]


def week(r):
    return [(x["date"], x["text"]) for x in r["records"]]


DIALOG = [
    # Создание повторов
    ("каждый вторник у меня планёрка в 10", "created",
     lambda r: first(r)["date"] == "2026-10-27" and first(r)["time"] == "10:00" and first(r)["type"] == "meeting"
               and first(r)["repeat"] == {"weekdays": [1], "until": None} and "каждый вторник" in r["text"]
               and first(r)["created_at"]),
    ("по средам и пятницам у меня йога в 19 до конца года", "created",
     lambda r: first(r)["date"] == "2026-10-21" and first(r)["repeat"] == {"weekdays": [2, 4], "until": "2026-12-31"}
               and r["total"] == 21 and "31 декабря" in r["text"]),
    ("напомни каждый понедельник в 9 выносить мусор до июня", "created",
     lambda r: first(r)["type"] == "reminder" and first(r)["date"] == "2026-10-26"
               and first(r)["repeat"]["until"] == "2027-05-31"),
    # Сегодняшний день, время уже прошло — начинаем через неделю
    ("каждую среду в 9 зарядка", "created", lambda r: first(r)["date"] == "2026-10-28"),
    # Встреча без времени — спросит время, повтор не потеряет
    ("каждый четверг созвон с командой", "clarify", lambda r: r["awaiting_reply"]),
    ("в 11", "created", lambda r: first(r)["date"] == "2026-10-22" and first(r)["repeat"]["weekdays"] == [3]),
    # Список недели: все дни повторов на месте
    ("что у меня на следующей неделе", "list",
     lambda r: ("2026-10-27", "Планёрка") in week(r) and ("2026-10-28", "Йога") in week(r)
               and ("2026-10-30", "Йога") in week(r) and ("2026-10-26", "Выносить мусор") in week(r)),
    # Поиск: из повтора — один ближайший день
    ("найди планёрку", "found", lambda r: r["total"] == 1 and first(r)["date"] == "2026-10-27"),
    # Удаление одного дня
    ("удали планёрку в следующий вторник", "deleted",
     lambda r: first(r)["date"] == "2026-10-27" and ("остальные" in r["text"].lower() or "только" in r["text"])),
    ("что у меня 3 ноября", "list", lambda r: "Планёрка" in texts(r)),
    # Без дня — спрашивает
    ("удали йогу", "clarify", lambda r: "Все предстоящие" in labels(r) and r["awaiting_reply"]),
    ("только ближайшую", "deleted", lambda r: first(r)["date"] == "2026-10-21"),
    ("что у меня в пятницу", "list", lambda r: "Йога" in texts(r)),
    # «Вообще» — все предстоящие дни
    ("убери планёрку вообще", "deleted", lambda r: r["total"] >= 50 and "Вернуть все" in labels(r)),
    ("что у меня 3 ноября", "list", lambda r: "Планёрка" not in texts(r)),
    ("верни все", None, None),
    ("удали йогу", "clarify", None),
    ("все", "deleted", lambda r: r["total"] == 20),
    ("что у меня в пятницу", "list", lambda r: "Йога" not in texts(r)),
    ("удали все созвоны с командой", "deleted", lambda r: r["total"] >= 50),
    # Задачи без срока к списку
    ("Запиши купить подарок маме", "created", lambda r: first(r)["date_kind"] == "none"),
    ("Запиши разобрать балкон", "created", None),
    ("заметка: идея для стартапа", "created", lambda r: first(r)["type"] == "note" and first(r)["created_at"]),
    ("что у меня завтра", "list",
     lambda r: "2 задачи без срока" in r["text"] or "2 задачи" in r["text"] and r["awaiting_reply"]
               and "Показать" in labels(r)),
    ("нет", "cancelled", None),
    ("что у меня на этой неделе", "list", lambda r: "без срока" in r["text"]),
    ("да", "found", lambda r: texts(r) == ["Разобрать балкон", "Купить подарок маме"]),
    ("что у меня в декабре", "list", lambda r: "без срока" not in r["text"]),
    ("какие у меня встречи завтра", "list", lambda r: "без срока" not in r["text"]),
    ("покажи задачи без срока", "found", lambda r: r["total"] == 2),
    # «Да» голосом на «Записать все?»
    ("завтра в 9:00 с Петей потом отправить договор Маше", "confirm", lambda r: texts(r)[0] == "Встреча с Петей"),
    ("ммм ну это", "clarify", lambda r: r["awaiting_reply"]),
    ("да записать всё", "created", lambda r: len(r["records"]) == 2),
    ("завтра в 11 созвон с Олегом потом купить корм", "confirm", None),
    ("нет", "cancelled", None),
    # Заметки не предлагаются как задачи без срока, но находятся
    ("покажи все заметки", "found", lambda r: texts(r) == ["Идея для стартапа"]),
    ("найди заметку про стартап", "found", lambda r: texts(r) == ["Идея для стартапа"]),
]


async def main():
    fails = 0
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            login = "rp" + uuid.uuid4().hex[:10]
            token = (await c.post("/api/auth/register", json={"login": login, "password": "secret123"})).json()["token"]
            h = {"Authorization": f"Bearer {token}", "X-Stevens-Features": "d2,d3,d10"}
            conv = str(uuid.uuid4())
            for phrase, kind, check in DIALOG:
                body = {"conversation_id": conv, "text": phrase, "source": "voice", "client_time": CLOCK,
                        "timezone": "Europe/Moscow"}
                r = (await c.post("/api/chat", json=body, headers=h)).json()
                ok = (kind is None or r["kind"] == kind) and (check is None or check(r))
                if not ok:
                    fails += 1
                    print(f"BAD «{phrase}» → {r['kind']} {r['text']!r} {texts(r)[:3]} total={r['total']} {labels(r)[:3]}")
            # Календарь отдаёт дни повторов, у всех записей есть время создания
            rows = (await c.get("/api/records?from=2026-10-01&to=2027-12-31", headers=h)).json()["records"]
            if not rows or any(not x["created_at"] for x in rows):
                fails += 1
                print("BAD records created_at")
            # В песочнице у демо-записей тоже есть время создания, они помечены demo
            s = {"X-Client-Id": "rp-" + uuid.uuid4().hex[:12]}
            await c.post("/api/sandbox/reset", headers=s)
            demo = (await c.get("/api/records?from=2026-01-01&to=2027-12-31", headers=s)).json()["records"]
            if not demo or any(not x["created_at"] or not x["demo"] for x in demo):
                fails += 1
                print("BAD demo created_at")
    print("fails:", fails)
    sys.exit(1 if fails else 0)

asyncio.run(main())
