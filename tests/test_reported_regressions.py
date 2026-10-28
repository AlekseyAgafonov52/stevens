"""Offline safeguards for regressions described in для-Никиты.md.
API/dialogue checks still require a clean local Postgres and contract phrases.
"""
from datetime import datetime
from app import nlu
from app.ai.schema import Input, Item, Result
from app.ai.quality import validate_input, validate_candidate

NOW = datetime(2026, 10, 21, 10, 0)


def test_readonly_calendar_questions_never_create():
    samples = {
        'Есть ли встречи сегодня?': 'list',
        'Во сколько встреча с Иваном?': 'search',
        'Есть что-нибудь завтра?': 'list',
        'У меня завтра много дел?': 'list',
        'сколько у меня завтра встреч?': 'list',
    }
    for utterance, intent in samples.items():
        assert nlu.parse(utterance, NOW).intent == intent


def test_still_create_speech_intended_as_task():
    item = nlu.parse('расскажи маме про отпуск завтра в 10', NOW)
    assert item.intent == 'create' and item.time == '10:00'


def test_reminder_of_studying_is_not_busy():
    item = nlu.parse('напомни завтра в 20 учиться водить', NOW)
    assert (item.intent, item.type, item.time) == ('create', 'reminder', '20:00')


def test_question_marks_are_not_corrupted_encoding():
    for utterance in ('что???', 'напомни завтра в 10 позвонить маме???'):
        validate_input(Input(text=utterance, now=NOW))


def test_grounding_accepts_selected_event_title():
    request = Input(text='во сколько и когда?', now=NOW,
                    focus={'text': 'Позвонить маме'}, history=[])
    result = Result(intent='create', layer='llm', confidence=0.9,
                    items=[Item(type='reminder', text='Позвонить маме')])
    assert validate_candidate(request, result) is result


def test_grounding_still_rejects_unrelated_title():
    import pytest
    pytest.importorskip("openai")
    from app.ai.provider import InvalidResponse
    request = Input(text='запиши хоккей на пятницу', now=NOW)
    result = Result(intent='create', layer='llm', confidence=0.9,
                    items=[Item(type='task', text='Созвон с клиентом')])
    try:
        validate_candidate(request, result)
    except InvalidResponse:
        return
    raise AssertionError('Ungrounded title was accepted')
