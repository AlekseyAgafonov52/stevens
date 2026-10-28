"""Safe, DB-independent checks for the late-Oct Stevens regression batch.

Run: python -m pytest -q tests/test_bugfix_round2_offline.py
API checks are separate; a green unit suite is NOT a full API pass.
"""
import ast
from datetime import datetime
from pathlib import Path
import re
from types import SimpleNamespace

import pytest
from app import nlu

NOW = datetime.fromisoformat('2026-10-21T10:00:00+03:00')


@pytest.mark.parametrize('phrase,expected', [
    ('в субботу встреча с Машей с 16 до 17:30', ('create', 'meeting', 'Встреча с Машей', '16:00', '17:30')),
    ('встреча с Олегом прошла, отметь', ('complete', None, None, None, None)),
    ('напомни завтра в 20 учиться водить', ('create', 'reminder', 'Учиться водить', '20:00', None)),
    ('расскажи маме про отпуск завтра в 10', ('create', 'task', 'Расскажи маме про отпуск', '10:00', None)),
    ('поставь завтра в 9 зарядку на 15 минут', ('create', 'task', 'Зарядку на 15 минут', '09:00', None)),
    ('Напомни в ближайшую пятницу в 11:00 оплатить интернет', ('create', 'reminder', 'Оплатить интернет', '11:00', None)),
    ('Есть ли встречи сегодня?', ('list', None, None, None, None)),
    ('Во сколько встреча с Иваном?', ('search', None, None, None, None)),
])
def test_nlu_has_no_unsafe_mutation_routes(phrase, expected):
    p = nlu.parse(phrase, NOW)
    assert (p.intent, p.type, p.text, p.time, p.end_time) == expected


def test_self_correcting_create_uses_last_time():
    p = nlu.parse('напомни завтра не в 10, а в 11 позвонить маме', NOW)
    assert (p.intent, p.type, p.text, p.time) == (
        'create', 'reminder', 'Позвонить маме', '11:00')


def test_nearest_friday_does_not_invent_next_tuesday():
    t = datetime.fromisoformat('2026-10-27T10:00:00+03:00')
    p = nlu.parse('Напомни в ближайшую пятницу в 11:00 оплатить интернет', t)
    assert p.date.isoformat() == '2026-10-30'


def test_minutes_in_title_do_not_force_llm_review():
    p = nlu.parse('поставь завтра в 9 зарядку на 15 минут', NOW)
    assert not nlu.needs_llm_review(p)


def test_meeting_parsing_preserves_participant_and_interval():
    p = nlu.parse('в субботу встреча с Машей с 16 до 17:30', NOW)
    assert p.has_subject and p.date.isoformat() == '2026-10-24'


def test_one_record_bulk_confirmation_uses_accusative_case():
    # Extract the pure formatting function to test without importing database-backed
    # chat.py (the regular tests for it run against a separate PostgreSQL database).
    source = (Path(__file__).resolve().parents[1] / 'app/routers/chat.py').read_text()
    tree = ast.parse(source)
    func = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == 'bulk_delete_prompt')
    ns = {'re': re, 'Ctx': object}
    exec(compile(ast.Module(body=[func], type_ignores=[]), '<bulk_delete_prompt>', 'exec'), ns)
    ctx = SimpleNamespace(say=lambda *a, **k: ('Удалить 2 дела?', None))
    text, speech = ns['bulk_delete_prompt'](ctx, 1, 'на вс, 5 янв 2031', ('встреча', 'встречи', 'встреч'), 'meeting')
    assert text == 'Удалить 1 встречу на вс, 5 янв 2031? Вот она:'
    assert '1 встречу' in speech


@pytest.mark.parametrize('kind,noun,pronoun', [
    ('task', 'задачу', 'она'), ('reminder', 'напоминание', 'оно'),
    ('note', 'заметку', 'она'), ('busy', 'занятость', 'она')
])
def test_bulk_one_record_noun_forms(kind, noun, pronoun):
    source = (Path(__file__).resolve().parents[1] / 'app/routers/chat.py').read_text()
    tree = ast.parse(source)
    func = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == 'bulk_delete_prompt')
    ns = {'re': re, 'Ctx': object}
    exec(compile(ast.Module(body=[func], type_ignores=[]), '<bulk_delete_prompt>', 'exec'), ns)
    ctx = SimpleNamespace(say=lambda *a, **k: ('unused', None))
    text, _ = ns['bulk_delete_prompt'](ctx, 1, '', None, kind)
    assert f'1 {noun}?' in text and f'Вот {pronoun}:' in text


def test_updated_contract_keeps_one_record_confirmation():
    import json
    path = Path(__file__).resolve().parent / 'data/contract_v15_phrases.json'
    d = next(x for x in json.loads(path.read_text())['dialogs'] if x['id'] == 'Т12-13')
    steps = d['steps']
    assert [s['kind'] for s in steps[12:16]] == ['confirm', 'confirm', 'deleted', 'found']
    assert steps[14]['press'] == 'Да, удалить все'
