"""Журнал 24.10: дубль и пересечение занятости, «удали первую», «во вт», «ближайшие 10 дней», «задача: диплом»,
пуш без «Позвольте напомнить», импорт и выгрузка — python tests/test_commands_busy_api.py"""
import asyncio, json, os, sys, uuid
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app import push
from app.main import app
from app.models import Record, TaskType

CLOCK = "2026-10-24T14:10:00+03:00"  # суббота
first = lambda r: r["records"][0] if r["records"] else {}
texts = lambda r: [x["text"] for x in r["records"]]
labels = lambda r: [b["label"] for b in r["buttons"]]

DIALOG = [
    ("работа по вторникам с 16:40 до 19:50", "created", lambda r: first(r)["type"] == "busy"),
    # Второй раз то же — не дублируем
    ("работа по вторникам с 16:40 до 19:50", "created", lambda r: "уже" in r["text"] and len(r["records"]) == 1),
    ("работа по четвергам с 15:50 до 19:50", "created", None),
    # Пересечение занятостей — как у встреч
    ("во вторник с 18 до 21 занят: курсы", "conflict",
     lambda r: "«Работа»" in r["text"] and labels(r)[:3] == ["Другое время для новой", "Изменить существующую", "Оставить обе"]),
    ("сохранить обе", "created", lambda r: first(r)["text"] == "Курсы" and first(r)["time"] == "18:00"),
    ("в четверг 29 октября с 19 до 20 занятость: йога", "conflict", lambda r: texts(r)[0] == "Йога"),
    ("изменить новую", "clarify", lambda r: "Йога" in r["text"]),
    ("с 20 до 21", "created", lambda r: first(r)["time"] == "20:00" and first(r)["end_time"] == "21:00"),
    # «Во вт», «удали первую» после списка
    ("покажи занятость во вт", "list", lambda r: texts(r) == ["Работа", "Курсы"]),
    ("удали вторую", "deleted", lambda r: first(r)["text"] == "Курсы"),
    ("что у меня в четверг", "list", lambda r: texts(r) == ["Работа", "Йога"]),
    ("удали пятую", "found", lambda r: r["total"] == 0),
    ("убери занятость во вторник", "deleted", lambda r: first(r)["text"] == "Работа" and first(r)["date"] == "2026-10-27"),
    # Ближайшие N дней — от сегодня
    ("завтра в 10 напомни позвонить маме", "created", None),
    ("в пятницу в 12 встреча с Олегом", "created", None),
    ("какие дела в ближайшие 10 дней", "list",
     lambda r: "ближайшие 10 дней" in r["text"] and {"Позвонить маме", "Встреча с Олегом"} <= set(texts(r))),
    ("что у меня на следующие три дня", "list", lambda r: "Встреча с Олегом" not in texts(r)),
    # Задача без срока
    ("задача: диплом", "created", lambda r: first(r)["type"] == "task" and first(r)["text"] == "Диплом" and first(r)["date"] is None),
    ("сделай задачу: диплом", "created", lambda r: first(r)["text"] == "Диплом"),
    ("задача почитать книгу для диплома", "created", lambda r: first(r)["text"] == "Почитать книгу для диплома"),
    ("поставь задачу на пятницу: отправить договор", "created", lambda r: first(r)["date"] == "2026-10-30"),
]


