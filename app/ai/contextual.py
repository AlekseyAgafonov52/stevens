"""Contract JSON for contextual replies and named lesson cancellations."""
import re
from datetime import datetime

from app import nlu
from app.ai.schema import Input, Period, Query, Reply, Result, Target


def whole_series_cancellation(raw: str, now: datetime) -> Result | None:
    """An explicit permanent cancellation names a series, not its focused day."""
    match = re.fullmatch(
        r"(?P<subject>.+?)\s+больше\s+не\s+будет\s*[,;.!—–-]?\s*"
        r"(?:убери(?:те)?|удали(?:те)?|отмени(?:те)?|вычеркни(?:те)?)\s+"
        r"вс[её]\s+(?:занятия|уроки|встречи|напоминания|задачи)[.!?]*", raw.strip(), re.I)
    if not match:
        return None
    subject = match["subject"]
    time, _, _, info = nlu.parse_when(subject, now)
    keys = nlu.keywords(subject)
    if not keys or time or info.date or info.period:
        return None  # A dated exception must not silently cancel an entire series.
    return Result(intent="delete", layer="rules", confidence=0.99,
                  target=Target(ref="query", query=Query(keywords=keys), series="all"))


def refine(request: Input, result: Result) -> Result:
    raw = request.text.strip()
    cancellation = re.fullmatch(
        r"(?P<body>.+?)\s+не\s+будет(?:\s*[,;.!—–-]?\s*"
        r"(?:вычеркни(?:те)?|убери(?:те)?|удали(?:те)?|отмени(?:те)?)(?:\s+(?:эту\s+)?"
        r"(?:задачу|напоминание|занятие|урок|встречу))?)?[.!?]*", raw, re.I)
    contextual = None
    last = request.last_query or {}
    if last.get("intent") == "list" and last.get("period") and re.fullmatch(
            r"(?:а\s+)?(?:встречи|задачи|напоминания)[\s?!.]*", raw, re.I):
        contextual = Result.model_validate(dict(intent="list", layer="rules", confidence=0.95,
                            period=Period.model_validate(last["period"]), filter_type=nlu._filter_type(raw.lower()),
                            query_mode=last.get("query_mode")))
    elif result.intent == "list" and last.get("intent") == "list" and result._rule_parses \
            and result._rule_parses[0].only_when and not result.filter_type:
        contextual = Result.model_validate({**result.model_dump(), "filter_type": last.get("filter_type"),
                                            "query_mode": last.get("query_mode")})
    if cancellation and not nlu.CREATE_VERB_RE.search(cancellation["body"].lower()):
        body = cancellation["body"]
        named = bool(re.search(r"\bрепетитор[а-яё]*\b", body, re.I))
        generic = bool(re.search(r"\b(?:заняти[еяй]|урок(?:а|ов)?|встреч(?:а|и)?)\s*$", body, re.I))
        if named or generic:
            time, _, time_spans, info = nlu.parse_when(body, request.now)
            title = re.sub(r"\b(?:заняти[а-яё]*|урок[а-яё]*|репетитор[а-яё]*)\b", " ",
                           nlu._cut(body, info.spans + time_spans), flags=re.I)
            contextual = Result(intent="delete", layer="rules", confidence=0.95,
                target=Target(ref="query" if named else "focus", time=time,
                              date=info.date.isoformat() if info.date else None,
                              query=Query(keywords=["репетитор", *nlu.keywords(title)]) if named else None),
                period=Period(start=info.period.start.isoformat(), end=info.period.end.isoformat(),
                              label=info.period.label) if info.period else None)
    if contextual is None and request.awaiting and result.intent in ("unknown", "create", "list"):
        time, _, _, info = nlu.parse_when(raw, request.now)
        if time or info.date:
            contextual = Result(intent="reply", layer="rules", confidence=0.95,
                reply=Reply(kind="day_time" if time and info.date else "time" if time else "day",
                            date=info.date.isoformat() if info.date else None, time=time))
        elif re.fullmatch(r"(?:да|ага|верно|подтверждаю)[\s,.!]*", raw, re.I):
            contextual = Result(intent="reply", layer="rules", confidence=0.95, reply=Reply(kind="yes"))
        elif re.fullmatch(r"(?:нет|неа)[\s,.!]*", raw, re.I):
            contextual = Result(intent="reply", layer="rules", confidence=0.95, reply=Reply(kind="no"))
    if contextual:
        contextual._rule_parses = result._rule_parses
        return contextual
    return result
