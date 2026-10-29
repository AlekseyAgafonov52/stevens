"""Draft subject clarification must preserve scheduling fields, without a DB."""
from datetime import datetime
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost/unused")

from app import nlu
from app.owner import Owner
from app.routers import chat
from app.schemas import ChatRequest

NOW = datetime.fromisoformat("2026-10-28T10:00:00+03:00")


class MissingSubjectTests(unittest.IsolatedAsyncioTestCase):
    async def test_subject_reply_preserves_day_and_overrides_only_explicit_time(self):
        for raw, expected_time in [("позвонить маме в 13.00", "13:00"),
                                   ("позвонить маме", "11:00")]:
            with self.subTest(raw=raw):
                db = AsyncMock()
                ctx = chat.Ctx(owner=Owner(sandbox_id="missing-subject"), db=db,
                               conv=chat.Conversation(), now=NOW.replace(tzinfo=None), features=set())
                draft = chat.draft_from(nlu.parse("Поставь напоминание на завтра в 11.00", ctx.now), ctx.today)
                self.assertFalse(draft["text"])
                answer = await chat.process_draft(ctx, draft)
                self.assertEqual(answer["kind"], "clarify")
                self.assertTrue(answer["awaiting_reply"])
                self.assertIsNotNone(ctx.conv.pending)
                payload = ChatRequest(conversation_id="test", text=raw, client_time=NOW.isoformat())
                with patch("app.routers.chat.series.extend", new=AsyncMock()), \
                     patch("app.routers.chat.process_draft", new=AsyncMock(return_value={"kind": "captured"})) as process:
                    answer = await chat.respond(ctx, payload)
                self.assertEqual(answer["kind"], "captured")
                assert process.await_args is not None
                merged = process.await_args.args[1]
                self.assertEqual(merged["date"], "2026-10-29")
                self.assertEqual(merged["time"], expected_time)
                self.assertEqual(merged["type"], "reminder")
                self.assertEqual(merged["text"].lower(), "позвонить маме")
                db.commit.assert_not_awaited()

    def test_other_commands_are_not_subject_replies(self):
        pending = chat.Pending("draft", {"type": "reminder", "text": "", "date": "2026-10-29", "time": "11:00"})
        for raw in ["поставь задачу купить хлеб завтра", "что у меня завтра?", "отмени", "спасибо", "в 13.00"]:
            with self.subTest(raw=raw):
                self.assertFalse(chat.answers_subject(pending, raw, nlu.parse(raw, NOW)))


if __name__ == "__main__":
    unittest.main()
