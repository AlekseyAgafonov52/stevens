"""Conservative decomposition of multi-action Russian creation requests.

This module does not write records or call the LLM. Only split when there is
textual evidence of independent actions. If the split is plausible but cannot
be validated, the caller must request an LLM parse or clarification; NEVER
persist the original merged record as a confident rule result.
"""
from __future__ import annotations

import re
from datetime import datetime

I = re.IGNORECASE

# Distinguish explicit time anchors from other numbers ("два литра", "в два раза").
_TIME_WORDS = "час|часа|часов|раза|раз|этапа|этапе|урока|уроков"
CLOCK = re.compile(
    r"\b(?:в|во)\s+(?:[01]?\d|2[0-3])(?::[0-5]\d)?\b(?!\s*(?:" + _TIME_WORDS + r")\b)"
    r"|\b(?:в|во)\s+(?:час|два|две|три|четыре|пять|шесть|семь|восемь|девять|десять|одиннадцать|двенадцать)\b"
    r"(?!\s*(?:" + _TIME_WORDS + r")\b)", I,
)
DAYPART = re.compile(r"\b(?:утром|вечером|дн[её]м)\b", I)
ACTION_START = re.compile(
    r"^(?:напомни(?:ть|те)?|запиши|поставь|назначь|создай|добавь|"
    r"встреч[ау]|созвон|забрать|оплатить|отправить|позвонить|сходить|"
    r"проверить|сдать|передать|купить|написать|сделать|подготовить|"
    r"провести|заказать|обсудить|отметить)\b", I,
)
STARTS_PARTICIPANT = re.compile(r"^(?:с|со)\s+[А-ЯЁ][а-яё-]+\b")
COUNT_HEADER = re.compile(
    r"^\s*(?:поставь|запиши|создай|запланируй|назначь|добавь|составь)\s+"
    r"(?P<number>дв[ае]|три|четыре|пять|\d+)\s+"
    r"(?P<noun>занят(?:ия|ий)|встреч[и]|дел[а]|задач[и]|напоминани[яй])\b"
    r"(?P<when>[^:;]{0,90}):\s*(?P<body>.+)$", I,
)
# "..., напомни за полчаса" / "..., напомни завтра" only adds a reminder to the
# same record; "в 10 а нет в 11" is a correction, not a second event.
REMIND_TAIL = re.compile(
    r"^напомни(?:ть|те)?(?:\s+(?:мне|об?\s+этом|про\s+это|за\s+\S+(?:\s+\S+)?|завтра|сегодня|послезавтра|"
    r"утром|вечером|дн[её]м|(?:в|во)\s+\S+))*\s*$", I,
)
CORRECTION = re.compile(r"\bа\s+нет\b|\bне\s+в\s+\S+,?\s+а\s+в\b|\bнет,?\s+(?:в|во|на)\s", I)
SEPARATOR = re.compile(r",\s*(?:а\s+)?|\s+(?:и|а\s+также)\s+", I)
WORD_HOURS = {
    "час": "1", "два": "2", "две": "2", "три": "3", "четыре": "4",
    "пять": "5", "шесть": "6", "семь": "7", "восемь": "8",
    "девять": "9", "десять": "10", "одиннадцать": "11", "двенадцать": "12",
}
WORD_CLOCK = re.compile(r"\b(в|во)\s+(час|два|две|три|четыре|пять|шесть|семь|восемь|девять|десять|одиннадцать|двенадцать)\b(?!\s*(?:раза|раз|дня|литра|часа|часов)\b)", I)


def _normalized_hours(text: str) -> str:
    """Translate spelled-out hours only in the preposition+hour construction."""
    return WORD_CLOCK.sub(lambda m: m.group(1) + " " + WORD_HOURS[m.group(2).lower()], text)


def _has_clock(text: str) -> bool:
    return bool(CLOCK.search(text))


def _has_time_hint(text: str) -> bool:
    return _has_clock(text) or bool(DAYPART.search(text))


def _independent_right(left: str, right: str, *, comma: bool) -> bool:
    """A conjunction can also join names or shopping items: refuse those."""
    right = right.lstrip(" ,;:.—-")
    if not right:
        return False
    if REMIND_TAIL.match(right.rstrip(" .!")):
        return False
    if ACTION_START.match(right):
        # A second explicit action is independent, except a generic object
        # without a time following 'и' ("купить молоко и хлеб").
        return True
    if STARTS_PARTICIPANT.match(right) and _has_clock(left) and _has_clock(right):
        return True
    if _has_time_hint(left) and _has_time_hint(right):
        # "встреча в 14 и в 17" lacks a second title: ask, don't duplicate.
        if re.fullmatch(r"(?:в|во)\s+\S+(?:\s+час(?:ов|а)?)?", right, I):
            return False
        return bool(re.search(r"[а-яё]{3,}", re.sub(CLOCK, "", right), I))
    # Comma-separated infinitive actions without their own hour remain
    # ambiguous ("купить хлеб, молоко") and are left to LLM/clarification.
    return False


