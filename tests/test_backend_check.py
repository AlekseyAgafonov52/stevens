"""Проверка бэка 23.10: гонки, ответы LLM, сбои входа. python tests/test_backend_check.py"""
import asyncio, os, sys, time, uuid
from datetime import datetime, timezone
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from sqlalchemy import text
import brain
from app import owner, push
from app.database import AsyncSessionLocal
from app.main import app
from app.models import Record, TaskType, DateKind
from app.routers import chat

CLOCK = "2026-10-21T10:00:00+03:00"  # среда
MONTH = "/api/records?from=2026-10-01&to=2026-10-31"


async def main():
    fails = 0
    def check(name, ok, info=""):
        nonlocal fails
        print(("OK  " if ok else "FAIL"), name, "" if ok else info)
        fails += 0 if ok else 1

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60) as c:
            cid = "chk-" + uuid.uuid4().hex[:12]
            h = {"X-Client-Id": cid, "X-Stevens-Features": "d2,d3,d10"}

            def say(text, **extra):
                return c.post("/api/chat", headers=h, json={"conversation_id": str(uuid.uuid4()), "text": text,
                                                            "client_time": CLOCK} | extra)

            # Новая вкладка: первые запросы разом — демо-данные один раз
            rs = await asyncio.gather(*[c.get(MONTH, headers=h) for _ in range(5)])
            async with AsyncSessionLocal() as db:
                count = (await db.execute(text("select count(*) from records where sandbox_id=:c"), {"c": cid})).scalar()
            check("песочница заполняется один раз", all(r.status_code == 200 for r in rs) and count == 1000, count)

            # Продление повтора: календарь и чат разом не задваивают дни
            r = (await say("каждый вторник в 10 планёрка")).json()
            check("повтор записан", r["kind"] == "created", r["text"])
            async with AsyncSessionLocal() as db:
                await db.execute(text("update series set filled_until='2026-11-01' where sandbox_id=:c"), {"c": cid})
                await db.execute(text("delete from records where sandbox_id=:c and series_id is not null and date>'2026-11-01'"),
                                 {"c": cid})
                await db.commit()
            await asyncio.gather(*[c.get(MONTH, headers=h) for _ in range(4)], say("что у меня завтра"))
            async with AsyncSessionLocal() as db:
                total, days = (await db.execute(text(
                    "select count(*), count(distinct date) from records where sandbox_id=:c and series_id is not null"),
                    {"c": cid})).one()
            check("повтор продлён без дублей", total == days and total > 40, (total, days))

            # Регистрация двойным кликом: один вход, второй — «логин занят», а не 500
            login = "chk" + uuid.uuid4().hex[:8]
            rs = await asyncio.gather(*[c.post("/api/auth/register", json={"login": login, "password": "12345"})
                                        for _ in range(3)])
            codes = sorted(r.status_code for r in rs)
            check("двойная регистрация", codes == [200, 409, 409], codes)

            # Пока bcrypt проверяет пароль, сервер отвечает другим
            async def health_during_login():
                await asyncio.sleep(0.02)
                started = time.perf_counter()
                await c.get("/api/health")
                return time.perf_counter() - started
            *_, wait = await asyncio.gather(*[c.post("/api/auth/login", json={"login": login, "password": "12345"})
                                              for _ in range(3)], health_during_login())
            check("вход не стопорит сервер", wait < 0.15, round(wait, 3))

            # Без client_time и с пустым текстом — ответ, а не 500
            r = await c.post("/api/chat", headers=h, json={"conversation_id": "x", "text": "что у меня сегодня"})
            check("без client_time", r.status_code == 200, r.status_code)
            r = await c.post("/api/chat", headers=h, json={"conversation_id": "x", "action": {"id": "zzz"}})
            check("неизвестная кнопка без текста", r.status_code == 200, r.status_code)
            r = await c.post("/api/chat", headers=h, json={"conversation_id": "x" * 500, "text": "привет"})
            check("слишком длинный conversation_id", r.status_code == 422, r.status_code)

            # Ответы LLM: кривое время не записываем, встреча «до» становится точной
            os.environ["YANDEX_API_KEY"], os.environ["YANDEX_FOLDER_ID"] = "test", "test"
            original = brain.parse_user_input

            async def llm(**fields):
                brain.parse_user_input = lambda text_: brain.IntentSchema(**fields)
                conv = str(uuid.uuid4())
                r = (await say("бубубу непонятная фраза", conversation_id=conv)).json()
                if fields["intent"].startswith("create_") and r["kind"] == "confirm":
                    # Разбор нейросети — черновик с «верно понял?»; соглашаемся
                    check("LLM: черновик с «верно понял?»", r["records"][0]["marks"] == ["draft"], r["text"])
                    r = (await say("да", conversation_id=conv)).json()
                return r

            r = await llm(intent="create_meeting", text="Встреча с Петей", date="tomorrow", time="25:99")
            check("LLM: время 25:99 не записано", r["kind"] == "clarify" and not r["records"], (r["kind"], r["text"]))
            r = await llm(intent="create_reminder", text="Полить цветы", date="tomorrow", time="9:30:00")
            check("LLM: 9:30:00 → 09:30", r["kind"] == "created" and r["records"][0]["time"] == "09:30", r["text"])
            r = await llm(intent="create_meeting", text="Созвон с Олей", date="tomorrow", time="11:00", date_kind="deadline")
            check("LLM: встреча «до» — точная", r["kind"] == "created" and r["records"][0]["date_kind"] == "exact"
                  and "до " not in r["text"], r["text"])
            r = await llm(intent="create_task", text="я" * 400, date="friday")
            check("LLM: длинный текст обрезан", r["kind"] == "created" and len(r["records"][0]["text"]) <= 300)

            # Пока LLM думает, остальные запросы не ждут
            def slow(text_):
                time.sleep(1)
                return brain.IntentSchema(intent="unknown")
            brain.parse_user_input = slow

            async def health_during_llm():
                await asyncio.sleep(0.1)
                started = time.perf_counter()
                await c.get("/api/health")
                return time.perf_counter() - started
            _, wait = await asyncio.gather(say("бубубу"), health_during_llm())
            check("LLM не стопорит сервер", wait < 0.3, round(wait, 3))
            # Яндекс лёг: после первого сбоя минуту его не ждём
            calls = []
            def down(text_):
                calls.append(text_)
                raise brain.openai.APIConnectionError(request=httpx.Request("POST", "https://llm"))
            brain.parse_user_input = down
            chat._llm_down_until = 0.0
            r1, r2 = (await say("бубубу раз")).json(), (await say("бубубу два")).json()
            check("Яндекс лёг — не ждём его повторно", r1["kind"] == r2["kind"] == "not_understood" and len(calls) == 1,
                  (r1["kind"], r2["kind"], len(calls)))
            chat._llm_down_until = 0.0
            brain.parse_user_input = original
            del os.environ["YANDEX_API_KEY"], os.environ["YANDEX_FOLDER_ID"]
            check("у Яндекса есть таймаут", 0 < brain.client.timeout <= 15 and brain.client.max_retries <= 1,
                  (brain.client.timeout, brain.client.max_retries))

            # Запись с кривым временем в базе не останавливает уведомления
            bad = Record(sandbox_id=cid, type=TaskType.reminder, text="Кривая", date="2026-10-21", time="25:99",
                         date_kind=DateKind.exact, created_at=datetime.now(timezone.utc))
            check("кривое время пропущено", push.fire_at(bad, timezone.utc) is None)

            # Заброшенные песочницы: удаляются целиком, общая и свежие остаются
            old_id = "old-" + uuid.uuid4().hex[:12]
            await c.get(MONTH, headers={"X-Client-Id": old_id})
            await c.post("/api/chat", headers={"X-Client-Id": old_id}, json={
                "conversation_id": "o", "text": "каждый вторник в 10 планёрка", "client_time": CLOCK})
            await c.get(MONTH)  # общая
            async with AsyncSessionLocal() as db:
                await db.execute(text("update sandboxes set seen_at = now() - interval '40 days' "
                                      "where client_id in (:o, 'shared-demo')"), {"o": old_id})
                await db.commit()
                removed = await owner.clean_sandboxes(db, 30)
                left = (await db.execute(text("select count(*) from records where sandbox_id=:o"), {"o": old_id})).scalar()
                boxes = set((await db.execute(text("select client_id from sandboxes where client_id in (:o, :c, 'shared-demo')"),
                                              {"o": old_id, "c": cid})).scalars())
            check("заброшенная песочница удалена", removed >= 1 and left == 0 and boxes == {cid, "shared-demo"},
                  (removed, left, boxes))
            r = await c.get(MONTH, headers={"X-Client-Id": old_id})
            check("вернулся — песочница заново", r.status_code == 200 and len(r.json()["records"]) > 0)
            async with AsyncSessionLocal() as db:
                await db.execute(text("update sandboxes set seen_at = now() - interval '2 hours' where client_id=:c"), {"c": cid})
                await db.commit()
            await c.get(MONTH, headers=h)
            async with AsyncSessionLocal() as db:
                fresh = (await db.execute(text("select seen_at > now() - interval '1 minute' from sandboxes where client_id=:c"),
                                          {"c": cid})).scalar()
            check("заход обновляет seen_at", fresh)

    print("fails:", fails)
    sys.exit(1 if fails else 0)


asyncio.run(main())
