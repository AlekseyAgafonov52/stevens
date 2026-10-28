"""Source-date selection and destination-date retention during a move."""
from datetime import date, datetime
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost/unused")

from app import nlu
from app.ai.rules import parse
from app.ai.schema import Input
from app.models import DateKind, Record, TaskStatus, TaskType
from app.owner import Owner
from app.routers import chat

NOW = datetime(2026, 10, 28, 10)
PHRASES = ["перенеси репетитора завтра на послезавтра",
           "перенеси репетитора с завтрашнего дня по послезавтра"]


class MoveDatesTests(unittest.IsolatedAsyncioTestCase):
    def context(self):
        return chat.Ctx(owner=Owner(sandbox_id="move-dates"), db=AsyncMock(),
                        conv=chat.Conversation(), now=NOW, features=set())

    def record(self, rid, day):
        return Record(id=rid, type=TaskType.reminder, text="Репетитор", date=day,
                      time="17:00", date_kind=DateKind.exact, status=TaskStatus.open,
                      demo=False, deleted_at=None)

    def test_both_phrases_and_explicit_hour(self):
        for phrase in PHRASES:
            for suffix, hour in [("", None), (" в 13:00", "13:00")]:
                with self.subTest(phrase=phrase, suffix=suffix):
                    p = nlu.parse(phrase + suffix, NOW)
                    self.assertEqual((p.intent, p.source, p.date, p.time),
                                     ("move", date(2026, 10, 29), date(2026, 10, 30), hour))
                    self.assertEqual(p.keywords, nlu.parse("перенеси репетитора на послезавтра", NOW).keywords)
                    result = parse(Input(text=phrase + suffix, now=NOW))
                    assert result.target and result.change and result.target.query
                    self.assertEqual(result.target.date, "2026-10-29")
                    self.assertEqual(result.target.query.date, "2026-10-29")
                    self.assertEqual(result.change.date, "2026-10-30")

    def test_weekday_source_and_plain_destination(self):
        p = nlu.parse("перенеси репетитора с пятницы на понедельник", NOW)
        self.assertEqual((p.source, p.date), (date(2026, 10, 30), date(2026, 11, 2)))
        p = nlu.parse("перенеси репетитора на послезавтра", NOW)
        self.assertIsNone(p.source)
        self.assertEqual(p.date, date(2026, 10, 30))

    async def test_move_selects_source_day_and_preserves_existing_hour(self):
        for phrase in PHRASES:
            ctx = self.context()
            ctx.raw = phrase
            first = self.record(1, "2026-10-29")
            other = self.record(2, "2026-10-30")
            with patch.object(chat, "focused", new=AsyncMock(return_value=[])), \
                 patch.object(chat, "find", new=AsyncMock(return_value=[first, other])) as find:
                result = await chat.answer_move(ctx, nlu.parse(phrase, NOW))
            assert find.await_args is not None
            self.assertEqual(find.await_args.args[1].date, date(2026, 10, 29))
            self.assertEqual(result["kind"], "updated")
            self.assertEqual((first.date, first.time), ("2026-10-30", "17:00"))
            self.assertEqual((other.date, other.time), ("2026-10-30", "17:00"))

    async def test_time_reply_uses_destination_retained_in_prompt(self):
        ctx = self.context()
        record = self.record(1, "2026-10-29")
        with patch.object(chat, "day_windows", new=AsyncMock(return_value=[(540, 1260)])):
            await chat.ask_move_time(ctx, record, date(2026, 10, 30))
        assert ctx.conv.pending is not None
        with patch.object(chat, "owned_record", new=AsyncMock(return_value=record)):
            result = await chat.answer_move_when(ctx, ctx.conv.pending, "в 13:00")
        assert result is not None
        self.assertEqual(result["kind"], "updated")
        self.assertEqual((record.date, record.time), ("2026-10-30", "13:00"))

    async def test_no_matching_source_does_not_move_other_day(self):
        ctx = self.context()
        record = self.record(1, "2026-10-30")
        with patch.object(chat, "focused", new=AsyncMock(return_value=[])), \
             patch.object(chat, "find", new=AsyncMock(return_value=[record])):
            result = await chat.answer_move(ctx, nlu.parse(PHRASES[0], NOW))
        self.assertEqual(result["total"], 0)
        self.assertEqual(record.date, "2026-10-30")


if __name__ == "__main__":
    unittest.main()
