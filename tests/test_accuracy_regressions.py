"""Fast, deterministic regression checks for contract-like Russian phrases.

Run without a database or YandexGPT:
    python -m pytest -q tests/test_accuracy_regressions.py
These are NLU-level checks; they are NOT a replacement for run_phrases.py HTTP tests.
"""
from datetime import datetime
import pytest

from app import nlu

NOW = datetime(2026, 10, 21, 10, 0)


@pytest.mark.parametrize("utterance,expected", [
    ("каждый день в 8 напоминай выпить витамины", ("create", "reminder", "Выпить витамины", "08:00")),
    ("напоминай по понедельникам в 10 передавать показания счётчиков до конца года", ("create", "reminder", "Передавать показания счётчиков", "10:00")),
    ("перекинь её на понедельник", ("move", None, None, None)),
    ("давай её на субботу перенесём", ("move", None, None, None)),
    ("в четверг учусь с 9", ("create", "busy", "Учёба", "09:00")),
    ("в понедельник я на парах", ("create", "busy", "Пары", None)),
    ("поставь завтра на 15 встречу с поставщиком", ("create", "meeting", "Встреча с поставщиком", "15:00")),
    ("ладно", ("thanks", None, None, None)),
    ("напомни завтра в 9 позвонить маме", ("create", "reminder", "Позвонить маме", "09:00")),
    ("встреча с Петей завтра в 15", ("create", "meeting", "Встреча с Петей", "15:00")),
    ("в субботу уборка", ("create", "task", "Уборка", None)),
])
def test_phrase_routing(utterance, expected):
    p = nlu.parse(utterance, NOW)
    assert (p.intent, p.type, p.text, p.time) == expected


def test_ambiguous_time_correction_uses_last_mentioned_time():
    # Used by merge_reply after a user clarifies a draft.
    assert nlu.reply_time("в 12 стой нет давай в 13")[0] == "13:00"


def test_search_with_explicit_search_verb_is_not_person_dossier():
    p = nlu.parse("найди всё со Светой", NOW)
    assert p.intent == "search"
    assert p.keywords


def test_person_dossier_without_search_verb_still_works():
    p = nlu.parse("что у меня с Иваном", NOW)
    assert p.intent == "person"


def test_list_filter_does_not_create_meeting():
    p = nlu.parse("а только встречи?", NOW)
    assert (p.intent, p.filter_type, p.query_mode) == ("list", "meeting", "filter_only")


def test_repeated_reminder_keeps_recurrence_and_end_date():
    p = nlu.parse("напоминай по понедельникам в 10 передавать показания счётчиков до конца года", NOW)
    assert p.repeat_days == [0]
    assert p.until.isoformat() == "2026-12-31"


def test_move_variants_preserve_pronoun_reference():
    for phrase in ("перекинь её на понедельник", "давай её на субботу перенесём"):
        p = nlu.parse(phrase, NOW)
        assert p.intent == "move"
        assert p.ref is True
        assert p.date is not None


def test_question_does_not_invent_a_meeting():
    p = nlu.parse("а только встречи?", NOW)
    assert p.intent != "create"
