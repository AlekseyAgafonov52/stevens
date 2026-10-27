"""Evening overdue digest policy without a database or network."""
from datetime import datetime, timezone
import json
import unittest
from zoneinfo import ZoneInfo

from app import push
from app.models import DateKind, Record, TaskStatus, TaskType


class OverdueDigestTests(unittest.TestCase):
    def record(self, kind=TaskType.task, **values):
        fields = dict(id=1, type=kind, text="Проверка", date="2026-10-21", time="10:00",
                      date_kind=DateKind.exact, status=TaskStatus.open, deleted_at=None, demo=False)
        return Record(**{**fields, **values})

    def test_task_reminder_and_meeting_are_overdue_after_their_time(self):
        for kind in (TaskType.task, TaskType.reminder, TaskType.meeting):
            record = self.record(kind)
            self.assertFalse(push.digest_due(record, timezone.utc, datetime(2026, 10, 21, 9, 59, tzinfo=timezone.utc)))
            self.assertTrue(push.digest_due(record, timezone.utc, datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)))

    def test_done_deleted_demo_undated_notes_and_busy_are_never_overdue(self):
        now = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
        for record in (self.record(status=TaskStatus.done), self.record(deleted_at=now), self.record(demo=True),
                       self.record(date=None), self.record(TaskType.note), self.record(TaskType.busy)):
            self.assertFalse(push.digest_due(record, timezone.utc, now))

    def test_date_without_time_lasts_until_local_midnight(self):
        tz = ZoneInfo("Europe/Moscow")
        record = self.record(time=None)
        self.assertFalse(push.digest_due(record, tz, datetime(2026, 10, 21, 23, 59, tzinfo=tz)))
        self.assertTrue(push.digest_due(record, tz, datetime(2026, 10, 22, 0, 0, tzinfo=tz)))

    def test_meeting_with_end_time_is_overdue_after_it_ends(self):
        record = self.record(TaskType.meeting, end_time="12:00")
        self.assertFalse(push.digest_due(record, timezone.utc, datetime(2026, 10, 21, 11, 59, tzinfo=timezone.utc)))
        self.assertTrue(push.digest_due(record, timezone.utc, datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)))

    def test_moving_a_record_makes_it_eligible_again(self):
        self.assertNotEqual(push.digest_key(self.record()), push.digest_key(self.record(date="2026-10-22")))

    def test_digest_payload_names_the_records(self):
        rows = [self.record(id=i, text=f"Дело {i}") for i in range(1, 6)]
        data = json.loads(push.digest_payload(rows[:2]))
        self.assertEqual(data["title"], "2 дела остались без отметки")
        self.assertEqual(data["body"], "Дело 1, Дело 2")
        self.assertEqual(data["record_ids"], [1, 2])
        self.assertTrue(data["digest"])
        data = json.loads(push.digest_payload(rows))
        self.assertEqual(data["title"], "5 дел осталось без отметки")
        self.assertEqual(data["body"], "Дело 1, Дело 2, Дело 3 и ещё 2")
        self.assertEqual(json.loads(push.digest_payload(rows[:1]))["title"], "1 дело осталось без отметки")

    def test_regular_payload_has_no_overdue_text(self):
        data = json.loads(push.payload(self.record(TaskType.meeting)))
        self.assertNotIn("overdue", data)
        self.assertIn("встреча", data["body"])


if __name__ == "__main__":
    unittest.main()
