"""Прогон демо-сценария защиты (DEMO.md) в чистой песочнице.

    python tools/demo_check.py                      # в процессе, нужна только база (DATABASE_URL)
    python tools/demo_check.py https://адрес-стенда # по сети, на живом прототипе

Время — текущее московское, как у фронта в день показа. Выход 0 — все шаги прошли.
"""
import asyncio, os, sys, uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.getcwd())
import httpx

# (фраза или [кнопка], ожидаемый kind, что должно быть в ответе: текст первой записи или кусок фразы)
STEPS = [
    ("Что у меня на этой неделе?", "list", None),
    ("Напомни завтра в 10 позвонить Ивану", "created", "Позвонить Ивану"),
    ("Поставь встречу с дизайнером завтра", "clarify", None),
    ("давай в 15", "created", "Встреча с дизайнером"),
    ("Слушай, напомни что завтра нужно встретиться с Машей в 15", "conflict", "Встреча с Машей"),
    ("[Другое время для новой]", "clarify", None),
    ("в 16", "created", "Встреча с Машей"),
    ("Перенеси её на завтра", "clarify", "Встреча с Машей"),
    ("в 17", "updated", "Встреча с Машей"),
    ("Когда я свободен завтра на час?", "clarify", None),
    ("Завтра в 9 созвон с Петей, потом отправить договор Маше", "confirm", "Созвон с Петей"),
    ("[Да, записать все]", "created", None),
    ("Найди встречи с Ваней", "found", "Иван"),
    ("Когда я последний раз звонил Ивану?", "found", "Позвонить Иваном"),
    ("Запиши чтобы я проверил наушники", "created", "Проверить наушники"),
    ("Готово", "completed", "Проверить наушники"),
]


def client_time() -> str:
    msk = timezone(timedelta(hours=3))
    return datetime.now(msk).replace(microsecond=0).isoformat()


async def run(client: httpx.AsyncClient) -> int:
    h = {"X-Client-Id": "demo-" + uuid.uuid4().hex[:12], "X-Stevens-Features": "d2,d3,d10"}
    await client.post("/api/sandbox/reset", headers=h)
    conv, last, fails = str(uuid.uuid4()), {}, 0
    for i, (step, kind, expect) in enumerate(STEPS, 1):
        body = {"conversation_id": conv, "text": step, "source": "text", "client_time": client_time(),
                "timezone": "Europe/Moscow"}
        if step.startswith("["):
            label = step.strip("[]")
            button = next((b for b in last.get("buttons", []) if b["label"] == label), None)
            if not button:
                print(f"{i:2}. ✗ нет кнопки «{label}»")
                fails += 1
                continue
            send = button["send"]
            body.update(text=send.get("text") or label, source="button")
            if send.get("action"):
                body["action"] = send["action"]
        r = (await client.post("/api/chat", json=body, headers=h)).json()
        first = r["records"][0]["text"] if r["records"] else ""
        ok = r["kind"] == kind and (expect is None or expect in first or expect in r["text"])
        fails += not ok
        print(f"{i:2}. {'✓' if ok else '✗'} {step}\n      → [{r['kind']}] {r['text']}")
        if not ok:
            print(f"      ждали [{kind}] {expect or ''}")
        last = r
    print("Все шаги прошли." if not fails else f"Ошибок: {fails}")
    return fails


async def main() -> int:
    if len(sys.argv) > 1:
        async with httpx.AsyncClient(base_url=sys.argv[1].rstrip("/"), timeout=30) as client:
            return await run(client)
    from app.main import app
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            return await run(client)

sys.exit(1 if asyncio.run(main()) else 0)
