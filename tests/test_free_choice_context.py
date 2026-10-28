"""Regression: a new event must not be hijacked by free-slot selection."""
import ast
from datetime import datetime
from pathlib import Path
import re

import pytest
from app import nlu

NOW = datetime.fromisoformat("2026-10-21T10:00:00+03:00")


def load_router_predicates():
    # Isolate pure functions from the database-backed chat router.
    path = Path(__file__).resolve().parents[1] / "app/routers/chat.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {"is_new_request", "is_new_event_after_free_choice"}
    parts = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(parts) == 2, "Chat router must expose both routing predicates"
    ns = {"nlu": nlu, "QUESTION_RE": re.compile(r"^(?:что у меня|покажи|есть ли|во сколько)\b", re.I)}
    exec(compile(ast.Module(body=parts, type_ignores=[]), str(path), "exec"), ns)
    return ns["is_new_event_after_free_choice"]


@pytest.mark.parametrize("phrase,expected", [
    ("в субботу встреча с Машей с 16 до 17:30", True),
    ("в субботу встреча с Машей", True),
    ("в субботу в 16 встреча", True),
    ("в субботу тренировка в 15", True),
    ("напомни в субботу в 16 позвонить папе", True),
    ("давай в 16", False),
    ("в субботу в 16", False),
    ("я свободен в субботу с 14 до 16?", False),
])
def test_new_calendar_command_is_not_slot_reply(phrase, expected):
    predicate = load_router_predicates()
    parsed = nlu.parse(phrase, NOW)
    assert predicate(parsed, phrase) is expected


def test_meeting_person_and_interval_survive_free_choice():
    predicate = load_router_predicates()
    phrase = "в субботу встреча с Машей с 16 до 17:30"
    p = nlu.parse(phrase, NOW)
    assert predicate(p, phrase)
    assert (p.intent, p.type, p.text, p.time, p.end_time) == (
        "create", "meeting", "Встреча с Машей", "16:00", "17:30")
