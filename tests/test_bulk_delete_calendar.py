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

    async def tutor(self, subject="математике"):
        result = await self.say(f"Напомни репетитор по {subject} каждую среду в 13 на месяц")
        self.assertEqual(result["kind"], "created", result)
        return result

    async def test_cancel_next_week_occurrence(self):
        await self.tutor()
        result = await self.say("На следующей неделе занятия не будет")
        self.assertEqual(result["kind"], "deleted", result)
        self.assertEqual(result["records"][0]["date"], "2026-11-04")
        self.assertEqual(len(await self.calendar()), 4)

    async def test_two_series_same_day_require_choice(self):
        await self.tutor()
        await self.tutor("физике")
        result = await self.say("В среду занятия не будет")
        self.assertEqual(result["kind"], "clarify", result)
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(len(await self.calendar()), 10)

    async def test_two_clarifications_preserve_weekly_title(self):
        self.assertEqual((await self.say("Напомни каждую неделю про математику"))["kind"], "clarify")
        self.assertEqual((await self.say("По средам"))["kind"], "clarify")
        result = await self.say("В 13")
        self.assertEqual(result["kind"], "created", result)
        row = result["records"][0]
        self.assertEqual((row["text"], row["time"], row["repeat"]["weekdays"]), ("Математику", "13:00", [2]))

    async def test_correct_created_series_weekday(self):
        await self.tutor()
        result = await self.say("Нет, лучше по пятницам")
        self.assertEqual(result["kind"], "updated", result)
        rows = await self.calendar()
        self.assertTrue(rows)
        self.assertTrue(all(date.fromisoformat(r["date"]).weekday() == 4 and r["time"] == "13:00"
                            and r["repeat"]["until"] == "2026-11-25" for r in rows), rows)

    async def test_elapsed_time_starts_next_week(self):
        self.ctx.now = datetime(2026, 10, 28, 14)
        result = await self.tutor()
        self.assertEqual(result["records"][0]["date"], "2026-11-04")

    async def test_cancel_bulk_tomorrow(self):
        a = self.add_record(TaskType.task)
        b = self.add_record(TaskType.reminder)
        a.date = b.date = "2026-10-27"
        self.session.commit()
        self.assertEqual((await self.say("Удали все задачи на завтра"))["kind"], "confirm")
        self.assertEqual((await self.say("Нет"))["kind"], "cancelled")
        self.assertEqual(len(await self.calendar()), 2)

    async def test_duplicate_confirmation_does_not_delete_new_records(self):
        self.add_record(TaskType.task)
        self.add_record(TaskType.task)
        await self.say("Удали все задачи")
        await self.say("Да, удалить все", {"id": "confirm_yes"})
        new = self.add_record(TaskType.task)
        result = await self.say("Да, удалить все", {"id": "confirm_yes"})
        self.assertIsNone(new.deleted_at, result)
        self.assertEqual([r["id"] for r in await self.calendar()], [new.id])

    async def test_deleted_occurrence_stays_deleted_after_reloads(self):
        await self.tutor()
        result = await self.say("11 ноября занятий не будет")
        self.assertEqual(result["kind"], "deleted", result)
        deleted_id = result["records"][0]["id"]
        for _ in range(3):
            self.session.expire_all()
            self.assertNotIn(deleted_id, [r["id"] for r in await self.calendar()])

    async def test_restore_series_reenables_extension(self):
        await self.say("Напомни репетитор каждую среду в 13")
        await self.say("Удали репетитора вообще")
        repeat = self.session.query(Series).one()
        self.assertTrue(repeat.ended)
        await self.say("Вернуть все", {"id": "restore_all"})
        self.assertFalse(repeat.ended)
        from app import series
        old_edge = repeat.filled_until
        await series.extend(self.db, self.owner, date(2027, 10, 26))
        self.assertGreater(repeat.filled_until, old_edge)

    async def test_series_delete_reply_selects_named_date(self):
        await self.tutor()
        self.assertEqual((await self.say("Удали репетитора"))["kind"], "clarify")
        result = await self.say("Только 11 ноября")
        self.assertEqual(result["kind"], "deleted", result)
        self.assertEqual(result["records"][0]["date"], "2026-11-11")

    async def test_period_with_multiple_occurrences_offers_each_date(self):
        created = await self.say("Напомни репетитор по средам и пятницам в 13 на месяц")
        self.assertEqual(created["kind"], "created", created)
        count = len(await self.calendar())
        result = await self.say("На следующей неделе занятия не будет")
        self.assertEqual(result["kind"], "clarify", result)
        self.assertEqual({r["date"] for r in result["records"]}, {"2026-11-04", "2026-11-06"})
        chosen = result["buttons"][1]["send"]["action"]
        deleted = await self.say("Выбрать", chosen)
        self.assertEqual(deleted["records"][0]["date"], "2026-11-06")
        self.assertEqual(len(await self.calendar()), count - 1)

    async def test_named_date_outside_series_does_not_delete_nearest(self):
        await self.tutor()
        await self.say("Удали репетитора")
        result = await self.say("Только 12 ноября")
        self.assertEqual((result["kind"], result["total"]), ("found", 0))
        self.assertEqual(len(await self.calendar()), 5)

    async def test_corrected_weekday_persists_after_calendar_reload(self):
        await self.tutor()
        await self.say("Нет, лучше по пятницам")
        self.session.expire_all()
        self.assertEqual(self.session.query(Series).one().weekdays, "4")
        self.assertEqual({r["date"] for r in await self.calendar()},
                         {"2026-10-30", "2026-11-06", "2026-11-13", "2026-11-20"})


if __name__ == "__main__":
    unittest.main()
