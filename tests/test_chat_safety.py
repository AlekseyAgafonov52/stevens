"""Chat edge cases without a database or external services."""
from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import nlu
from app.models import Record, TaskType
from app.owner import Owner
from app.routers import chat


class ChatSafetyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = AsyncMock()
        self.ctx = chat.Ctx(
            owner=Owner(sandbox_id="chat-safety"), db=self.db,
            conv=chat.Conversation(), now=datetime(2026, 10, 24, 10), features=set(),
        )

    async def test_time_boundaries(self):
        base = {"type": "task", "text": "test", "date": "2026-10-24",
                "date_kind": "exact", "end_time": None}
        cases = [
            ({"time": None}, "created"),
            ({"time": "09:00"}, "clarify"),
            ({"time": "10:00"}, "clarify"),
            ({"time": "11:00"}, "created"),
            ({"type": "busy", "time": "09:00", "end_time": "18:00", "busy_ok": True}, "created"),
            ({"type": "busy", "time": "08:00", "end_time": "09:00", "busy_ok": True}, "clarify"),
        ]
        with patch.object(chat, "free_times", new=AsyncMock(return_value=[])), \
                patch.object(chat, "save", new=AsyncMock(return_value={"kind": "created"})):
            for values, expected in cases:
                with self.subTest(values=values):
                    result = await chat.process_draft(self.ctx, {**base, **values})
                    self.assertEqual(result["kind"], expected)

    async def test_missing_repeat_end_asks_instead_of_crashing(self):
        draft = {"type": "busy", "text": "work", "date": "2026-10-24", "time": "11:00",
                 "end_time": None, "date_kind": "exact", "repeat": {"days": [5]}}
        result = await chat.process_draft(self.ctx, draft)
        self.assertEqual(result["kind"], "clarify")
        self.assertEqual(self.ctx.trace["template"], "clarify_busy_end")

    async def test_missing_reminder_interval_never_writes(self):
        result = await chat.answer_remind_before(self.ctx, nlu.Parse())
        self.assertEqual(result["kind"], "not_understood")
        self.db.commit.assert_not_awaited()

    async def test_series_action_on_regular_record_never_writes(self):
        record = Record(id=1, type=TaskType.task, text="test", series_id=None)
        for action in (chat.delete_series, chat.undo_series):
            result = await action(self.ctx, record)
            self.assertEqual(result["kind"], "not_understood")
        self.db.commit.assert_not_awaited()

    async def test_missing_stored_question_is_reasked(self):
        result = chat.hold_reask(self.ctx, chat.Pending("draft", {"text": "test"}))
        self.assertEqual(result["kind"], "clarify")
        self.assertTrue(result["awaiting_reply"])

    async def test_empty_move_group_returns_response(self):
        for day in (self.ctx.today, self.ctx.today - timedelta(days=1)):
            result = await chat.plan_move_all(self.ctx, [], day)
            self.assertEqual(result["kind"], "cancelled")
        self.db.commit.assert_not_awaited()

    async def test_edit_without_type_never_partially_writes(self):
        record = Record(id=1, type=None, text="original")
        result = await chat.edit_one(self.ctx, record, {"text": "changed"})
        self.assertEqual(result["kind"], "not_understood")
        self.assertEqual(record.text, "original")
        self.db.commit.assert_not_awaited()

    def test_nullable_type_does_not_become_task(self):
        self.assertIsNone(chat.type_forms([Record(type=None)]))


if __name__ == "__main__":
    unittest.main()
