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
