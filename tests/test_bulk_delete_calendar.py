"""Exercise confirmation and calendar queries against an isolated SQLite database."""
from datetime import date, datetime, timedelta
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import DateKind, Record, Series, TaskStatus, TaskType
from app.owner import Owner
from app.routers import chat, records
from app.schemas import ChatRequest


class AsyncSessionBridge:
    """Use the real SQL queries without requiring a running PostgreSQL server."""

    def __init__(self, session):
        self.session = session

    async def execute(self, query):
        return self.session.execute(query)

    async def commit(self):
        self.session.commit()

    async def flush(self):
        self.session.flush()

    async def get(self, model, key):
        return self.session.get(model, key)

    def add_all(self, rows):
        self.session.add_all(rows)

    def add(self, row):
        self.session.add(row)

    async def refresh(self, row):
        self.session.refresh(row)


class BulkDeleteCalendarTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.db = AsyncSessionBridge(self.session)
        self.owner = Owner(sandbox_id="bulk-calendar")
        self.ctx = chat.Ctx(owner=self.owner, db=self.db, conv=chat.Conversation(),
                            now=datetime(2026, 10, 26, 10), features={"d2", "d3", "d10"})

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def add_record(self, kind, **values):
        row = self.owner.new_record(type=kind, text="Проверка", date="2026-10-29", time="19:00",
                                    date_kind=DateKind.exact, status=TaskStatus.open, **values)
        self.session.add(row)
        self.session.commit()
        return row

    async def say(self, text, action=None):
        return await chat.respond(self.ctx, ChatRequest(conversation_id="bulk-test", text=text, action=action))

    async def calendar(self):
        result = await records.list_records(from_="2026-10-01", to="2026-11-30",
                                             owner=self.owner, db=self.db)
        return result["records"]

    async def test_text_and_button_confirmation_remove_tasks_and_reminders(self):
        for action in [None, {"id": "confirm_yes"}]:
            with self.subTest(action=action):
                task = self.add_record(TaskType.task)
                reminder = self.add_record(TaskType.reminder)
                other = Record(sandbox_id="another-owner", type=TaskType.task, text="Чужая",
                               date="2026-10-29", date_kind=DateKind.exact)
                self.session.add(other)
                self.session.commit()
                confirmation = await self.say("удали все мои задачи")
                self.assertEqual(confirmation["kind"], "confirm")
                self.assertEqual(confirmation["total"], 2)
                self.assertEqual(len(await self.calendar()), 2)
                deleted = await self.say("да удалить все", action)
                self.assertEqual((deleted["kind"], deleted["total"]), ("deleted", 2))
                self.assertIsNotNone(task.deleted_at)
                self.assertIsNotNone(reminder.deleted_at)
                self.assertIsNone(other.deleted_at)
                self.assertEqual(await self.calendar(), [])
                self.session.expire_all()
                self.assertEqual(await self.calendar(), [])

    async def test_deleted_repeat_stays_empty_when_calendar_extends_horizon(self):
        repeat = Series(sandbox_id=self.owner.sandbox_id, type=TaskType.task, text="Повтор",
                        weekdays="3", filled_until="2027-10-26", ended=False)
        self.session.add(repeat)
        self.session.commit()
        self.add_record(TaskType.task, series_id=repeat.id, repeat="3")
        self.add_record(TaskType.task, series_id=repeat.id, repeat="3")
        await self.say("удали все мои задачи")
        await self.say("да удалить все")
        self.assertTrue(repeat.ended)
        from app import series
        await series.extend(self.db, self.owner, date(2027, 10, 26) + timedelta(days=1))
        self.assertEqual(await chat.owner_records(self.ctx), [])

    async def test_cancel_keeps_calendar_records(self):
        self.add_record(TaskType.task)
        self.add_record(TaskType.reminder)
        await self.say("удали все мои задачи")
        self.assertEqual((await self.say("нет"))["kind"], "cancelled")
        self.assertEqual(len(await self.calendar()), 2)

    async def test_weekday_clarification_creates_month_of_reminders_in_calendar(self):
        first = await self.say("поставь напоминание репетитор по математике каждую неделю 13.00 вперед на месяц")
        self.assertEqual(first["kind"], "clarify")
        self.assertEqual(await self.calendar(), [])
        second = await self.say("каждую среду")
        self.assertEqual(second["kind"], "created")
        saved = await self.calendar()
        self.assertEqual([r["date"] for r in saved],
                         ["2026-10-28", "2026-11-04", "2026-11-11", "2026-11-18", "2026-11-25"])
        self.assertTrue(all(r["text"] == "Репетитор по математике" and r["time"] == "13:00"
                            and r["repeat"] == {"weekdays": [2], "until": "2026-11-25"} for r in saved))

    async def test_period_deletion_keeps_other_occurrences_and_series_active(self):
        repeat = Series(sandbox_id=self.owner.sandbox_id, type=TaskType.task, text="Повтор",
                        weekdays="3", filled_until="2027-10-26", ended=False)
        self.session.add(repeat)
        self.session.commit()
        self.add_record(TaskType.task, series_id=repeat.id, repeat="3")
        self.add_record(TaskType.task, series_id=repeat.id, repeat="3")
        remaining = self.add_record(TaskType.task, series_id=repeat.id, repeat="3")
        remaining.date = "2026-11-05"
        self.session.commit()
        confirmation = await self.say("удали все задачи на 29 октября")
        self.assertEqual(confirmation["total"], 2)
        await self.say("да удалить все")
        self.assertFalse(repeat.ended)
        self.assertEqual([r["id"] for r in await self.calendar()], [remaining.id])

    async def test_restore_returns_deleted_records_to_calendar(self):
        self.add_record(TaskType.task)
        self.add_record(TaskType.reminder)
        await self.say("удали все мои задачи")
        await self.say("да удалить все")
        restored = await self.say("Вернуть все", {"id": "restore_all"})
        self.assertEqual(restored["total"], 2)
        self.assertEqual(len(await self.calendar()), 2)


if __name__ == "__main__":
    unittest.main()
