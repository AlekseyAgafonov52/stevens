"""Регрессии сохранности данных и push. Только на отдельной тестовой БД."""
import asyncio
import base64
from datetime import date, datetime, timedelta, timezone
import json
import os
import sys
from unittest.mock import patch
import uuid

sys.path.insert(0, os.getcwd())
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import func, select

from app import push, series
from app.database import AsyncSessionLocal
from app.logic.push_targets import allowed_endpoint
from app.main import app
from app.models import Account, PushSent, PushSnooze, PushSubscription, Record, Series, TaskType, DateKind
from app.owner import Owner


async def paused():
    await asyncio.Event().wait()


async def main():
    push.loop = paused
    failures = []

    def check(name, ok):
        print("OK  " if ok else "FAIL", name)
        if not ok:
            failures.append(name)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as c:
            reg = (await c.post("/api/auth/register", json={"login": "secure" + uuid.uuid4().hex[:10], "password": "test-password"})).json()
            h = {"Authorization": "Bearer " + reg["token"]}
            owner = Owner(account=Account(id=reg["user"]["id"]))
            async def export():
                return (await c.get("/api/records/export", headers=h)).json()
            async def apply(rows):
                return await c.post("/api/records/import/apply", headers=h, json={"records": rows})
            new = {"type": "meeting", "text": "test meeting", "date": "2026-11-01", "time": "15:00", "date_kind": "exact"}
            preview = await c.post("/api/records/import/preview", headers=h, json={"records": [new]})
            check("preview не пишет данные", preview.json() == {"add": 1, "update": 0, "delete": 0, "errors": []}
                  and not (await export())["records"])
            done = await apply([new])
            check("атомарное добавление", done.status_code == 200 and done.json()["add"] == 1)
            undo_id = done.json()["undo_id"]
            rows = (await export())["records"]
            original = rows[0]
            bad = await apply([{**original, "text": "must rollback"}, {**new, "text": "invalid", "time": None}])
            check("ошибка строки отменяет весь пакет", bad.status_code == 422 and (await export())["records"] == rows)
            for rid in ([], {}, 10 ** 70, True):
                r = await apply([{**new, "id": rid}])
                check("неверный id не дает 500: " + str(type(rid)), r.status_code == 422)
            check("пустой импорт не удаляет данные", (await apply([])).status_code == 422 and (await export())["records"] == rows)
            # Сбой БД после начала записи не должен оставить уже измененный текст.
            with patch("app.routers.imports.log_import", side_effect=RuntimeError("simulated storage error")):
                failed = await apply([{**original, "text": "must also rollback"}])
            check("отказ перед commit откатывает запись", failed.status_code == 500 and (await export())["records"] == rows)
            stranger = (await c.post("/api/auth/register", json={"login": "foreign" + uuid.uuid4().hex[:10], "password": "test-password"})).json()
            foreign = await c.post("/api/records/import/undo", headers={"Authorization": "Bearer " + stranger["token"]}, json={"undo_id": undo_id})
            check("чужой владелец не отменяет импорт", foreign.status_code == 404)
            undone = await c.post("/api/records/import/undo", headers=h, json={"undo_id": undo_id})
            check("отмена импорта на 2 часа", undone.status_code == 200 and undone.json() == {"add": 1, "update": 0, "delete": 0}
                  and not (await export())["records"])
            check("повторная отмена невозможна", (await c.post("/api/records/import/undo", headers=h, json={"undo_id": undo_id})).status_code == 404)
            created = await apply([new])
            row = (await export())["records"][0]
            await c.patch(f"/api/records/{row['id']}", headers=h, json={"text": "later edit"})
            conflict = await c.post("/api/records/import/undo", headers=h, json={"undo_id": created.json()["undo_id"]})
            check("undo не затирает позднюю правку", conflict.status_code == 422 and (await export())["records"][0]["text"] == "later edit")
            # Основной диалог по v1.6 без скрытых legacy-заголовков.
            conversation = str(uuid.uuid4())
            async def say(text):
                return (await c.post("/api/chat", headers=h, json={"conversation_id": conversation, "text": text,
                    "source": "voice", "client_time": "2026-10-21T10:00:00+03:00", "timezone": "Europe/Moscow"})).json()
            question = await say("Поставь встречу с дизайнером завтра")
            meeting = await say("в 15")
            moved = await say("перенеси её на пятницу в 16")
            check("создание → уточнение → перенос без legacy-заголовка", question["kind"] == "clarify"
                  and meeting["kind"] == "created" and any(b["send"].get("action", {}).get("id") == "undo" for b in meeting["buttons"])
                  and moved["kind"] == "updated" and moved["records"][0]["date"] == "2026-10-23"
                  and moved["records"][0]["time"] == "16:00")
            reminder_question = await say("напоминание: оплатить интернет")
            reminder = await say("завтра в 9")
            check("префикс напоминания из v1.6", reminder_question["kind"] == "clarify" and reminder["kind"] == "created"
                  and reminder["records"][0]["type"] == "reminder")
            # Конечная серия продлевается только до until; повторный вызов не создает дублей.
            async with AsyncSessionLocal() as db:
                draft = {"type": "meeting", "text": "long series", "date": "2026-10-24", "time": "12:00",
                         "repeat": {"days": [0, 1, 2, 3, 4, 5, 6], "until": "2028-10-24"}}
                s, _ = await series.create(db, owner, draft, date(2026, 10, 24))
                assert s is not None, "Expected a nonempty series"
                sid = s.id
                await series.extend(db, owner, date(2028, 1, 1))
                await db.refresh(s)
                check("конечная серия продлена до until", s.filled_until == "2028-10-24")
                await series.extend(db, owner, date(2028, 2, 1))
                total, days = (await db.execute(select(func.count(), func.count(func.distinct(Record.date)))
                                               .where(Record.series_id == sid))).one()
                check("продление без дублей", total == days)
                invalid = {**draft, "time": None}
                try:
                    await series.create(db, owner, invalid, date(2026, 10, 24))
                    rejected = False
                except ValueError:
                    rejected = True
                check("встреча серии требует время", rejected)
            # SSRF и неверный JSON: endpoint проверяется до SQL/сети.
            for endpoint in ("https://127.0.0.1/a", "https://169.254.169.254/a", "https://fcm.googleapis.com.evil.invalid/a",
                             "https://fcm.googleapis.com:444/a", "https://user@fcm.googleapis.com/a"):
                check("push отклоняет опасный URL: " + endpoint, not allowed_endpoint(endpoint))
            for keys in ([1], "bad", True, {"p256dh": "x", "auth": "y"}):
                r = await c.post("/api/push/subscribe", headers=h, json={"endpoint": "https://fcm.googleapis.com/a", "keys": keys})
                check("неверные push keys возвращают 422", r.status_code == 422)
            raw = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
            keys = {"p256dh": base64.urlsafe_b64encode(raw).decode().rstrip("="),
                    "auth": base64.urlsafe_b64encode(b"0123456789abcdef").decode().rstrip("=")}
            endpoint = "https://fcm.googleapis.com/audit/" + uuid.uuid4().hex
            r = await c.post("/api/push/subscribe", headers=h, json={"endpoint": endpoint, "keys": keys, "timezone": "UTC"})
            check("валидная подписка", r.status_code == 204)
            forged = {**keys, "auth": base64.urlsafe_b64encode(b"fedcba9876543210").decode().rstrip("=")}
            foreign_sub = await c.post("/api/push/subscribe", headers={"Authorization": "Bearer " + stranger["token"]},
                json={"endpoint": endpoint, "keys": forged, "timezone": "UTC"})
            check("одного endpoint недостаточно для подмены ключей", foreign_sub.status_code == 422)
            async with AsyncSessionLocal() as db:
                sub = (await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))).scalar_one()
                now = datetime.now(timezone.utc)
                task = owner.new_record(type=TaskType.reminder, text="retry delivery", date=now.date().isoformat(),
                                        time=now.strftime("%H:%M"), date_kind=DateKind.exact, demo=False)
                db.add(task); await db.commit(); await db.refresh(task)
                rid = task.id
                key = f"{push.record_key(task)}:s{sub.id}"
            with patch("app.push.send", return_value=None):
                await push.tick()
            async with AsyncSessionLocal() as db:
                check("ошибка доставки не считается успехом", await db.get(PushSent, key) is None)
            with patch("app.push.send", return_value=True) as sender:
                await push.tick(); await push.tick()
                deliveries = [call for call in sender.call_args_list if json.loads(call.args[1])["record_id"] == rid]
                check("повтор доставки затем единственная отправка", len(deliveries) == 1)
            await c.post("/api/push/snooze", json={"endpoint": endpoint, "record_id": rid})
            async with AsyncSessionLocal() as db:
                z = (await db.execute(select(PushSnooze).where(PushSnooze.record_id == rid))).scalar_one()
                z.at = datetime.now(timezone.utc) - timedelta(seconds=1); await db.commit()
            with patch("app.push.send", return_value=None):
                await push.tick()
            async with AsyncSessionLocal() as db:
                check("snooze остается после сбоя", (await db.execute(select(PushSnooze).where(PushSnooze.record_id == rid))).scalar_one_or_none() is not None)
    print("fails:", len(failures))
    return bool(failures)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
