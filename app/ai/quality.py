"""Fail closed on damaged UTF-8 input and unsupported model substitutions."""
import re

class DamagedInput(ValueError):
    """Likely Cyrillic lost in a terminal/pipe encoding conversion."""


def validate_input(request):
    text = request.text
    # Windows PowerShell can replace Cyrillic with '?' when piping a here-string to docker.
    if "\ufffd" in text:
        raise DamagedInput("input_encoding_damaged: use a UTF-8 .py file or ASCII Unicode escapes")


def _tokens(text):
    return set(re.findall(r"[а-яёa-z]{3,}", text.casefold()))


def validate_candidate(request, result):
    """Reject clear hallucinations rather than silently writing wrong records."""
    # Read-only calendar questions must not be silently classified as off-topic.
    # This only requests another parse; it never creates or changes records.
    if result.intent in ("unknown", "off_topic") and re.search(
        r"\b(?:дел|задач|встреч|планов|планы|расписани|загружен|занят)\w*\b", request.text, re.I
    ) and re.search(r"\b(?:сколько|много|какие|что|как|насколько|есть|будет|у меня)\b", request.text, re.I):
        from app.ai.provider import InvalidResponse
        raise InvalidResponse("calendar_question_misclassified")
    # A command explicitly asking to create something is not a schedule listing.
    if result.intent == "list" and re.search(
        r"^\s*(?:поставь|запиши|создай|создать|напомни|запланируй|добавь\s+(?:задачу|встречу|напоминание))\b",
        request.text, re.I,
    ):
        from app.ai.provider import InvalidResponse
        raise InvalidResponse("creation_misclassified_as_list")
    if result.intent not in ("create", "note"):
        return result
    if result.intent == "create":
        from app.ai.decomposition import suspected_multiple, requested_count, _prepared, _segments, _has_time_hint
        from app import nlu
        if suspected_multiple(request.text):
            expected = nlu.parse_many(request.text, request.now)
            explicit = requested_count(request.text)
            parts = _segments(_prepared(request.text)[0])
            minimum = max(explicit or 2, len(expected) if expected else 2, len(parts))
            if len(result.items) < minimum:
                from app.ai.provider import InvalidResponse
                raise InvalidResponse("multi_actions_merged")
            # Do not let the model duplicate an item when a reliable count is
            # known. A guessed extra entry is as dangerous as a missing one.
            if (explicit or expected) and len(result.items) > (explicit or len(expected)):
                from app.ai.provider import InvalidResponse
                raise InvalidResponse("multi_actions_extra")
            if expected and len(result.items) == len(expected):
                for idx, (rule, candidate) in enumerate(zip(expected, result.items)):
                    if rule.date and candidate.date != rule.date.isoformat():
                        from app.ai.provider import InvalidResponse
                        raise InvalidResponse("multi_action_date_changed")
                    # An explicit exact time must be assigned to its own item.
                    if rule.time and not rule.time_ambiguous and not rule.time_guess and candidate.time != rule.time:
                        from app.ai.provider import InvalidResponse
                        raise InvalidResponse("multi_action_time_changed")
                    # With no temporal anchor in this clause, a new hour is a
                    # hallucination; vague dayparts are the only exception.
                    if (not rule.time and candidate.time and idx < len(parts)
                            and not _has_time_hint(parts[idx])):
                        from app.ai.provider import InvalidResponse
                        raise InvalidResponse("multi_action_time_invented")
                    if rule.type in ("meeting", "reminder") and candidate.type != rule.type:
                        from app.ai.provider import InvalidResponse
                        raise InvalidResponse("multi_action_type_changed")
    source = _tokens(request.text)
    if request.awaiting and request.awaiting.about:
        source |= _tokens(" ".join(str(v) for v in request.awaiting.about.values() if isinstance(v, str)))
    if request.focus:
        source |= _tokens(str(request.focus.get("text") or ""))
    for turn in request.history[-3:]:
        if isinstance(turn, dict):
            source |= _tokens(" ".join(str(v) for v in turn.values() if isinstance(v, str)))
    # A title has to overlap the actual request rather than a prompt example.
    # Allow common verb normalization (позвонить / звонок etc.) via stem prefixes.
    for item in result.items:
        title = _tokens(item.text)
        if title and source and not any(a[:4] == b[:4] for a in title for b in source):
            from app.ai.provider import InvalidResponse
            raise InvalidResponse("item_not_grounded_in_input")
    return result


