"""Evening overdue digest over a real database: once a day, once per record, one device."""
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
from app import push
from app.database import AsyncSessionLocal
from app.main import app
from app.models import DateKind, PushSubscription, Record, TaskStatus, TaskType


async def idle():
    await asyncio.Event().wait()


async def main():
    moment = datetime(2026, 10, 21, 18, 59, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

    sent = []
    failures = set()

    mine = set()

    def send(sub, data, key):
        if sub.endpoint in mine:  # в общей тестовой БД бывают подписки других тестов
            sent.append((sub.endpoint, json.loads(data)))
        return None if sub.endpoint in failures else True

    with patch.object(push, "loop", idle), patch.object(push, "send", send), patch.object(push, "datetime", Clock):
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                auth = (await client.post("/api/auth/register", json={"login": "dg" + uuid4().hex[:12], "password": "test-password"})).json()
                account = auth["user"]["id"]
                headers = {"Authorization": "Bearer " + auth["token"]}
                # Один ноутбук, два адреса сайта — две подписки; свежая та, где человек был последним
                laptop = "https://fcm.googleapis.com/digest/" + uuid4().hex
                tailnet = "https://fcm.googleapis.com/digest/" + uuid4().hex
                mine.update({laptop, tailnet})
                async with AsyncSessionLocal() as db:
                    db.add(PushSubscription(account_id=account, endpoint=laptop, p256dh="t", auth="t", timezone="UTC",
                                            seen_at=moment - timedelta(hours=5)))
                    db.add(PushSubscription(account_id=account, endpoint=tailnet, p256dh="t", auth="t", timezone="UTC",
                                            seen_at=moment - timedelta(hours=1)))
                    rows = [Record(account_id=account, type=kind, text=kind.value, date="2026-10-21", time="10:00",
                                   date_kind=DateKind.exact, status=None if kind == TaskType.meeting else TaskStatus.open)
                            for kind in (TaskType.task, TaskType.reminder, TaskType.meeting)]
                    done = Record(account_id=account, type=TaskType.task, text="done", date="2026-10-21", time="09:00",
                                  date_kind=DateKind.exact, status=TaskStatus.done)
                    later = Record(account_id=account, type=TaskType.task, text="later", date="2026-10-21", time="22:00",
                                   date_kind=DateKind.exact, status=TaskStatus.open)
                    ancient = Record(account_id=account, type=TaskType.task, text="ancient", date="2026-10-01", time="10:00",
                                     date_kind=DateKind.exact, status=TaskStatus.open)
                    db.add_all([*rows, done, later, ancient])
                    db.add_all([Record(account_id=account, type=kind, text="ignored", date="2026-10-20", time="10:00",
                                       date_kind=DateKind.exact, demo=kind == TaskType.task)
                                for kind in (TaskType.task, TaskType.busy, TaskType.note)])
                    await db.commit()
                    ids = [r.id for r in rows]
                    later_id = later.id
                await push.tick()
                assert sent == [], sent  # до 19:00 молчим
                moment = moment.replace(hour=19, minute=0)
                await push.tick()
                assert len(sent) == 1, sent
                endpoint, data = sent[0]
                assert endpoint == tailnet and data["digest"] and data["record_ids"] == ids, sent
                assert data["title"] == "3 дела остались без отметки", data
                # Тот же вечер — больше не шлём
                moment += timedelta(hours=2)
                await push.tick()
                assert len(sent) == 1, sent
                # Следующий вечер: старые дела уже были в сводке, новое просроченное — да; перенесённое — снова
                response = await client.patch(f"/api/records/{ids[1]}", headers=headers, json={"date": "2026-10-22"})
                assert response.status_code == 200, response.text
                moment = datetime(2026, 10, 22, 19, 0, tzinfo=timezone.utc)
                await push.tick()
                assert len(sent) == 2 and sent[1][1]["record_ids"] == [later_id, ids[1]], sent
                # Свежее устройство не приняло — сводка уходит на следующее, а не теряется
                async with AsyncSessionLocal() as db:
                    db.add(Record(account_id=account, type=TaskType.task, text="new", date="2026-10-23", time="08:00",
                                  date_kind=DateKind.exact, status=TaskStatus.open))
                    await db.commit()
                failures.add(tailnet)
                moment = datetime(2026, 10, 23, 19, 0, tzinfo=timezone.utc)
                await push.tick()
                assert [e for e, _ in sent[2:]] == [tailnet, laptop], sent
                await push.tick()
                assert len(sent) == 4, sent
    print("PASS: evening digest at 19:00; once per day and per record; moved records return; newest device with fallback")


if __name__ == "__main__":
    asyncio.run(main())
