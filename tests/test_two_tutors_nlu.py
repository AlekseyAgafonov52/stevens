"""Regression: a coordinated phrase with two independent hours creates two meetings.

Offline: no PostgreSQL credentials or YandexGPT API keys needed.
"""
from datetime import date, datetime
import pytest

from app import nlu
from app.ai.rules import parse as parse_rules
from app.ai.adapter import to_parses
from app.ai.schema import Input

NOW = datetime(2026, 10, 21, 10, 0)
TOMORROW = date(2026, 10, 22)


@pytest.mark.parametrize("phrase, titles", [
    (
        "Составь встречу завтра с репетитором по математике в 14 и по физике в 17.",
        ("Встреча с репетитором по математике", "Встреча с репетитором по физике"),
    ),
    (
        "Поставь встречу завтра с репетитором по математике в 14 и по физике в 17",
        ("Встреча с репетитором по математике", "Встреча с репетитором по физике"),
    ),
    (
        "Назначь встречу завтра с преподавателем по математике в 14 и по физике в 17",
        ("Встреча с преподавателем по математике", "Встреча с преподавателем по физике"),
    ),
    (
        "Завтра встреча с Машей в 14 и с Таней в 17",
        ("Встреча с Машей", "Встреча с Таней"),
    ),
    (
        "Встреча завтра с репетитором по математике в 14 и с преподавателем по физике в 17",
        ("Встреча с репетитором по математике", "Встреча с преподавателем по физике"),
    ),
])
def test_two_meetings_with_shared_date(phrase, titles):
    many = nlu.parse_many(phrase, NOW)
    assert many is not None and len(many) == 2
    assert [p.intent for p in many] == ["create", "create"]
    assert [p.type for p in many] == ["meeting", "meeting"]
    assert [p.text for p in many] == list(titles)
    assert [p.time for p in many] == ["14:00", "17:00"]
    assert [p.date for p in many] == [TOMORROW, TOMORROW]


def test_contract_rules_return_two_items_not_one():
    phrase = "Составь встречу завтра с репетитором по математике в 14 и по физике в 17."
    request = Input(text=phrase, now=NOW)
    result = parse_rules(request)
    assert result.intent == "create"
    assert result.layer == "rules"
    assert result.confidence >= 0.8, "Clear multi-command should not unnecessarily call LLM"
    assert len(result.items) == 2
    assert [item.type for item in result.items] == ["meeting", "meeting"]
    assert [item.time for item in result.items] == ["14:00", "17:00"]
    assert [item.date for item in result.items] == [TOMORROW.isoformat()] * 2
    adapted = to_parses(result, NOW.date())
    assert [(p.text, p.time) for p in adapted] == [
        ("Встреча с репетитором по математике", "14:00"),
        ("Встреча с репетитором по физике", "17:00"),
    ]


@pytest.mark.parametrize("phrase", [
    "Завтра в 14 встреча с репетитором по математике и по физике",
    "Составь встречу завтра с Машей и с Таней в 17",
    "Составь встречу завтра с репетитором по математике в 14 и по физике",
    "Составь список дел на завтра: математика и физика",
])
def test_do_not_guess_two_meetings_without_two_times(phrase):
    assert nlu.parse_many(phrase, NOW) is None


def test_existing_multi_reminders_are_unchanged():
    phrase = "Напомни завтра в 9 позвонить врачу и в 12 забрать анализы"
    many = nlu.parse_many(phrase, NOW)
    assert many is not None and len(many) == 2
    assert [p.type for p in many] == ["reminder", "reminder"]
    assert [p.time for p in many] == ["09:00", "12:00"]
