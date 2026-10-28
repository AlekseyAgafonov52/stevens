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
