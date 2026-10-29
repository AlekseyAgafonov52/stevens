"""Offline multi-action NLU, routing, and mocked YandexGPT transport tests.

No PostgreSQL, real Yandex credentials, or network calls required.
"""
import asyncio
import importlib.util
import json
import sys
import types
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app import nlu
from app.ai.decomposition import requested_count, suspected_multiple
from app.ai.rules import parse as parse_rules
from app.ai.adapter import to_parses
from app.ai.schema import Input, Item, Result

NOW = datetime(2026, 10, 21, 10, 0)


@pytest.mark.parametrize("phrase, expected", [
    (
        "Завтра математика в два, а физика в пять.",
        [("task", "Математика", date(2026, 10, 22), "14:00"),
         ("task", "Физика", date(2026, 10, 22), "17:00")],
    ),
    (
        "Поставь два занятия на завтра: английский утром и программирование в 18.",
        [("task", "Английский", date(2026, 10, 22), "09:00"),
         ("task", "Программирование", date(2026, 10, 22), "18:00")],
    ),
    (
        "Запиши в пятницу встречу с Иваном в 12, с Олегом в 15 и созвон с Марией в 19.",
        [("meeting", "Встреча с Иваном", date(2026, 10, 23), "12:00"),
         ("meeting", "Встреча с Олегом", date(2026, 10, 23), "15:00"),
         ("meeting", "Созвон с Марией", date(2026, 10, 23), "19:00")],
    ),
    (
        "В понедельник надо оплатить квартиру, забрать посылку в 16 и напомнить про тренировку в 20.",
        [("task", "Оплатить квартиру", date(2026, 10, 26), None),
         ("task", "Забрать посылку", date(2026, 10, 26), "16:00"),
         ("reminder", "Напомнить про тренировку", date(2026, 10, 26), "20:00")],
    ),
])
def test_independent_actions_are_separate(phrase, expected):
    pieces = nlu.parse_many(phrase, NOW)
    assert pieces is not None
    assert [(p.type, p.text, p.date, p.time) for p in pieces] == expected
    result = parse_rules(Input(text=phrase, now=NOW))
    assert result.intent == "create"
    assert len(result.items) == len(expected)
    assert [x.type for x in result.items] == [e[0] for e in expected]
    assert [x.date for x in result.items] == [e[2].isoformat() for e in expected]
    assert [x.time for x in result.items] == [e[3] for e in expected]
    adapted = to_parses(result, NOW.date())
    assert [(x.type, x.text, x.date, x.time) for x in adapted] == expected


def test_vague_hour_is_not_invented_by_rules():
    result = parse_rules(Input(text="Поставь два занятия на завтра: английский утром и программирование в 18", now=NOW))
    assert result.confidence < 0.8, "Vague day part must be eligible for LLM review"
    assert result.items[0].time == "09:00"
    assert result.items[0].time_guess == "day_part"
    assert result.items[1].time == "18:00"


@pytest.mark.parametrize("phrase", [
    "Купить молоко и хлеб завтра в 9",
    "Встреча с Иваном и Марией завтра в 14",
    "Завтра в 14 встреча с репетитором по математике и по физике",
    "Покажи встречи завтра и в пятницу",
    "Поставь задачу купить два литра молока и три яйца завтра в 9",
])
def test_do_not_split_one_action(phrase):
    assert not suspected_multiple(phrase)
    assert nlu.parse_many(phrase, NOW) is None


def test_existing_reminder_splitting_preserves_type():
    many = nlu.parse_many("Напомни завтра в 9 позвонить врачу и в 12 забрать анализы", NOW)
    assert many is not None and [p.type for p in many] == ["reminder", "reminder"]
    assert [p.time for p in many] == ["09:00", "12:00"]


def test_count_mismatch_never_creates_merged_record():
    phrase = "Поставь три занятия на завтра: английский в 12 и программирование в 18"
    assert requested_count(phrase) == 3
    assert nlu.parse_many(phrase, NOW) is None
    result = parse_rules(Input(text=phrase, now=NOW))
    assert result.intent == "unknown" and result.items == []
    assert result.confidence == 0.0