async def main():
    fails = 0

    def check(name, ok, detail: object=""):
        nonlocal fails
        print(("ok " if ok else "BAD"), name, "" if ok else detail)
        fails += not ok

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            login = "cb" + uuid.uuid4().hex[:10]
            token = (await c.post("/api/auth/register", json={"login": login, "password": "secret123"})).json()["token"]
            h = {"Authorization": f"Bearer {token}", "X-Stevens-Features": "d2,d3,d10"}
            conv = str(uuid.uuid4())
            for phrase, kind, test in DIALOG:
                body = {"conversation_id": conv, "text": phrase, "source": "text", "client_time": CLOCK,
                        "timezone": "Europe/Moscow"}
                r = (await c.post("/api/chat", json=body, headers=h)).json()
                ok = (kind is None or r["kind"] == kind) and (test is None or test(r))
                check(f"«{phrase}» → {r['kind']}", ok, f"{r['text']!r} {texts(r)[:3]} {labels(r)[:3]}")

            # Пуш: заголовок — текст записи, без «Позвольте напомнить»
            reminder = Record(id=1, type=TaskType.reminder, text="Ехать на ОВК", date="2026-10-24", time="15:00")
            data = json.loads(push.payload(reminder))
            check("пуш напоминания", (data["title"], data["body"]) == ("Ехать на ОВК", ""), data)

            # Выгрузка: повтор — одной строкой «sN», остальное — записями
            ex = (await c.get("/api/transfer/export", params={"client_time": CLOCK}, headers=h)).json()
            rows = ex["records"]
            repeats = [x for x in rows if str(x["id"]).startswith("s")]
            check("выгрузка", ex["stevens"] == 1 and "how" in ex and len(repeats) == 2
                  and all(isinstance(x["id"], int) for x in rows if x not in repeats), rows[:3])
            work = next(x for x in repeats if x["repeat"]["weekdays"] == [3])
            diplom = next(x for x in rows if x["text"] == "Диплом")
            meeting = next(x for x in rows if x["type"] == "meeting")
            edit = {"records": [
                {**work, "end_time": "20:00"},
                {"id": diplom["id"], "delete": True},
                {**meeting, "time": "13:00"},
                {"type": "busy", "text": "Пары", "date": "2026-10-26", "time": "10:00", "end_time": "13:20"},
                {"type": "задача", "text": "Купить книгу", "date": None},
                {"type": "busy", "text": "Спорт", "time": "07:00", "end_time": "08:00",
                 "repeat": {"weekdays": ["пн", "ср"], "until": None}},
                {"type": "meeting", "text": "Без времени", "date": "2026-10-27"},
                {"id": 999999999, "text": "нет такой"},
            ]}
            text = "Готово:\n```json\n" + json.dumps(edit, ensure_ascii=False, indent=1) + ",\n```"
            preview = (await c.post("/api/transfer/import", json={"text": text, "apply": False, "client_time": CLOCK},
                                    headers=h)).json()
            counts = lambda d: (d["add"], d["update"], d["delete"], len(d["errors"]))
            check("предпросмотр", counts(preview) == (3, 2, 1, 2) and preview["applied"] is False, counts(preview))
            same = (await c.get("/api/transfer/export", params={"client_time": CLOCK}, headers=h)).json()["records"]
            check("предпросмотр ничего не меняет", same == rows)
            failed = await c.post("/api/transfer/import", json={"text": text, "apply": True, "client_time": CLOCK}, headers=h)
            check("ошибка импорта — без частичного применения", failed.status_code == 422
                  and (await c.get("/api/transfer/export", params={"client_time": CLOCK}, headers=h)).json()["records"] == rows)
            valid_text = json.dumps({"records": edit["records"][:-2]}, ensure_ascii=False)
            done = (await c.post("/api/transfer/import", json={"text": valid_text, "apply": True, "client_time": CLOCK},
                                 headers=h)).json()
            check("применить", counts(done) == (3, 2, 1, 0) and done["applied"] is True, counts(done))
            after = (await c.get("/api/transfer/export", params={"client_time": CLOCK}, headers=h)).json()["records"]
            by_text = {x["text"]: x for x in after}
            check("после импорта",
                  "Диплом" in [x["text"] for x in after if x["id"] != diplom["id"]] and diplom["id"] not in [x["id"] for x in after]
                  and next(x for x in after if x["id"] == work["id"])["end_time"] == "20:00"
                  and by_text["Встреча с Олегом"]["time"] == "13:00" and by_text["Пары"]["end_time"] == "13:20"
                  and by_text["Купить книгу"]["date"] is None and by_text["Спорт"]["repeat"]["weekdays"] == [0, 2]
                  and "Без времени" not in by_text, after)
            rows = (await c.get("/api/records?from=2026-10-29&to=2026-10-29", headers=h)).json()["records"]
            check("правка повтора — во всех днях", any(x["text"] == "Работа" and x["end_time"] == "20:00" for x in rows), rows)
            again = (await c.post("/api/transfer/import", json={"text": json.dumps({"records": after}), "apply": False, "client_time": CLOCK},
                                  headers=h)).json()
            check("та же выгрузка — менять нечего", counts(again) == (0, 0, 0, 0) and again["unchanged"] == len(after),
                  counts(again))
            bad = await c.post("/api/transfer/import", json={"text": "{оops", "apply": False}, headers=h)
            check("кривой JSON", bad.status_code == 422 and bad.json()["error"] == "bad_json", bad.text)
    print("fails:", fails)
    sys.exit(1 if fails else 0)

asyncio.run(main())
