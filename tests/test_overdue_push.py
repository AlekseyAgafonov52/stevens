"""Hourly overdue push policy without a database or network."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from zoneinfo import ZoneInfo

from app import push
from app.models import DateKind, Record, TaskStatus, TaskType


class OverduePolicyTests(unittest.TestCase):
    def record(self, kind=TaskType.task, **values):
        fields = dict(id=1, type=kind, text="Проверка", date="2026-10-21", time="10:00",
                      date_kind=DateKind.exact, status=TaskStatus.open, deleted_at=None, demo=False)
        return Record(**{**fields, **values})

    def test_first_repeat_is_after_one_hour_for_all_three_event_types(self):
        for kind in (TaskType.task, TaskType.reminder, TaskType.meeting):
            record = self.record(kind)
            self.assertFalse(push.overdue_due(record, timezone.utc, datetime(2026, 10, 21, 10, 59, 59, tzinfo=timezone.utc)))
            self.assertTrue(push.overdue_due(record, timezone.utc, datetime(2026, 10, 21, 11, tzinfo=timezone.utc)))

    def test_hour_is_measured_from_last_success_not_wall_clock_boundary(self):
        previous = datetime(2026, 10, 21, 11, 59, tzinfo=timezone.utc)
        self.assertFalse(push.overdue_due(self.record(), timezone.utc, previous + timedelta(minutes=1), previous))
        self.assertTrue(push.overdue_due(self.record(), timezone.utc, previous + timedelta(hours=1), previous))

    def test_completed_deleted_demo_and_non_events_do_not_repeat(self):
        cases = [self.record(status=TaskStatus.done), self.record(deleted_at=datetime.now(timezone.utc)),
                 self.record(demo=True), self.record(TaskType.note), self.record(TaskType.busy), self.record(date=None)]
        for record in cases:
            with self.subTest(type=record.type):
                self.assertFalse(push.overdue_due(record, timezone.utc, datetime(2026, 10, 26, 12, tzinfo=timezone.utc)))

    def test_date_without_time_ends_at_next_local_midnight(self):
        record = self.record(time=None)
        tz = ZoneInfo("Europe/Moscow")
        self.assertEqual(push.due_at(record, tz), datetime(2026, 10, 22, tzinfo=tz))
        self.assertFalse(push.overdue_due(record, tz, datetime(2026, 10, 21, 23, 59, tzinfo=tz)))
        self.assertTrue(push.overdue_due(record, tz, datetime(2026, 10, 22, 1, tzinfo=tz)))

    def test_meeting_interval_and_overnight_end(self):
        record = self.record(TaskType.meeting, time="23:00", end_time="01:00")
        self.assertEqual(push.due_at(record, timezone.utc), datetime(2026, 10, 22, 1, tzinfo=timezone.utc))
        self.assertFalse(push.overdue_due(record, timezone.utc, datetime(2026, 10, 22, 1, 59, tzinfo=timezone.utc)))

    def test_invalid_schedule_does_not_break_queue(self):
        for changes in [{"date": "2026-02-30"}, {"time": "25:00"}, {"end_time": "bad", "type": TaskType.meeting}]:
            self.assertIsNone(push.due_at(self.record(**changes), timezone.utc))

    def test_overdue_payload_does_not_say_meeting_is_in_fifteen_minutes(self):
        data = json.loads(push.payload(self.record(TaskType.meeting), overdue=True))
        self.assertTrue(data["overdue"])
        self.assertNotIn("Через", data["body"])
        self.assertIn("выполненным", data["body"])
        self.assertNotEqual(push.overdue_key(self.record(), 1), push.overdue_key(self.record(), 2))


if __name__ == "__main__":
    unittest.main()
