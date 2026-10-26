"""Provider-inferred mutations require explicit approval of immutable record snapshots."""
from datetime import datetime
from typing import cast
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.ai.schema import Result
from app.database import Base
from app.models import DateKind, Record, Series, TaskStatus, TaskType
from app.owner import Owner
from app.routers import chat
from app.schemas import ChatRequest
from tests.test_bulk_delete_calendar import AsyncSessionBridge


class AIConfirmationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.ctx = chat.Ctx(owner=Owner(sandbox_id="ai-confirm"),
                            db=cast(AsyncSession, AsyncSessionBridge(self.session)), conv=chat.Conversation(),
                            now=datetime(2026, 10, 21, 10), features={"d2", "d3", "d10"})
        self.record = Record(sandbox_id="ai-confirm", type=TaskType.task, text="Договор", date="2026-10-22",
                             time="11:00", date_kind=DateKind.exact, status=TaskStatus.open)
        self.session.add(self.record)
        self.session.commit()
        self.ctx.conv.focus = self.record.id
        chat._llm_down_until = 0

    def tearDown(self):
        self.session.close()
        self.engine.dispose()
        chat._llm_down_until = 0

    async def say(self, text, action=None):
        return await chat.respond(self.ctx, ChatRequest(conversation_id="test", text=text, action=action))

    async def propose(self, intent="delete", **fields):
        result = Result.model_validate({"intent": intent, "target": {"ref": "focus"},
                                       "confidence": 0.9, "layer": "llm", **fields})
        with patch.object(chat, "llm_enabled", return_value=True), patch("brain.parse_user_input", return_value=result):
            return await self.say("бубубу")

    async def test_delete_is_a_proposal_until_separate_yes(self):
        result = await self.propose()
        self.assertEqual(result["kind"], "confirm", result)
        self.assertEqual(result["records"][0]["id"], self.record.id)
        self.assertIsNone(self.record.deleted_at)
        result = await self.say("Да, верно", {"id": "confirm_yes"})
        self.assertEqual(result["kind"], "deleted", result)
        self.assertIsNotNone(self.record.deleted_at)

    async def test_no_preserves_records(self):
        await self.propose()
        result = await self.say("нет")
        self.assertEqual(result["kind"], "cancelled")
        self.assertIsNone(self.record.deleted_at)
        self.assertIsNone(self.ctx.conv.pending)

    async def test_record_changed_after_preview_invalidates_confirmation(self):
        await self.propose()
        self.record.text = "Новая редакция договора"
        self.session.commit()
        result = await self.say("да")
        self.assertEqual(result["kind"], "clarify", result)
        self.assertIsNone(self.record.deleted_at)
        self.assertEqual(self.record.text, "Новая редакция договора")

    async def test_move_and_edit_do_not_apply_before_approval(self):
        result = await self.propose("move", change={"date": "2026-10-23", "time": "15:00"})
        self.assertEqual(result["kind"], "confirm", result)
        self.assertEqual(self.record.date, "2026-10-22")
        self.assertIn("draft", result["records"][1]["marks"])
        result = await self.say("да")
        self.assertEqual(result["kind"], "updated", result)
        self.assertEqual((self.record.date, self.record.time), ("2026-10-23", "15:00"))
        await self.propose("edit", change={"text": "Отправить договор"})
        self.assertEqual(self.record.text, "Договор")
        await self.say("да")
        self.assertEqual(self.record.text, "Отправить договор")

    async def test_complete_requires_confirmation(self):
        await self.propose("complete")
        self.assertEqual(self.record.status, TaskStatus.open)
        self.assertEqual((await self.say("да"))["kind"], "completed")
        self.assertEqual(self.record.status, TaskStatus.done)

    async def test_query_cannot_select_another_owners_records(self):
        self.ctx.owner = Owner(sandbox_id="different-owner")
        result = await self.propose()
        self.assertEqual((result["kind"], result["total"]), ("found", 0))
        self.assertIsNone(self.record.deleted_at)

    async def test_low_confidence_never_creates_a_mutation_proposal(self):
        result = await self.propose(confidence=0.2)
        self.assertEqual(result["kind"], "not_understood", result)
        self.assertIsNone(self.ctx.conv.pending)
        self.assertIsNone(self.record.deleted_at)

    async def test_feature_disabled_after_preview_prevents_mutation(self):
        await self.propose()
        with patch.object(chat.features, "on", side_effect=lambda key: key != "f12"):
            result = await self.say("да", {"id": "confirm_yes"})
        self.assertEqual(result["kind"], "not_understood", result)
        self.assertIsNone(self.record.deleted_at)

    async def test_repeated_confirmation_does_not_touch_new_records(self):
        await self.propose()
        await self.say("да", {"id": "confirm_yes"})
        new = Record(sandbox_id="ai-confirm", type=TaskType.task, text="Новая", date_kind=DateKind.none)
        self.session.add(new)
        self.session.commit()
        self.ctx.conv.focus = new.id
        await self.say("Да, верно", {"id": "confirm_yes"})
        self.assertIsNone(new.deleted_at)

    async def test_multiple_matches_require_selection_then_confirmation(self):
        other = Record(sandbox_id="ai-confirm", type=TaskType.task, text="Договор второй", date_kind=DateKind.none)
        self.session.add(other)
        self.session.commit()
        result = await self.propose(target={"ref": "query", "query": {"keywords": ["договор"]}})
        self.assertEqual(result["kind"], "clarify", result)
        selected = result["buttons"][0]["send"]["action"]
        result = await self.say("Выбрать", selected)
        self.assertEqual(result["kind"], "confirm", result)
        chosen_id = result["records"][0]["id"]
        self.assertIsNone(self.record.deleted_at)
        self.assertIsNone(other.deleted_at)
        await self.say("да")
        chosen = self.session.get(Record, chosen_id)
        assert chosen is not None
        self.assertIsNotNone(chosen.deleted_at)
        self.assertEqual(self.session.query(Record).filter(Record.deleted_at.is_(None)).count(), 1)

    async def test_undo_cannot_expand_to_unconfirmed_new_occurrences(self):
        rule = Series(sandbox_id="ai-confirm", type=TaskType.task, text="Договор", weekdays="3", filled_until="2027-10-21")
        self.session.add(rule)
        self.session.flush()
        self.record.series_id = rule.id
        self.record.repeat = "3"
        self.session.commit()
        self.ctx.conv.undo = {"id": "undo", "record_id": self.record.id}
        result = await self.propose("undo", target={"ref": "last"}, change={"restore": False})
        self.assertEqual(result["kind"], "confirm", result)
        new = Record(sandbox_id="ai-confirm", type=TaskType.task, text="Договор", date="2026-10-29",
                     date_kind=DateKind.exact, series_id=rule.id, repeat="3")
        self.session.add(new)
        self.session.commit()
        await self.say("да")
        self.assertIsNotNone(self.record.deleted_at)
        self.assertIsNone(new.deleted_at)

    async def test_move_confirmation_expires_if_destination_becomes_past(self):
        await self.propose("move", change={"date": "2026-10-22", "time": "12:00"})
        self.ctx.now = datetime(2026, 10, 22, 13)
        result = await self.say("да")
        self.assertEqual(result["kind"], "clarify", result)
        self.assertEqual(self.record.time, "11:00")

    async def test_model_cannot_turn_an_unclear_reply_into_user_approval(self):
        await self.propose()
        fake_yes = Result.model_validate({"intent": "reply", "reply": {"kind": "yes"}, "confidence": 1.0, "layer": "llm"})
        with patch.object(chat, "llm_enabled", return_value=True), patch("brain.parse_user_input", return_value=fake_yes) as model:
            result = await self.say("бубубу")
        self.assertEqual(result["kind"], "clarify", result)
        self.assertIsNone(self.record.deleted_at)
        model.assert_not_called()

    async def test_llm_note_creation_is_confirmed_and_has_no_schedule(self):
        result = Result.model_validate({"intent": "note", "items": [{"type": "note", "text": "Идея"}],
                                        "confidence": 0.9, "layer": "llm"})
        with patch.object(chat, "llm_enabled", return_value=True), patch("brain.parse_user_input", return_value=result):
            answer = await self.say("бубубу")
        self.assertEqual(answer["kind"], "confirm", answer)
        self.assertEqual(self.session.query(Record).count(), 1)
        saved = await self.say("да")
        self.assertEqual(saved["kind"], "created", saved)
        row = saved["records"][0]
        self.assertEqual((row["type"], row["date"], row["time"], row["status"], row["date_kind"]),
                         ("note", None, None, None, "none"))

    async def test_llm_time_reply_only_produces_a_draft_for_approval(self):
        first = await self.say("Напомни завтра позвонить Ивану")
        self.assertEqual(first["kind"], "clarify", first)
        result = Result.model_validate({"intent": "reply", "reply": {"kind": "time", "time": "13:00"},
                                        "confidence": 0.9, "layer": "llm"})
        with patch.object(chat, "llm_enabled", return_value=True), patch("brain.parse_user_input", return_value=result):
            answer = await self.say("бубубу")
        self.assertEqual(answer["kind"], "confirm", answer)
        self.assertEqual(self.session.query(Record).count(), 1)
        self.assertEqual(answer["records"][0]["time"], "13:00")


if __name__ == "__main__":
    unittest.main()
