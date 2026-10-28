"""Offline contract and failure checks for the Yandex fallback."""
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost/unused")

import httpx
import openai
import brain
from app.ai import provider
from app.ai.adapter import query_context, to_parses
from app.ai.schema import Awaiting, Input, Result
from app import nlu
from app.routers import chat

NOW = datetime.fromisoformat("2031-11-04T10:00:00+03:00")


def creation(**changes):
    return {"intent": "create", "items": [{"type": "task", "text": "Подготовить отчёт 25",
            "date": "2031-11-06", "time": "09:00", **changes}], "confidence": 0.95, "layer": "llm"}


class SchemaTests(unittest.TestCase):
    def decode(self, data):
        return provider.decode(json.dumps(data, ensure_ascii=False))

    def test_title_numbers_and_ready_date_are_preserved(self):
        result = self.decode(creation())
        parsed = to_parses(result, NOW.date())[0]
        self.assertEqual(parsed.text, "Подготовить отчёт 25")
        self.assertEqual(parsed.date, date(2031, 11, 6))
        self.assertEqual(parsed.doubt, [{"why": "llm"}])

    def test_invalid_dates_times_and_tokens_are_rejected(self):
        for change in [{"date": "2027-02-29"}, {"date": "tomorrow"}, {"date": "2031-13-01"},
                       {"time": "25:99"}, {"time": "9:00"}, {"time": "09:00:00"}]:
            with self.subTest(change=change), self.assertRaises(provider.InvalidResponse):
                self.decode(creation(**change))

    def test_missing_time_can_be_clarified(self):
        result = self.decode(creation(type="meeting", time=None))
        parsed = to_parses(result, NOW.date())[0]
        self.assertEqual(parsed.intent, "create")
        self.assertIsNone(parsed.time)

    def test_unknown_stays_unknown_without_keyword_guesses(self):
        result = self.decode({"intent": "unknown", "confidence": 0.1, "layer": "llm"})
        self.assertEqual(to_parses(result, NOW.date())[0].intent, "unknown")

    def test_confidence_and_layer_must_be_valid(self):
        for change in [{"confidence": -1}, {"confidence": 1.1}, {"confidence": True},
                       {"confidence": "high"}, {"layer": "rules"}, {"intent": "create_task"}]:
            with self.subTest(change=change), self.assertRaises(provider.InvalidResponse):
                self.decode({**creation(), **change})

    def test_extra_fields_and_reversed_period_rejected(self):
        for data in [{**creation(), "sql": "delete records"},
                     {"intent": "list", "period": {"start": "2031-11-07", "end": "2031-11-06", "label": "bad"},
                      "confidence": 0.9, "layer": "llm"}]:
            with self.subTest(data=data), self.assertRaises(provider.InvalidResponse):
                self.decode(data)

    def test_invalid_json_is_not_guessed(self):
        for text in ['[]', '{}', '{"intent":"unknown","intent":"help"}',
                     json.dumps(creation()) + json.dumps(creation()), 'Here is JSON: ' + json.dumps(creation()),
                     '{"intent":"unknown","confidence":NaN,"layer":"llm"}']:
            with self.subTest(text=text), self.assertRaises(provider.InvalidResponse):
                provider.decode(text)

    def test_code_fence_and_json_both_validate(self):
        self.assertEqual(provider.decode('```json\n' + json.dumps(creation()) + '\n```').intent, "create")

    def test_incomplete_doubt_cannot_break_confirmation_template(self):
        for doubt in [{"why": "typo"}, {"why": "typo", "word": "зватра"}, {"why": "vague"}]:
            with self.subTest(doubt=doubt), self.assertRaises(provider.InvalidResponse):
                self.decode({**creation(), "doubts": [doubt]})

    def test_too_long_title_and_output_rejected(self):
        with self.assertRaises(provider.InvalidResponse):
            self.decode(creation(text="x" * 301))
        with self.assertRaises(provider.InvalidResponse):
            provider.decode(" " * 65537)

    def test_low_confidence_never_creates(self):
        result = self.decode({**creation(), "confidence": 0.49})
        self.assertEqual(to_parses(result, NOW.date())[0].intent, "unknown")

    def test_medium_confidence_create_still_needs_confirmation(self):
        result = self.decode({**creation(), "confidence": 0.6})
        self.assertTrue(to_parses(result, NOW.date())[0].doubt)

    def test_unimplemented_actions_never_get_enabled(self):
        result = self.decode({"intent": "delete", "target": {"ref": "focus"},
                              "confidence": 1.0, "layer": "llm"})
        self.assertEqual(to_parses(result, NOW.date())[0].intent, "unknown")

    def test_search_respects_type_date_and_period(self):
        result = self.decode({"intent": "search", "query": {"keywords": ["договор"], "person": "Иван",
                              "type": "meeting", "ask": "when", "tense": "past", "date": "2031-11-03"},
                              "confidence": 0.9, "layer": "llm"})
        parsed = to_parses(result, NOW.date())[0]
        self.assertEqual((parsed.filter_type, parsed.ask, parsed.tense), ("meeting", "when", "past"))
        self.assertEqual(parsed.date, date(2031, 11, 3))
        self.assertTrue(parsed.keywords)

    def test_zero_reminder_interval_reaches_draft(self):
        result = self.decode(creation(type="meeting", remind_before=0))
        draft = chat.draft_from(to_parses(result, NOW.date())[0], NOW.date())
        self.assertEqual(draft["remind_before"], 0)
        self.assertEqual(chat.draft_record(draft, ["draft"])["remind_before"], 0)

    def test_replacement_uses_exact_contract_field_name(self):
        result = self.decode({"intent": "fix", "change": {"replace": {"from": "Ваня", "to": "Иван"}},
                              "confidence": 0.9, "layer": "llm"})
        self.assertEqual(result.model_dump(by_alias=True)["change"]["replace"]["from"], "Ваня")


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"YANDEX_API_KEY": "synthetic-key", "YANDEX_FOLDER_ID": "synthetic-folder"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def response(self, arguments=None, **fields):
        call = SimpleNamespace(type="function_call", name="extract_intent", arguments=arguments or json.dumps(creation()))
        return SimpleNamespace(output=[call], output_text="", status="completed", **fields)

    def test_context_is_passed_and_prompt_has_no_fixed_year(self):
        context = Input(text="6 ноября отчёт 25", now=NOW, timezone="Europe/Moscow", source="voice",
                        awaiting=Awaiting(question="time", about={"text": "Отчёт 25"}),
                        focus={"text": "Отчёт 25"}, last_query={"intent": "list"})
        with patch.object(brain.client.responses, "create", return_value=self.response()) as create:
            brain.parse_user_input(context.text, context=context)
        request = json.loads(create.call_args.kwargs["input"])
        self.assertEqual(request["now"], NOW.isoformat())
        self.assertEqual(request["awaiting"]["question"], "time")
        self.assertEqual(request["source"], "voice")
        self.assertEqual(request["timezone"], "Europe/Moscow")
        self.assertNotIn("2026-11-06", create.call_args.kwargs["instructions"])
        self.assertNotIn("synthetic-key", create.call_args.kwargs["input"])
        self.assertEqual(set(request), {"text", "now", "timezone", "source", "awaiting", "focus", "last_query"})

    def test_missing_credentials_make_no_request(self):
        with patch.dict(os.environ, {"YANDEX_API_KEY": ""}), patch.object(brain.client.responses, "create") as create:
            with self.assertRaises(brain.Unavailable):
                brain.parse_user_input("test")
            create.assert_not_called()

    def test_provider_timeout_has_distinct_reason(self):
        error = openai.APITimeoutError(request=httpx.Request("POST", "https://provider.invalid"))
        with patch.object(brain.client.responses, "create", side_effect=error):
            with self.assertRaisesRegex(brain.Unavailable, "^timeout$"):
                brain.parse_user_input("test")

    def test_incomplete_multiple_and_unknown_calls_rejected(self):
        good = self.response()
        cases = [SimpleNamespace(output=good.output, output_text="", status="incomplete"),
                 SimpleNamespace(output=good.output * 2, output_text="", status="completed"),
                 SimpleNamespace(output=[SimpleNamespace(type="function_call", name="delete_all", arguments="{}")],
                                 output_text="", status="completed")]
        for response in cases:
            with self.subTest(response=response), patch.object(brain.client.responses, "create", return_value=response):
                with self.assertRaises(provider.InvalidResponse):
                    brain.parse_user_input("test")

    def test_plain_json_response_validates(self):
        response = SimpleNamespace(output=[], output_text=json.dumps(creation()), status="completed")
        # The returned title must be grounded in the user's actual request.
        with patch.object(brain.client.responses, "create", return_value=response):
            self.assertEqual(brain.parse_user_input("Подготовить отчёт 25").items[0].text, "Подготовить отчёт 25")


class DialogueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        chat._llm_down_until = 0

    def tearDown(self):
        chat._llm_down_until = 0

    async def test_invalid_response_does_not_start_provider_cooldown(self):
        trace = {}
        with patch("brain.parse_user_input", side_effect=provider.InvalidResponse("invalid_parse_schema")) as parse:
            result = await chat.llm_parse("test", NOW, trace=trace)
            other_trace = {}
            await chat.llm_parse("another", NOW, trace=other_trace)
        self.assertEqual(result.intent, "unknown")
        self.assertEqual(trace["llm_status"], "invalid_response")
        self.assertEqual(other_trace["llm_status"], "invalid_response")
        self.assertIn("llm_ms", trace)
        self.assertEqual(parse.call_count, 2)

    async def test_context_uses_owner_checked_focus_and_original_offset(self):
        from app.owner import Owner
        from app.schemas import ChatRequest
        ctx = chat.Ctx(owner=Owner(sandbox_id="context-test"), db=AsyncMock(),
                       conv=chat.Conversation(focus=42), now=NOW.replace(tzinfo=None), features=set())
        pending = chat.Pending("draft", {"type": "meeting", "text": "Встреча", "date": "2031-11-06",
                                         "ask": {"template": "clarify_meeting_time", "quick": None}})
        payload = ChatRequest(conversation_id="test", text=" в пять ", client_time=NOW.isoformat(),
                              timezone="Europe/Moscow", source="voice")
        focus = SimpleNamespace(deleted_at=None, to_contract=lambda: {"id": 42, "text": "Встреча"})
        with patch.object(chat, "owned_record", new=AsyncMock(return_value=focus)) as lookup:
            context = await chat.ai_context(ctx, payload, pending)
        lookup.assert_awaited_once_with(ctx, 42)
        self.assertEqual(context.now, NOW)
        self.assertEqual(context.text, "в пять")
        self.assertIsNotNone(context.awaiting)
        assert context.awaiting is not None
        self.assertEqual(context.awaiting.question, "time")
        self.assertEqual(context.focus, {"id": 42, "text": "Встреча"})

    async def test_ten_second_outer_deadline(self):
        async def deadline(awaitable, *, timeout):
            self.assertEqual(timeout, 10)
            awaitable.close()
            raise TimeoutError
        with patch("app.routers.chat.asyncio.wait_for", side_effect=deadline):
            trace = {}
            self.assertEqual((await chat.llm_parse("test", NOW, trace=trace)).intent, "unknown")
        self.assertEqual(trace["llm_status"], "unavailable")

    async def test_valid_create_reaches_existing_confirmation(self):
        result = provider.decode(json.dumps(creation()))
        with patch("brain.parse_user_input", return_value=result):
            parsed = await chat.llm_parse("test", NOW)
        from app.owner import Owner
        ctx = chat.Ctx(owner=Owner(sandbox_id="ai-test"), db=AsyncMock(), conv=chat.Conversation(),
                       now=NOW.replace(tzinfo=None), features=set())
        answer = await chat.process_draft(ctx, chat.draft_from(parsed, NOW.date()))
        self.assertEqual(answer["kind"], "confirm")
        self.assertEqual(answer["records"][0]["text"], "Подготовить отчёт 25")
        self.assertEqual(answer["records"][0]["marks"], ["draft"])

    async def test_batch_never_saves_only_first_item(self):
        from app.owner import Owner
        from app.schemas import ChatRequest
        for ready, expected in [(False, "not_understood"), (True, "confirm")]:
            with self.subTest(ready=ready):
                data = creation()
                data["items"].append({"type": "meeting", "text": "Встреча с Петей",
                                      "date": "2031-11-06" if ready else None,
                                      "time": "11:00" if ready else None})
                result = provider.decode(json.dumps(data))
                db = AsyncMock()
                ctx = chat.Ctx(owner=Owner(sandbox_id="ai-batch"), db=db, conv=chat.Conversation(),
                               now=NOW.replace(tzinfo=None), features={"d2", "d3", "d10"})
                payload = ChatRequest(conversation_id="test", text="бубубу", client_time=NOW.isoformat())
                with patch.dict(os.environ, {"YANDEX_API_KEY": "fake", "YANDEX_FOLDER_ID": "fake"}), \
                        patch("app.routers.chat.series.extend", new=AsyncMock()), \
                        patch("brain.parse_user_input", return_value=result):
                    answer = await chat.respond(ctx, payload)
                self.assertEqual(answer["kind"], expected)
                self.assertEqual(len(answer["records"]), 2 if ready else 0)
                db.commit.assert_not_awaited()

    def test_query_context_contains_public_fields_only(self):
        parsed = nlu.Parse(intent="list", filter_type="meeting", period=nlu.Period(NOW.date(), NOW.date(), "сегодня", "сегодня"))
        context = query_context(parsed)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context["period"]["start"], "2031-11-04")
        self.assertNotIn("owner", context)


if __name__ == "__main__":
    unittest.main()
