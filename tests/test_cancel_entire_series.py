"""Whole-series cancellation must propose every future date before any write."""
from datetime import datetime
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost/unused")

from app.ai.contextual import whole_series_cancellation
from app.ai.schema import Result, Target
from app.logic import ai_actions
from app.models import DateKind, Record, TaskStatus, TaskType
from app.owner import Owner
from app.routers import chat
from app.schemas import ChatRequest

NOW = datetime(2026, 10, 28, 18)
PHRASE = "Репетитора больше не будет, убери все занятия"


class EntireSeriesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = AsyncMock()
        self.ctx = chat.Ctx(owner=Owner(sandbox_id="series-cancel"), db=self.db,
                            conv=chat.Conversation(focus=1), now=NOW, features={"d2"})
        self.rows = [self.record(1, "2026-11-04"), self.record(2, "2026-11-11"), self.record(3, "2026-11-18")]
        self.past = self.record(4, "2026-10-21")

    def record(self, rid, day, sid=10):
        return Record(id=rid, sandbox_id="series-cancel", type=TaskType.task, text="Репетитор",
                      date=day, time="17:00", date_kind=DateKind.exact, status=TaskStatus.open,
                      series_id=sid, repeat="2", deleted_at=None, demo=False)

    async def propose(self, seeds=None):
        result = whole_series_cancellation(PHRASE, NOW)
        assert result is not None
        with patch.object(chat, "owner_records", new=AsyncMock(return_value=seeds or self.rows)), \
             patch.object(chat, "owned_record", new=AsyncMock(return_value=self.rows[0])), \
             patch.object(chat.series, "upcoming", new=AsyncMock(return_value=self.rows)) as upcoming:
            answer = await ai_actions.propose(self.ctx, result)
        return answer, upcoming

    async def test_query_expands_series_once_and_waits_for_confirmation(self):
        answer, upcoming = await self.propose()
        self.assertEqual(answer["kind"], "confirm")
        self.assertEqual(answer["total"], 3)
        self.assertIn("все предстоящие", answer["text"])
        upcoming.assert_awaited_once()
        self.assertIsNotNone(self.ctx.conv.pending)
        assert self.ctx.conv.pending is not None
        self.assertEqual(set(self.ctx.conv.pending.draft["ids"]), {1, 2, 3})
        self.assertTrue(all(r.deleted_at is None for r in self.rows))
        self.db.commit.assert_not_awaited()

    async def test_focus_only_seed_still_expands_all_future_dates(self):
        result = Result(intent="delete", layer="llm", confidence=.95, target=Target(ref="focus", series="all"))
        with patch.object(chat, "owned_record", new=AsyncMock(return_value=self.rows[0])), \
             patch.object(chat.series, "upcoming", new=AsyncMock(return_value=self.rows)):
            answer = await ai_actions.propose(self.ctx, result)
        self.assertEqual(answer["total"], 3)

    async def test_confirmation_deletes_future_dates_and_stops_regeneration(self):
        await self.propose()
        query = MagicMock()
        query.scalars.return_value.all.return_value = self.rows
        self.db.execute.return_value = query
        with patch.object(chat, "owner_records", new=AsyncMock(return_value=[])), \
             patch.object(chat, "owned_record", new=AsyncMock(return_value=self.rows[0])), \
             patch.object(chat.series, "extend", new=AsyncMock()), \
             patch.object(chat.series, "set_ended", new=AsyncMock()) as ended:
            answer = await chat.respond(self.ctx, ChatRequest(conversation_id="test", text="Да, верно",
                                                              client_time=NOW.isoformat()))
        self.assertEqual(answer["kind"], "deleted")
        self.assertEqual(answer["total"], 3)
        self.assertTrue(all(r.deleted_at is not None for r in self.rows))
        self.assertIsNone(self.past.deleted_at)
        ended.assert_awaited_once_with(self.db, self.ctx.owner, {10}, True)
        self.assertEqual(set(self.ctx.conv.bulk_deleted), {1, 2, 3})
        self.assertIsNone(self.ctx.conv.pending)

    async def test_rejection_keeps_every_occurrence(self):
        await self.propose()
        with patch.object(chat, "owned_record", new=AsyncMock(return_value=self.rows[0])), \
             patch.object(chat.series, "extend", new=AsyncMock()):
            answer = await chat.respond(self.ctx, ChatRequest(conversation_id="test", text="Нет",
                                                              client_time=NOW.isoformat()))
        self.assertEqual(answer["kind"], "cancelled")
        self.assertTrue(all(r.deleted_at is None for r in self.rows))
        self.assertIsNone(self.ctx.conv.pending)
        self.db.commit.assert_not_awaited()

    async def test_distinct_series_require_choice_before_confirmation(self):
        other = self.record(8, "2026-11-04", sid=20)
        answer, upcoming = await self.propose([*self.rows, other])
        self.assertEqual(answer["kind"], "clarify")
        self.assertEqual(len(answer["records"]), 2)
        upcoming.assert_not_awaited()
        self.db.commit.assert_not_awaited()

    async def test_reported_phrase_routes_without_llm(self):
        payload = ChatRequest(conversation_id="test", text=PHRASE, client_time=NOW.isoformat())
        with patch.object(chat.series, "extend", new=AsyncMock()), \
             patch.object(chat, "owner_records", new=AsyncMock(return_value=self.rows)), \
             patch.object(chat, "owned_record", new=AsyncMock(return_value=self.rows[0])), \
             patch.object(chat.series, "upcoming", new=AsyncMock(return_value=self.rows)), \
             patch.object(chat, "llm_parse", new=AsyncMock(side_effect=AssertionError("LLM not needed"))):
            answer = await chat.respond(self.ctx, payload)
        self.assertEqual(answer["kind"], "confirm")
        self.assertEqual(answer["total"], 3)

    def test_dated_exception_is_not_entire_series_cancellation(self):
        self.assertIsNone(whole_series_cancellation("В среду репетитора не будет, убери задачу", NOW))
        self.assertIsNone(whole_series_cancellation("Репетитора завтра больше не будет, убери все занятия", NOW))


if __name__ == "__main__":
    unittest.main()
