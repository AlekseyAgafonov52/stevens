"""Unit tests: no Yandex credentials and no database required."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.ai.provider import InvalidResponse, decode, decode_for_request, parse
from app.ai.schema import Input
from app.ai.adapter import to_parses

NOW = datetime(2026, 10, 28, 10, tzinfo=timezone.utc)


def test_missing_period_repairs_only_read_only_list():
    request = Input(text="У меня завтра много дел?", now=NOW)
    result = decode_for_request('{"intent":"list","query_mode":"workload","confidence":0.9,"layer":"llm"}', request)
    assert result.period.start == "2026-10-29"
    assert result.period.end == "2026-10-29"
    assert result.query_mode == "workload"
    parsed = to_parses(result, NOW.date())[0]
    assert parsed.intent == "list" and parsed.query_mode == "workload"


def test_list_without_date_defaults_to_today():
    request = Input(text="Что у меня запланировано?", now=NOW)
    result = decode_for_request('{"intent":"list","confidence":0.9,"layer":"llm"}', request)
    assert result.period.start == NOW.date().isoformat()


def test_legacy_readonly_workload_alias():
    request = Input(text="У меня завтра много дел?", now=NOW)
    result = decode_for_request('{"intent":"workload","confidence":0.9,"layer":"llm"}', request)
    assert result.intent == "list" and result.query_mode == "workload"


def test_invalid_mutation_is_not_repaired():
    request = Input(text="Поставь хоккей завтра", now=NOW)
    with pytest.raises(InvalidResponse):
        decode_for_request('{"intent":"create","confidence":0.9,"layer":"llm"}', request)
    with pytest.raises(InvalidResponse):
        decode_for_request('{"intent":"move","confidence":0.9,"layer":"llm"}', request)


def test_rejects_bad_extra_fields_even_read_only():
    request = Input(text="Что у меня завтра?", now=NOW)
    with pytest.raises(InvalidResponse):
        decode_for_request('{"intent":"list","confidence":0.9,"layer":"llm","sql":"DROP TABLE x"}', request)


def test_strict_decode_stays_strict_without_request():
    with pytest.raises(InvalidResponse):
        decode('{"intent":"list","confidence":0.9,"layer":"llm"}')


def test_retry_after_invalid_json_then_good(monkeypatch):
    request = Input(text="Напомни завтра проверить отчёт", now=NOW)
    valid = json.dumps({"intent": "create", "items": [{"type": "reminder", "text": "Проверить отчёт", "date": "2026-10-29"}],
                        "confidence": 0.9, "layer": "llm"}, ensure_ascii=False)
    outputs = iter(['{"intent":"create","items":[]}', valid])
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output=[], output_text=next(outputs))

    monkeypatch.setenv("YANDEX_API_KEY", "test")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test")
    with patch("app.ai.provider.client.responses.create", side_effect=fake_create):
        result = parse(request)
    assert result.intent == "create" and result.items[0].text == "Проверить отчёт"
    assert len(calls) == 2
    assert "ПРЕДЫДУЩИЙ ОТВЕТ" in calls[1]["instructions"]


def test_retry_does_not_execute_hallucinated_title(monkeypatch):
    request = Input(text="Поставь хоккей на пятницу", now=NOW)
    wrong = json.dumps({"intent": "create", "items": [{"type": "task", "text": "Созвон с клиентом"}],
                        "confidence": 0.95, "layer": "llm"}, ensure_ascii=False)
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output=[], output_text=wrong)

    monkeypatch.setenv("YANDEX_API_KEY", "test")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test")
    with patch("app.ai.provider.client.responses.create", side_effect=fake_create), pytest.raises(InvalidResponse):
        parse(request)
    assert len(calls) == 2


def test_reject_calendar_question_as_off_topic():
    from app.ai.quality import validate_candidate
    from app.ai.schema import Result
    request = Input(text="У меня завтра много дел?", now=NOW)
    candidate = Result(intent="off_topic", layer="llm", confidence=0.95)
    with pytest.raises(InvalidResponse, match="calendar_question_misclassified"):
        validate_candidate(request, candidate)


def test_weekday_in_conversational_request():
    request = Input(text="Расскажи, какой у меня будет день в пятницу", now=NOW)
    result = decode_for_request('{"intent":"list","query_mode":"summary","confidence":0.9,"layer":"llm"}', request)
    assert result.period.start == "2026-10-30"
