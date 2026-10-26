"""Focused v1.6 acceptance checks, isolated from user data and providers."""
from datetime import datetime
from typing import cast
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from app import features, nlu
from app.ai.rules import parse as rules
from app.ai.schema import Awaiting, Input, Result
from app.database import Base
from app.models import ChatLog, DateKind, Record, TaskType
from app.owner import Owner, get_owner
from app.routers import chat
from app.schemas import ChatPayload, ChatRequest
from tests.test_bulk_delete_calendar import AsyncSessionBridge

NOW = datetime(2026, 10, 21, 10)


class ContractSchemaTests(unittest.TestCase):
    def payload(self):
        return dict(conversation_id=str(uuid4()), text="Привет", source="text",
                    client_time="2026-10-21T10:00:00+03:00", timezone="Europe/Moscow")

    def test_required_fields_and_uuid(self):
        body = self.payload()
        ChatPayload.model_validate(body)
        for key in body:
            with self.subTest(missing=key), self.assertRaises(ValidationError):
                ChatPayload.model_validate({k: v for k, v in body.items() if k != key})
        for key, value in [("conversation_id", "not-a-uuid"), ("client_time", "yesterday"),
                           ("client_time", "2026-10-21T10:00:00"), ("timezone", "not/a/timezone")]:
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                ChatPayload.model_validate({**body, key: value})

    def test_all_existing_contract_phrases_have_serializable_rule_results(self):
        dataset = json.loads((Path(__file__).parent / "data/contract_v15_phrases.json").read_text(encoding="utf-8"))
        for dialog in dataset["dialogs"]:
            for step in dialog["steps"]:
                if "say" not in step:
                    continue
                with self.subTest(dialog=dialog["id"], phrase=step["say"]):
                    result = rules(Input(text=step["say"], now=NOW, timezone="Europe/Moscow"))
                    Result.model_validate(result.model_dump(mode="json", by_alias=True))
                    self.assertEqual(result.layer, "rules")

    def test_explicit_reminder_prefix(self):
        result = rules(Input(text="напоминание: оплатить интернет", now=NOW))
        self.assertEqual((result.intent, result.items[0].type, result.items[0].text),
                         ("create", "reminder", "Оплатить интернет"))

    def test_weekends_default_and_explicit_exclusion(self):
        self.assertTrue(nlu.parse("самый свободный день на следующей неделе", NOW).weekends)
        self.assertFalse(nlu.parse("самый свободный день на следующей неделе без выходных", NOW).weekends)

    def test_ai_boundary_classifies_named_cancellation_and_contextual_reply(self):
        result = rules(Input(text="в среду через 3 недели репетитора по математике не будет, убери задачу", now=NOW))
        self.assertEqual(result.intent, "delete")
        assert result.target is not None
        self.assertEqual(result.target.date, "2026-11-11")
        result = rules(Input(text="в 15", now=NOW, awaiting=Awaiting(question="time")))
        self.assertEqual(result.intent, "reply")
        assert result.reply is not None
        self.assertEqual(result.reply.time, "15:00")

    def test_ai_boundary_preserves_last_query_period_when_type_changes(self):
        result = rules(Input(text="а встречи?", now=NOW, last_query={"intent": "list",
            "period": {"start": "2026-10-22", "end": "2026-10-22", "label": "завтра"}}))
        self.assertEqual((result.intent, result.filter_type), ("list", "meeting"))
        assert result.period is not None
        self.assertEqual(result.period.start, "2026-10-22")


class ContractBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.db = cast(AsyncSession, AsyncSessionBridge(self.session))
        self.owner = Owner(sandbox_id="contract-v16")
        self.ctx = chat.Ctx(owner=self.owner, db=self.db, conv=chat.Conversation(), now=NOW,
                            features={"d2", "d3", "d10"})

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    async def say(self, text, action=None):
        return await chat.respond(self.ctx, ChatRequest(conversation_id="unit", text=text, action=action))

    async def test_missing_mode_is_422_without_database_access(self):
        db = AsyncMock()
        with self.assertRaises(HTTPException) as failure:
            await get_owner(authorization=None, x_client_id=None, db=db)
        self.assertEqual(failure.exception.status_code, 422)
        db.execute.assert_not_awaited()

    async def test_invalid_authorization_cannot_fall_back_to_sandbox(self):
        with self.assertRaises(HTTPException) as failure:
            await get_owner(authorization="Basic invalid", x_client_id="contract-v16", db=AsyncMock())
        self.assertEqual(failure.exception.status_code, 401)

    async def test_busy_duplicate_and_contract_conflict_buttons(self):
        first = await self.say("Завтра работа с 9 до 18")
        self.assertEqual(first["kind"], "created", first)
        again = await self.say("Завтра работа с 9 до 18")
        self.assertEqual(again["kind"], "created", again)
        self.assertEqual(again["records"][0]["id"], first["records"][0]["id"])
        self.assertEqual(self.session.query(Record).count(), 1)
        conflict = await self.say("Завтра учёба с 12 до 14")
        self.assertEqual(conflict["kind"], "conflict", conflict)
        buttons = {b["label"]: b["send"]["action"] for b in conflict["buttons"]}
        self.assertEqual(buttons["Изменить существующую"]["id"], "edit_existing")
        self.assertIn("Другое время для новой", buttons)
        self.assertIn("Оставить обе", buttons)
        question = await self.say("Изменить существующую", buttons["Изменить существующую"])
        self.assertEqual(question["kind"], "clarify", question)
        moved = await self.say("с 15 до 19")
        self.assertEqual(moved["kind"], "updated", moved)
        old = self.session.get(Record, first["records"][0]["id"])
        assert old is not None
        self.assertEqual((old.time, old.end_time), ("15:00", "19:00"))

    async def test_free_day_compares_weekends_with_busy_workdays(self):
        await self.say("По будням работа с 9 до 18")
        result = await self.say("самый свободный день на следующей неделе")
        self.assertEqual(result["kind"], "clarify", result)
        self.assertIn("31 окт", result["text"])
        self.assertNotIn("Выходные не считал", result["text"])

    async def test_disabling_creation_blocks_pending_confirmation(self):
        result = await self.say("Завтра в 10 сделать что-нибудь по отчёту")
        self.assertEqual(result["kind"], "confirm", result)
        with patch.object(features, "on", side_effect=lambda key: key != "f5"):
            result = await self.say("Да", {"id": "confirm_yes"})
        self.assertEqual(result["kind"], "not_understood")
        self.assertEqual(self.session.query(Record).count(), 0)

    async def test_conversation_expires_after_two_hours_even_when_small(self):
        key = str(uuid4())
        previous = chat.conversation(self.owner, key)
        previous.pending = chat.Pending("draft", {"text": "Тест"})
        previous.touched -= 3 * 3600
        self.assertIsNone(chat.conversation(self.owner, key).pending)

    def test_journal_has_contract_metrics(self):
        self.assertTrue({"layer", "confidence", "doubts", "parsed", "llm_ms"} <= set(ChatLog.__table__.columns.keys()))


if __name__ == "__main__":
    unittest.main()