# ── Даты и время считает код, а не модель ──
WEEKDAYS = {"понедельник": 0, "вторник": 1, "сред[ауы]": 2, "четверг": 3, "пятниц": 4, "суббот": 5, "воскресень": 6}
TIME_WORD_RE = re.compile(r"\d|час|полдень|полночь|полови|четверт|полтор|\b(?:один|одну|два|две|три|четыре|пять|шесть|семь|"
                          r"восемь|девять|десять|одиннадцать|двенадцать|двадцать|тридцать|сорок|пятьдесят)\b", re.I)
DAY_PART_RE = re.compile(r"утр|вечер|дн[её]м|\bдня\b|ноч|обед", re.I)
REMIND_START_RE = re.compile(r"^\s*(?:пожалуйста\s+)?напомина?й?(?:и|ите|те)?\b", re.I)


def _weekday_date(text, today):
    """«в ближайшую пятницу» → ближайшая пятница после сегодня. None — если дней недели нет, их несколько или «следующую»."""
    found = {i for stem, i in WEEKDAYS.items() if re.search(rf"\b{stem}(?:[а-яё]*)\b", text, re.I)}
    if len(found) != 1 or re.search(r"следующ|кажд|по\s+\w+(?:ам|ям)\b", text, re.I):
        return None
    from datetime import timedelta
    return today + timedelta(days=(found.pop() - today.weekday() - 1) % 7 + 1)


def ground_in_text(request, result):
    """Модель понимает смысл, а даты, время, повтор и тип «напомни» берём из правил, если правила их нашли.
    Lite ошибается в арифметике дат: «ближайшая пятница», «через 20 минут» в полночь, «следующая неделя»."""
    if request.awaiting is not None or result.intent not in ("create", "list", "free"):
        return result
    from app import nlu
    text, now = request.text, request.now
    if result.intent == "free":
        # «Завтра я занят с 9 до 18» — это занятость, а не поиск свободного времени
        rules = nlu.parse(text, now)
        if rules.intent == "create" and rules.type == "busy" and rules.date and rules.time and rules.end_time:
            return type(result).model_validate({"intent": "create", "layer": "llm", "confidence": result.confidence,
                "items": [{"type": "busy", "text": rules.text or "Занят", "date": rules.date.isoformat(),
                           "time": rules.time, "end_time": rules.end_time}]})
        return result
    time, _, _, info = nlu.parse_when(text, now)
    data = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    if result.intent == "list":
        if info.period:  # «следующая неделя» = пн–вс по календарю, а не как посчитала модель
            data["period"] = {"start": info.period.start.isoformat(), "end": info.period.end.isoformat(),
                              "label": result.period.label if result.period else info.period.label}
        return type(result).model_validate(data)
    rules = nlu.parse(text, now)
    if rules.intent == "create" and rules.type == "busy" and rules.time and rules.end_time:
        return result  # занятость правила разбирают сами, сюда не дойдёт
    items = data.get("items") or []
    repeat = nlu.parse_repeat(text, now)
    for item in items:
        if item.get("type") in ("note",):
            continue
        if REMIND_START_RE.match(text) and item.get("type") in ("task", "meeting") and len(items) == 1:
            item["type"] = "reminder"
        if len(items) == 1:
            relative = re.search(r"\bчерез\b", text, re.I)  # «через 20 минут» — считает код, в том числе через полночь
            if relative and time and info.date:
                item["date"], item["time"] = info.date.isoformat(), time
            elif not re.search(r"\bне\b[^,]*,\s*а\b", text, re.I) and (day := _weekday_date(text, now.date())):
                item["date"] = day.isoformat()  # «в ближайшую пятницу» — ближайшая пятница, а не вторник
            if repeat and repeat.days:  # дни повтора считают правила: Lite путает нумерацию (пн = 0)
                item["repeat"] = {**(item.get("repeat") or {}), "weekdays": repeat.days}
                if rules.date:
                    item["date"] = rules.date.isoformat()
        if item.get("time") and not TIME_WORD_RE.search(text) and not DAY_PART_RE.search(text):
            item.pop("time", None)  # времени в фразе нет — Стивенс спросит, а не поставит 09:00
            item.pop("time_guess", None)
        if item.get("time_guess") == "day_part" and not DAY_PART_RE.search(text):
            item.pop("time_guess", None)
    return type(result).model_validate(data)
