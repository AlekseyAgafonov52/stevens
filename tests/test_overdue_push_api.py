"""Actual persisted hourly delivery, restart deduplication and completion over HTTP."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import sys
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:overdue-test@127.0.0.1:55442/stevens_overdue_check")

import httpx
from sqlalchemy import select
from app import push
from app.database import AsyncSessionLocal
from app.main import app
from app.models import DateKind, PushSent, PushSubscription, Record, TaskStatus, TaskType


async def idle():
    await asyncio.Event().wait()


async def main():
    moment = datetime(2026, 10, 21, 10, 59, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

    sent = []
    failures = set()

    def send(sub, data, key):
        sent.append((sub.endpoint, json.loads(data)))
        return None if sub.endpoint in failures else True

    with patch.object(push, "loop", idle), patch.object(push, "send", send), patch.object(push, "datetime", Clock):
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                auth = (await client.post("/api/auth/register", json={"login": "ov" + uuid4().hex[:12], "password": "test-password"})).json()
                account = auth["user"]["id"]
                headers = {"Authorization": "Bearer " + auth["token"]}
                endpoint = "https://fcm.googleapis.com/overdue/" + uuid4().hex
                async with AsyncSessionLocal() as db:
                    db.add(PushSubscription(account_id=account, endpoint=endpoint, p256dh="test", auth="test", timezone="UTC"))
                    rows = [Record(account_id=account, type=kind, text=kind.value, date="2026-10-21", time="10:00",
                                   date_kind=DateKind.exact, status=None if kind == TaskType.meeting else TaskStatus.open)
                            for kind in (TaskType.task, TaskType.reminder, TaskType.meeting)]
                    old = Record(account_id=account, type=TaskType.task, text="old", date="2026-10-01", time="10:00",
                                 date_kind=DateKind.exact, status=TaskStatus.open)
                    db.add_all([*rows, old])
                    db.add_all([Record(account_id=account, type=kind, text="ignored", date="2026-10-01", time="10:00",
                                       date_kind=DateKind.exact, demo=True if kind == TaskType.task else False)
                                for kind in (TaskType.task, TaskType.busy, TaskType.note)])
                    await db.commit()
                    ids = [r.id for r in rows]
                    old_id = old.id
                mine = lambda: [data for dest, data in sent if dest == endpoint]
                await push.tick()
                assert [d["record_id"] for d in mine()] == [old_id], mine()
                moment = moment.replace(hour=11, minute=0)
                await push.tick()
                assert len(mine()) == 4 and {d["record_id"] for d in mine()} == {*ids, old_id}, mine()
                assert all(d["overdue"] for d in mine())
                # New ticks and new DB sessions cannot redeliver the same hourly reminder.
                await push.tick()
                moment += timedelta(minutes=59)
                await push.tick()
                assert len(mine()) == 5, mine()  # old event's next hour was 11:59
                moment = moment.replace(hour=12, minute=0)
                await push.tick()
                assert len(mine()) == 8, mine()
                for rid in (ids[0], ids[2]):
                    response = await client.patch(f"/api/records/{rid}", headers=headers, json={"status": "done"})
                    assert response.status_code == 200 and response.json()["record"]["status"] == "done", response.text
                response = await client.patch(f"/api/records/{ids[1]}", headers=headers, json={"date": "2026-10-22"})
                assert response.status_code == 200, response.text
                assert (await client.delete(f"/api/records/{old_id}", headers=headers)).status_code == 204
                moment = moment.replace(hour=13)
                await push.tick()
                assert len(mine()) == 8, mine()
                assert (await client.patch(f"/api/records/{ids[2]}", headers=headers, json={"status": "open"})).status_code == 200
                result = await client.post("/api/chat", headers=headers, json={"conversation_id": str(uuid4()),
                    "text": "Отметь встречу выполненной", "source": "text", "client_time": moment.isoformat(), "timezone": "UTC"})
                assert result.status_code == 200 and result.json()["kind"] == "completed", result.text
                assert result.json()["records"][0]["status"] == "done"
                # A failed delivery is retried; a success starts a fresh one-hour cooldown.
                assert (await client.patch(f"/api/records/{ids[0]}", headers=headers, json={"status": "open"})).status_code == 200
                failures.add(endpoint)
                await push.tick()
                assert len(mine()) == 9
                failures.clear()
                moment += timedelta(seconds=30)
                await push.tick()
                assert len(mine()) == 10
                await push.tick()
                assert len(mine()) == 10
                # Old events open directly by ID, outside the calendar's recent-day window.
                result = await client.get(f"/api/records/{ids[0]}", headers=headers)
                assert result.status_code == 200, result.text
                async with AsyncSessionLocal() as db:
                    markers = list((await db.execute(select(PushSent).where(PushSent.key.like(f"o:{ids[0]}@%")))).scalars())
                    assert len(markers) == 1
    print("PASS: hourly overdue task/reminder/meeting push; persistent cooldown; old dates; done/deleted/moved stop; retry on failure")


if __name__ == "__main__":
    asyncio.run(main())
