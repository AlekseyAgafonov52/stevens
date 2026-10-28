"""Contract JSON -> existing dialogue parser. No DB access or actions."""
from datetime import date

from app import nlu
from app.ai.schema import Result

SUPPORTED = {"create", "note", "list", "search", "person", "notes", "undated", "repeats", "free",
             "reply", "cancel", "greeting", "help", "thanks", "off_topic", "unknown"}
CREATE_TYPES = {"task", "meeting", "reminder", "note", "busy"}


def supported(result: Result) -> bool:
    """Mutations use the separate snapshot-bound confirmation flow, never this adapter."""
    return (result.intent in SUPPORTED and
            (result.intent != "create" or all(item.type in CREATE_TYPES for item in result.items)))


def to_parses(result: Result, today: date) -> list[nlu.Parse]:
    if result.layer == "rules" and result._rule_parses:
        return result._rule_parses
    if not supported(result) or result.confidence < 0.5:
        return [nlu.Parse()]
    if result.intent in ("create", "note") and result.items:
        parses = []
        for item in result.items:
            value = nlu.Parse(
                intent="create", type=item.type, text=item.text.strip(),
                date=date.fromisoformat(item.date) if item.date else None,
                date_kind=item.date_kind if item.type == "task" else "exact",
                time=item.time, end_time=item.end_time, remind_before=item.remind_before,
                time_ambiguous=item.time_guess == "ambiguous", time_guess=item.time_guess,
                repeat_days=item.repeat.weekdays if item.repeat else None,
                until=date.fromisoformat(item.repeat.until) if item.repeat and item.repeat.until else None,
                doubt=[d.model_dump(exclude_none=True) for d in result.doubts],
            )
            # Also protect direct adapter callers; a model must never bypass confirmation.
            if not any(d["why"] == "llm" for d in value.doubt):
                value.doubt.append({"why": "llm"})
            if item.time_guess == "day_part":
                value.part_word = {"09:00": "утром", "13:00": "днём", "19:00": "вечером"}.get(item.time or "")
            parses.append(value)
        return parses
    # No new generic confirmation flow for other intents in this stage.
    if result.confidence < 0.8:
        return [nlu.Parse()]
    value = nlu.Parse(intent=result.intent)
    value.filter_type = result.filter_type
    value.query_mode = result.query_mode
    if result.period:
        start, end = date.fromisoformat(result.period.start), date.fromisoformat(result.period.end)
        value.period = nlu.describe_period(start, end, today)
        value.period.label = result.period.label
    if result.query:
        query = result.query
        terms = " ".join([*query.keywords, *([query.person] if query.person else [])])
        value.keywords, value.required = nlu.search_keywords(terms)
        value.ask, value.tense = query.ask, query.tense
        value.filter_type = query.type or value.filter_type
        value.date = date.fromisoformat(query.date) if query.date else None
        value.person = query.person
    if result.free:
        free = result.free
        value.free_mode = {"slots": "windows", "at": "windows"}.get(free.mode, free.mode)
        value.date = date.fromisoformat(free.date) if free.date else None
        value.time, value.duration, value.window, value.weekends = free.time, free.duration_min, free.duration_min, free.weekends
        if free.period:
            value.period = nlu.describe_period(date.fromisoformat(free.period.start), date.fromisoformat(free.period.end), today)
    if result.reply:
        value.date = date.fromisoformat(result.reply.date) if result.reply.date else None
        value.time, value.text = result.reply.time, result.reply.text
    return [value]


def query_context(value: object) -> dict | None:
    """Only public query context; do not send internal dialogue state or owner credentials."""
    if not isinstance(value, nlu.Parse) or value.intent not in ("list", "search", "person", "notes"):
        return None
    period = ({"start": value.period.start.isoformat(), "end": value.period.end.isoformat(),
               "label": value.period.label} if value.period else None)
    return {"intent": value.intent, "period": period, "filter_type": value.filter_type,
            "query_mode": value.query_mode,
            "query": {"keywords": value.keywords, "person": value.person, "ask": value.ask,
                      "tense": value.tense, "type": value.filter_type,
                      "date": value.date.isoformat() if value.date else None}}