def _segments(text: str) -> list[str]:
    positions = []
    start = 0
    for m in SEPARATOR.finditer(text):
        left, right = text[start:m.start()], text[m.end():]
        if _independent_right(left, right, comma=m.group(0).lstrip().startswith(",")):
            positions.append((m.start(), m.end()))
            start = m.end()
    if not positions:
        return [text]
    pieces = []
    begin = 0
    for b, e in positions:
        pieces.append(text[begin:b].strip(" ,.;"))
        begin = e
    pieces.append(text[begin:].strip(" ,.;"))
    return [p for p in pieces if p]


def requested_count(text: str) -> int | None:
    m = COUNT_HEADER.match(text)
    if not m:
        return None
    val = {"два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5}.get(m.group("number").lower())
    return val if val is not None else int(m.group("number"))


def _prepared(text: str):
    text = " ".join(text.strip().split()).rstrip(".! ")
    match = COUNT_HEADER.match(text)
    if match:
        return match.group("body"), text[:match.start("body")], requested_count(text), match.group("noun").lower()
    return text, "", None, ""


def decompose(text: str, now: datetime):
    """Return list[nlu.Parse] only when there are 2..5 validated independent actions.

    None means no reliable structured split: callers use normal NLU for simple
    requests, or the LLM when `suspected_multiple` returns True.
    """
    from app import nlu  # lazy import because nlu.parse_many calls this module
    body, header, count, noun = _prepared(text)
    parts = _segments(body)
    if not 2 <= len(parts) <= 5 or (count is not None and count != len(parts)):
        return None
    parent_date = None
    if header:
        _, _, _, info = nlu.parse_when(header, now)
        parent_date = info.date
        if not parent_date and info.period:
            return None  # vague "next week": must choose a day explicitly
    parsed = []
    for index, clause in enumerate(parts):
        normalized = _normalized_hours(clause)
        if index > 0 and STARTS_PARTICIPANT.match(normalized):
            if not parsed or parsed[-1].type != "meeting":
                return None
            normalized = "встреча " + normalized
        if index == 0 and noun.startswith("встреч") and not re.search(nlu.MEETING_WORD_RE, normalized, I):
            normalized = "встреча " + normalized
        item = nlu.parse(normalized, now)
        if item.intent != "create" or not item.text:
            item = nlu.parse("запиши " + normalized, now)
        if item.intent != "create" or not item.text:
            return None
        # A shortened second clause inherits the command kind unless it
        # explicitly introduces a different kind of event.
        if index and parsed and parsed[0].type == "reminder" and item.type == "task" and not ACTION_START.match(normalized):
            item.type = "reminder"
        if not item.date:
            item.date = parent_date or (parsed[-1].date if parsed else None)
            if item.date:
                item.date_kind = "exact"
        # No title may be only a connective or an hour, and a meeting must
        # remain a meeting after its omitted verb is restored.
        if item.text.lower() in ("это", "и", "а", "встреча", "созвон"):
            return None
        if index > 0 and parts[index].lstrip().lower().startswith(("с ", "со ")) and item.type != "meeting":
            return None
        if (part := DAYPART.search(clause)) and item.time is None:
            # Existing Stevens convention: morning=09:00, day=13:00,
            # evening=19:00. Explicitly mark the interpretation as day_part,
            # and request LLM review instead of treating it as an exact hour.
            part_word = part.group(0).lower().replace("днем", "днём")
            item.time = {"утром": "09:00", "днём": "13:00", "вечером": "19:00"}[part_word]
            item.time_guess = "day_part"
            item.doubt.append({"why": "unclear"})
        parsed.append(item)
    if count is not None and count != len(parsed):
        return None
    return parsed


def suspected_multiple(text: str) -> bool:
    """Flag plausible compound commands to avoid one merged calendar record."""
    body, _, count, _ = _prepared(text)
    if count is not None and count >= 2:
        return True
    parts = _segments(body)
    if len(parts) >= 2:
        return True
    # Two separate time anchors with a conjunction are not automatically two
    # events, but the merged parse is unsafe without a model/clarification.
    if len(CLOCK.findall(body)) >= 2 and not CORRECTION.search(body) and re.search(r"\s+(?:и|а)\s+|,", body, I):
        return True
    return False
