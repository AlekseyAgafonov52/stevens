"""User phrasing and conservative LLM review of incomplete rule matches."""
from datetime import datetime
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost/unused")
from app import nlu
from app.ai.provider import InvalidResponse
from app.ai.schema import Result
from app.owner import Owner
from app.routers import chat
from app.schemas import ChatRequest

NOW = datetime(2026, 10, 25, 10)
FIRST = "Будь добр, помоги мне не забыть: завтра к 11 надо подготовить отчёт 25."
SECOND = "Мне бы завтра в 15 пересечься с Иваном, организуй это как встречу."


class RuleTests(unittest.TestCase):
    def test_monthly_tutor_reminders(self):
        p = nlu.parse("Поставь напоминания на месяц вперед репетитор каждый вторник в 9.00", NOW)
        self.assertEqual((p.intent, p.type, p.text, p.time), ("create", "reminder", "Репетитор", "09:00"))
        self.assertEqual(p.repeat_days, [1])
        self.assertEqual(p.until.isoformat() if p.until else None, "2026-11-24")

    def test_incomplete_math_task_with_relative_reminder(self):
        p = nlu.parse("я вчера не сделал задачку по математике напомни через 2 дня сделать", NOW)
        self.assertEqual((p.intent, p.type, p.text, p.time), ("create", "reminder", "Сделать задачку по математике", None))
        self.assertEqual(p.date.isoformat() if p.date else None, "2026-10-27")

    def test_forgotten_event_does_not_override_reminder_day(self):
        for phrase in ["Я вчера забыл помыть посуду, напомни завтра",
                       "Я забыла вчера помыть посуду, напомни завтра",
                       "Вчера не успел помыть посуду; напомни завтра в 11"]:
            with self.subTest(phrase=phrase):
                p = nlu.parse(phrase, NOW)
                self.assertEqual((p.intent, p.type, p.text), ("create", "reminder", "Помыть посуду"))
                self.assertEqual(p.date.isoformat() if p.date else None, "2026-10-26")
                self.assertEqual(p.time, "11:00" if "в 11" in phrase else None)

    def test_reminder_with_own_action_does_not_inherit_background(self):
        p = nlu.parse("Я вчера забыл помыть посуду, напомни завтра купить молоко", NOW)
        self.assertEqual(p.text, "Купить молоко")
        self.assertEqual(p.date.isoformat() if p.date else None, "2026-10-26")

    def test_past_schedule_is_not_inherited_from_background(self):
        p = nlu.parse("Я забыл помыть посуду вчера в 9, напомни завтра", NOW)
        self.assertEqual(p.text, "Помыть посуду")
        self.assertEqual(p.date.isoformat() if p.date else None, "2026-10-26")
        self.assertIsNone(p.time)

    def test_task_title_and_time(self):
        p = nlu.parse(FIRST, NOW)
        self.assertEqual((p.intent, p.type, p.text, p.time), ("create", "task", "Подготовить отчёт 25", "11:00"))
        self.assertEqual(p.date.isoformat() if p.date else None, "2026-10-26")
        self.assertFalse(nlu.needs_llm_review(p))

    def test_meeting_title(self):
        p = nlu.parse(SECOND, NOW)
        self.assertEqual((p.type, p.text, p.time), ("meeting", "Встреча с Иваном", "15:00"))
        self.assertFalse(nlu.needs_llm_review(p))

    def test_hour_formats_and_ambiguity(self):
        for phrase, time, ambiguous in [("к 11", "11:00", False), ("ко 11", "11:00", False),
                                        ("к 11:30", "11:30", False), ("к 2", "14:00", True),
                                        ("к 2 дня", "14:00", False), ("на 7 утра", "07:00", False)]:
            with self.subTest(phrase=phrase):
                p = nlu.parse("Завтра " + phrase + " подготовить отчёт 25", NOW)
                self.assertEqual((p.time, p.time_ambiguous), (time, ambiguous))
                self.assertNotIn("к 11", p.text or "")

    def test_dates_and_numbered_objects_are_not_hours(self):
        for phrase in ["Подготовить отчёт 25", "Подготовиться к 11 классу", "Подготовить отчёт к 11 ноября"]:
            with self.subTest(phrase=phrase):
                self.assertIsNone(nlu.parse(phrase, NOW).time)

    def test_review_is_limited_to_unclear_supported_creations(self):
        self.assertTrue(nlu.needs_llm_review(nlu.parse("Завтра в 10 сделать что-нибудь по отчёту", NOW)))
        self.assertTrue(nlu.needs_llm_review(nlu.Parse(intent="create", type="task", text="Помоги разобрать это")))
        self.assertFalse(nlu.needs_llm_review(nlu.Parse(intent="delete", text="Помоги удалить")))
        self.assertFalse(nlu.needs_llm_review(nlu.parse("Завтра в 10 купить молоко", NOW)))


class RefinementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = AsyncMock()
        self.ctx = chat.Ctx(owner=Owner(sandbox_id="refine-test"), db=self.db,
                            conv=chat.Conversation(), now=NOW, features={"d2", "d3", "d10"})
        chat._llm_down_until = 0

    def tearDown(self):
        chat._llm_down_until = 0

    async def say(self, text):
        payload = ChatRequest(conversation_id="test", text=text, client_time=NOW.isoformat())
        with patch.object(chat.series, "extend", new=AsyncMock()):
            return await chat.respond(self.ctx, payload)

    def result(self, confidence=0.95):
        return Result.model_validate({"intent": "create", "items": [{"type": "task", "text": "Подготовить отчёт 25",
            "date": "2026-10-26", "time": "11:00"}], "confidence": confidence, "layer": "llm"})

    async def test_clear_request_does_not_call_llm(self):
        with patch.object(chat, "llm_enabled", return_value=True), \
                patch("brain.parse_user_input") as parse, patch.object(chat, "save", new=AsyncMock(return_value={"kind": "created"})):
            self.assertEqual((await self.say(FIRST))["kind"], "created")
        parse.assert_not_called()

    async def test_occurrence_cancellation_respects_disabled_deletion(self):
        with patch.object(chat.features, "on", side_effect=lambda feature: feature != "f12"):
            answer = await self.say("17 ноября занятий не будет")
        self.assertEqual(answer["kind"], "not_understood")
        self.db.commit.assert_not_awaited()

    async def test_forgotten_task_asks_time_for_tomorrow(self):
        with patch.object(chat, "free_times", new=AsyncMock(return_value=[])), \
                patch("brain.parse_user_input") as parse:
            answer = await self.say("Я вчера забыл помыть посуду, напомни завтра")
        self.assertEqual(answer["kind"], "clarify")
        self.assertIsNotNone(self.ctx.conv.pending)
        assert self.ctx.conv.pending is not None
        self.assertEqual(self.ctx.conv.pending.draft["text"], "Помыть посуду")
        self.assertEqual(self.ctx.conv.pending.draft["date"], "2026-10-26")
        self.assertEqual(self.ctx.trace["template"], "clarify_reminder_time")
        parse.assert_not_called()
        self.db.commit.assert_not_awaited()

    async def test_unclear_creation_is_reviewed_but_not_saved(self):
        with patch.object(chat, "llm_enabled", return_value=True), patch("brain.parse_user_input", return_value=self.result()) as parse:
            answer = await self.say("Завтра в 10 сделать что-нибудь по отчёту")
        self.assertEqual(answer["kind"], "confirm")
        self.assertEqual(answer["records"][0]["text"], "Подготовить отчёт 25")
        self.assertTrue(self.ctx.trace["llm_used"])
        parse.assert_called_once()
        self.db.commit.assert_not_awaited()

    async def test_invalid_provider_retains_rules_and_confirmation(self):
        with patch.object(chat, "llm_enabled", return_value=True), \
                patch("brain.parse_user_input", side_effect=InvalidResponse("invalid_parse_schema")):
            answer = await self.say("Завтра в 10 сделать что-нибудь по отчёту")
        self.assertEqual(answer["kind"], "confirm")
        self.assertIn("что-нибудь", answer["records"][0]["text"])
        self.assertFalse(self.ctx.trace["llm_used"])
        self.db.commit.assert_not_awaited()

    async def test_weaker_llm_result_does_not_replace_rules(self):
        with patch.object(chat, "llm_enabled", return_value=True), patch("brain.parse_user_input", return_value=self.result(0.5)):
            answer = await self.say("Завтра в 10 сделать что-нибудь по отчёту")
        self.assertEqual(answer["kind"], "confirm")
        self.assertFalse(self.ctx.trace["llm_used"])
        self.db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
