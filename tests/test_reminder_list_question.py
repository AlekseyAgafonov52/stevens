"""Reminder list questions must never enter the creation/clarification flow."""
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
from app.owner import Owner
from app.routers import chat
from app.schemas import ChatRequest

NOW = datetime(2026, 10, 29, 10)


class ReminderQuestionTests(unittest.IsolatedAsyncioTestCase):
    def test_list_questions_with_optional_words(self):
        for text, kind in [("какие есть напоминания на завтра", "reminder"),
                           ("Какие есть у меня напоминания на завтра?", "reminder"),
                           ("Какие у меня есть напоминания на завтра", "reminder"),
                           ("какие ещё есть напоминания на завтра", "reminder"),
                           ("какие есть встречи на завтра", "meeting"),
                           ("какие есть задачи на завтра", "task")]:
            with self.subTest(text=text):
                p = nlu.parse(text, NOW)
                self.assertEqual((p.intent, p.filter_type), ("list", kind))
                assert p.period is not None
                self.assertEqual((p.period.start, p.period.end), (date(2026, 10, 30), date(2026, 10, 30)))
                result = parse(Input(text=text, now=NOW))
                self.assertEqual(result.intent, "list")
                self.assertEqual(result.items, [])

    async def test_reported_question_routes_to_list_without_creating_draft(self):
        db = AsyncMock()
        ctx = chat.Ctx(owner=Owner(sandbox_id="question-list"), db=db,
                       conv=chat.Conversation(), now=NOW, features=set())
        payload = ChatRequest(conversation_id="test", text="какие есть напоминания на завтра",
                              client_time=NOW.isoformat())
        with patch.object(chat.series, "extend", new=AsyncMock()), \
             patch.object(chat, "answer_list", new=AsyncMock(return_value={"kind": "found"})) as listing, \
             patch.object(chat, "process_draft", new=AsyncMock()) as creation, \
             patch.object(chat, "llm_parse", new=AsyncMock()) as llm:
            answer = await chat.respond(ctx, payload)
        self.assertEqual(answer["kind"], "found")
        listing.assert_awaited_once()
        creation.assert_not_awaited()
        llm.assert_not_awaited()
        self.assertIsNone(ctx.conv.pending)
        db.commit.assert_not_awaited()

    def test_explicit_creation_with_question_in_title_still_creates(self):
        p = nlu.parse("Напомни завтра в 9 проверить какие есть задачи", NOW)
        self.assertEqual(p.intent, "create")
        self.assertEqual(p.time, "09:00")


if __name__ == "__main__":
    unittest.main()
