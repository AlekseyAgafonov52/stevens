"""A broad deletion request must not silently select the focused record."""
from datetime import datetime
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost/unused")

from app import nlu
from app.models import DateKind, Record, TaskStatus, TaskType
from app.owner import Owner
from app.routers import chat

NOW = datetime(2026, 10, 28, 10)


class AmbiguousDeleteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = AsyncMock()
        self.ctx = chat.Ctx(owner=Owner(sandbox_id="ambiguous-delete"), db=self.db,
                            conv=chat.Conversation(focus=2), now=NOW, features={"d2"})
        self.rows = [Record(id=rid, type=TaskType.task, text=title, date="2026-10-29", time=hour,
                            date_kind=DateKind.exact, status=TaskStatus.open, demo=False, deleted_at=None)
                     for rid, title, hour in [(1, "Репетитора по математике", "14:00"),
                                              (2, "Репетитора по физике", "17:00")]]

    async def answer(self, phrase):
        self.ctx.raw = phrase
        # Keep the actual keyword ranking and deletion handlers; only DB reads are replaced.
        with patch.object(chat, "owner_records", new=AsyncMock(return_value=self.rows)), \
             patch.object(chat, "owned_record", new=AsyncMock(return_value=self.rows[1])):
            return await chat.answer_delete(self.ctx, nlu.parse(phrase, NOW))

    async def test_two_subjects_require_choice_even_with_recent_focus(self):
        result = await self.answer("Удали репетитора завтра")
        self.assertEqual(result["kind"], "clarify")
        self.assertTrue(result["awaiting_reply"])
        self.assertEqual({r["id"] for r in result["records"]}, {1, 2})
        self.assertEqual(self.ctx.conv.choices, {"action": "delete", "ids": [1, 2]})
        self.assertTrue(all(r.deleted_at is None for r in self.rows))
        self.db.commit.assert_not_awaited()
        self.assertIs(chat.pick_choice("по математике", self.rows, NOW), self.rows[0])
        self.assertIs(chat.pick_choice("вторую", self.rows, NOW), self.rows[1])

    async def test_specific_subject_overrides_recent_focus(self):
        result = await self.answer("Удали репетитора по математике завтра")
        self.assertEqual(result["kind"], "deleted")
        self.assertIsNotNone(self.rows[0].deleted_at)
        self.assertIsNone(self.rows[1].deleted_at)

    async def test_explicit_hour_selects_only_matching_record(self):
        result = await self.answer("Удали репетитора завтра в 14:00")
        self.assertEqual(result["kind"], "deleted")
        self.assertIsNotNone(self.rows[0].deleted_at)
        self.assertIsNone(self.rows[1].deleted_at)

    async def test_nonexistent_hour_does_not_fall_back_to_other_records(self):
        result = await self.answer("Удали репетитора завтра в 16:00")
        self.assertEqual(result["total"], 0)
        self.assertTrue(all(r.deleted_at is None for r in self.rows))
        self.db.commit.assert_not_awaited()

    async def test_pronoun_still_selects_focused_record(self):
        result = await self.answer("Удали её")
        self.assertEqual(result["kind"], "deleted")
        self.assertIsNone(self.rows[0].deleted_at)
        self.assertIsNotNone(self.rows[1].deleted_at)

    async def test_same_title_independent_events_still_require_choice(self):
        for row in self.rows:
            row.text = "Репетитор"
        result = await self.answer("Удали репетитора завтра")
        self.assertEqual(result["kind"], "clarify")
        self.db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
