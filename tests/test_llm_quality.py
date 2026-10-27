import pytest
from datetime import datetime, timezone
from app.ai.schema import Input, Result, Item
from app.ai.quality import DamagedInput, validate_input, validate_candidate
from app.ai.provider import InvalidResponse

NOW = datetime(2026, 10, 28, 10, tzinfo=timezone.utc)

def test_reject_cyrillic_question_marks():
    with pytest.raises(DamagedInput):
        validate_input(Input(text="??????? ??????", now=NOW))

def test_accept_russian():
    validate_input(Input(text="Поставь хоккей на пятницу", now=NOW))

def test_reject_invented_title():
    request=Input(text="Поставь хоккей на пятницу в 18:00", now=NOW)
    result=Result(intent="create", items=[Item(type="meeting", text="Созвон с клиентом")], confidence=.9,layer="llm")
    with pytest.raises(InvalidResponse):
        validate_candidate(request,result)

def test_accept_correct_title():
    request=Input(text="Поставь хоккей на пятницу", now=NOW)
    result=Result(intent="create",items=[Item(type="task",text="Хоккей")],confidence=.9,layer="llm")
    assert validate_candidate(request,result) is result