@pytest.fixture
def modules(monkeypatch):
    # The CI/dev host may not have the provider SDK installed; this lightweight
    # stub lets tests verify orchestration while keeping production untouched.
    if importlib.util.find_spec("openai") is None and "openai" not in sys.modules:
        fake = types.ModuleType("openai")
        fake.OpenAI = lambda **kwargs: SimpleNamespace(responses=SimpleNamespace(create=None))
        for name in ("APITimeoutError", "RateLimitError", "AuthenticationError", "PermissionDeniedError", "APIError"):
            setattr(fake, name, type(name, (Exception,), {}))
        monkeypatch.setitem(sys.modules, "openai", fake)
    from app.ai import provider, understanding
    import brain
    return provider, understanding, brain


def test_clear_multi_does_not_call_yandex(modules, monkeypatch):
    _, understanding, brain = modules
    calls = []
    monkeypatch.setenv("YANDEX_API_KEY", "test")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test")
    monkeypatch.setattr(brain, "parse_user_input", lambda *a, **kw: calls.append((a, kw)))
    request = Input(text="Запиши в пятницу встречу с Иваном в 12, с Олегом в 15 и созвон с Марией в 19", now=NOW)
    result = asyncio.run(understanding.understand(request))
    assert result.layer == "rules" and len(result.items) == 3
    assert calls == [], "High-confidence multi-item rules should not call YandexGPT"


def test_vague_multi_is_sent_to_yandex(modules, monkeypatch):
    _, understanding, brain = modules
    calls = []
    monkeypatch.setenv("YANDEX_API_KEY", "test")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test")

    def model(text, *, context):
        calls.append((text, context))
        return Result(intent="create", layer="llm", confidence=0.95, items=[
            Item(type="task", text="Английский", date="2026-10-22", time="09:00", time_guess="day_part"),
            Item(type="task", text="Программирование", date="2026-10-22", time="18:00"),
        ])
    monkeypatch.setattr(brain, "parse_user_input", model)
    request = Input(text="Поставь два занятия на завтра: английский утром и программирование в 18", now=NOW)
    result = asyncio.run(understanding.understand(request))
    assert result.layer == "llm"
    assert [x.time for x in result.items] == ["09:00", "18:00"]
    assert len(calls) == 1 and calls[0][1] is request


def test_ambiguous_count_without_yandex_fails_closed(modules, monkeypatch):
    _, understanding, brain = modules
    monkeypatch.delenv("YANDEX_API_KEY", raising=False)
    monkeypatch.delenv("YANDEX_FOLDER_ID", raising=False)
    monkeypatch.setattr(brain, "parse_user_input", lambda *a, **kw: pytest.fail("unexpected network call"))
    request = Input(text="Поставь три занятия на завтра: английский в 12 и программирование в 18", now=NOW)
    result = asyncio.run(understanding.understand(request))
    assert result.intent == "unknown" and not result.items


def test_provider_rejects_merged_llm_items_even_after_retry(modules, monkeypatch):
    provider, _, _ = modules
    monkeypatch.setenv("YANDEX_API_KEY", "test")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test")
    request = Input(text="Запиши в пятницу встречу с Иваном в 12, с Олегом в 15 и созвон с Марией в 19", now=NOW)
    merged = json.dumps({"intent": "create", "items": [{"type": "meeting", "text": "Встреча с Иваном и Олегом и Марией", "date": "2026-10-23", "time": "12:00"}],
                         "layer": "llm", "confidence": 0.95}, ensure_ascii=False)
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output=[], output_text=merged)

    monkeypatch.setattr(provider.client.responses, "create", fake_create)
    with pytest.raises(provider.InvalidResponse, match="multi_actions_merged"):
        provider.parse(request)
    assert len(calls) == 2
    assert "ПРЕДЫДУЩИЙ ОТВЕТ" in calls[1]["instructions"]


def test_provider_accepts_valid_three_items(modules, monkeypatch):
    provider, _, _ = modules
    monkeypatch.setenv("YANDEX_API_KEY", "test")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test")
    request = Input(text="Запиши в пятницу встречу с Иваном в 12, с Олегом в 15 и созвон с Марией в 19", now=NOW)
    payload = {"intent": "create", "items": [
        {"type": "meeting", "text": "Встреча с Иваном", "date": "2026-10-23", "time": "12:00"},
        {"type": "meeting", "text": "Встреча с Олегом", "date": "2026-10-23", "time": "15:00"},
        {"type": "meeting", "text": "Созвон с Марией", "date": "2026-10-23", "time": "19:00"},
    ], "layer": "llm", "confidence": 0.9}
    monkeypatch.setattr(provider.client.responses, "create", lambda **kw: SimpleNamespace(status="completed", output=[], output_text=json.dumps(payload, ensure_ascii=False)))
    result = provider.parse(request)
    assert [x.time for x in result.items] == ["12:00", "15:00", "19:00"]
    assert all(x.date == "2026-10-23" for x in result.items)


