"""Full dialogues: finite repeat, one cancelled occurrence, past context and anaphora."""
import asyncio
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app.main import app


async def main():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            auth = await c.post("/api/auth/register", json={"login": "ctx" + uuid.uuid4().hex[:12], "password": "test-password"})
            assert auth.status_code == 200, auth.text
            headers = {"Authorization": "Bearer " + auth.json()["token"]}
            conversation = uuid.uuid4().hex

            async def say(text, *, conv=None, action=None):
                body = {"text": text, "conversation_id": conv or conversation, "source": "text",
                        "client_time": "2026-10-25T10:00:00+03:00", "timezone": "Europe/Moscow"}
                if action:
                    body["action"] = action
                response = await c.post("/api/chat", headers=headers, json=body)
                assert response.status_code == 200, response.text
                return response.json()

            async def records():
                response = await c.get("/api/records/export", headers=headers)
                assert response.status_code == 200, response.text
                return response.json()["records"]

            control = await say("Напомни 17 ноября в 9 позвонить Ивану")
            assert control["kind"] == "created", control
            control_id = control["records"][0]["id"]
            created = await say("Поставь напоминания на месяц вперед репетитор каждый вторник в 9.00")
            assert created["kind"] == "created", created
            before = [r for r in await records() if r["text"] == "Репетитор"]
            assert len(before) == 5, before
            assert all(r["time"] == "09:00" and r["repeat"]["until"] == "2026-11-24" for r in before), before
            cancelled = await say("17 ноября занятий не будет")
            assert cancelled["kind"] == "deleted" and cancelled["records"][0]["date"] == "2026-11-17", cancelled
            deleted_id = cancelled["records"][0]["id"]
            after = await records()
            assert any(r["id"] == control_id for r in after), after
            assert {r["date"] for r in after if r["text"] == "Репетитор"} == {r["date"] for r in before} - {"2026-11-17"}
            unchanged = await say("16 ноября занятий не будет")
            assert unchanged["kind"] == "found" and unchanged["total"] == 0, unchanged
            assert len(await records()) == len(after)
            no_context = await say("17 ноября занятий не будет", conv=uuid.uuid4().hex)
            assert no_context["kind"] == "clarify", no_context
            assert len(await records()) == len(after)
            await say("Вернуть", action={"id": "restore", "record_id": deleted_id})
            assert len([r for r in await records() if r["text"] == "Репетитор"]) == 5

            math_conv = uuid.uuid4().hex
            asked = await say("я вчера не сделал задачку по математике напомни через 2 дня сделать", conv=math_conv)
            assert asked["kind"] == "clarify" and asked["awaiting_reply"], asked
            done = await say("в 18", conv=math_conv)
            assert done["kind"] == "created", done
            row = done["records"][0]
            assert (row["text"], row["date"], row["time"]) == ("Сделать задачку по математике", "2026-10-27", "18:00"), row
            print("PASS: finite tutor series, scoped cancellation/restore, missing context, relative math reminder")


if __name__ == "__main__":
    asyncio.run(main())