def test_model_cannot_hallucinate_extra_unrelated_event(modules, monkeypatch):
    provider, _, _ = modules
    from app.ai.quality import validate_candidate
    request = Input(text="Завтра математика в два, а физика в пять", now=NOW)
    candidate = Result(intent="create", layer="llm", confidence=0.99, items=[
        Item(type="task", text="Математика", date="2026-10-22", time="14:00"),
        Item(type="task", text="Физика", date="2026-10-22", time="17:00"),
        Item(type="task", text="Уборка квартиры", date="2026-10-22", time="19:00"),
    ])
    with pytest.raises(provider.InvalidResponse):
        validate_candidate(request, candidate)


def test_model_cannot_repeat_extra_grounded_item(modules):
    provider, _, _ = modules
    from app.ai.quality import validate_candidate
    request = Input(text="Поставь два занятия на завтра: английский утром и программирование в 18", now=NOW)
    candidate = Result(intent="create", layer="llm", confidence=0.99, items=[
        Item(type="task", text="Английский", date="2026-10-22", time="09:00"),
        Item(type="task", text="Программирование", date="2026-10-22", time="18:00"),
        Item(type="task", text="Английский", date="2026-10-22", time="09:00"),
    ])
    with pytest.raises(provider.InvalidResponse, match="multi_actions_extra"):
        validate_candidate(request, candidate)


def test_rules_review_vague_second_item():
    result = parse_rules(Input(text="Завтра программирование в 18 и английский утром", now=NOW))
    assert result.intent == "create" and len(result.items) == 2
    assert result.items[0].time == "18:00" and result.items[1].time_guess == "day_part"
    assert result.confidence < 0.8


def test_model_cannot_swap_explicit_times(modules):
    provider, _, _ = modules
    from app.ai.quality import validate_candidate
    request = Input(text="Запиши в пятницу встречу с Иваном в 12, с Олегом в 15 и созвон с Марией в 19", now=NOW)
    candidate = Result(intent="create", layer="llm", confidence=0.99, items=[
        Item(type="meeting", text="Встреча с Иваном", date="2026-10-23", time="15:00"),
        Item(type="meeting", text="Встреча с Олегом", date="2026-10-23", time="12:00"),
        Item(type="meeting", text="Созвон с Марией", date="2026-10-23", time="19:00"),
    ])
    with pytest.raises(provider.InvalidResponse, match="multi_action_time_changed"):
        validate_candidate(request, candidate)


def test_model_cannot_invent_time_for_unscheduled_action(modules):
    provider, _, _ = modules
    from app.ai.quality import validate_candidate
    request = Input(text="В понедельник надо оплатить квартиру, забрать посылку в 16 и напомнить про тренировку в 20", now=NOW)
    candidate = Result(intent="create", layer="llm", confidence=0.99, items=[
        Item(type="task", text="Оплатить квартиру", date="2026-10-26", time="09:00"),
        Item(type="task", text="Забрать посылку", date="2026-10-26", time="16:00"),
        Item(type="reminder", text="Напомнить про тренировку", date="2026-10-26", time="20:00"),
    ])
    with pytest.raises(provider.InvalidResponse, match="multi_action_time_invented"):
        validate_candidate(request, candidate)


def test_model_cannot_change_explicit_reminder_to_task(modules):
    provider, _, _ = modules
    from app.ai.quality import validate_candidate
    request = Input(text="В понедельник надо оплатить квартиру, забрать посылку в 16 и напомнить про тренировку в 20", now=NOW)
    candidate = Result(intent="create", layer="llm", confidence=0.99, items=[
        Item(type="task", text="Оплатить квартиру", date="2026-10-26"),
        Item(type="task", text="Забрать посылку", date="2026-10-26", time="16:00"),
        Item(type="task", text="Напомнить про тренировку", date="2026-10-26", time="20:00"),
    ])
    with pytest.raises(provider.InvalidResponse, match="multi_action_type_changed"):
        validate_candidate(request, candidate)
