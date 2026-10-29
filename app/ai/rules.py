"""Rules entry point: the same v1.6 input/output as the LLM, with no storage access."""
from datetime import date
from pydantic import ValidationError

from app import nlu
from app.ai.schema import Change, Free, Input, Item, Period, Query, Repeat, Result, Target
from app.ai.contextual import refine


def from_parse(p: nlu.Parse, today: date) -> Result:
    intent = {"bye": "thanks", "bad_date": "unknown"}.get(p.intent, p.intent)
    period = (Period(start=p.period.start.isoformat(), end=p.period.end.isoformat(), label=p.period.label)
              if p.period else None)
    values: dict[str, object] = dict(intent=intent, layer="rules", confidence=0.0 if intent == "unknown" else
                  0.65 if nlu.needs_llm_review(p) else 0.95, doubts=p.doubt)
    if p.filter_type in ("task", "reminder", "meeting", "busy"):
        values["filter_type"] = p.filter_type
    if intent in ("create", "note"):
        values["items"] = ([Item.model_validate(dict(type=p.type or ("note" if intent == "note" else "task"), text=p.text,
            date=p.date.isoformat() if p.date else None, date_kind=p.date_kind,
            time=p.time, end_time=p.end_time, remind_before=p.remind_before,
            time_guess="ambiguous" if p.time_ambiguous else p.time_guess,
            repeat=Repeat(weekdays=p.repeat_days, until=p.until.isoformat() if p.until else None)
                   if p.repeat_days else None))] if p.text else [])
        if intent == "create" and not values["items"]:
            values.update(intent="unknown", confidence=0.0)
    if intent in ("list", "person"):
        values["period"] = period
    if intent == "list" and period is None:
        day = p.date or today
        values["period"] = Period(start=day.isoformat(), end=day.isoformat(), label=nlu.describe_period(day, day, today).label)
    query = Query.model_validate(dict(keywords=p.keywords, person=p.person, ask=p.ask, tense=p.tense,
                  type=p.filter_type, date=p.date.isoformat() if p.date else None))
    if intent in ("search", "person", "notes"):
        values["query"] = query
    if intent in ("delete", "complete", "move", "edit"):
        values["target"] = Target(ref="shown" if p.group else "focus" if p.ref else "query",
            query=query if not (p.group or p.ref) else None, date=p.date.isoformat() if p.date else None,
            time=p.time, all=p.bulk or p.all, count=p.group_count,
            index=p.ordinal - 1 if p.ordinal is not None and p.ordinal > 0 else p.ordinal,
            series="all" if p.series_all else "one" if p.series_one else None)
    if intent in ("move", "edit"):
        values["change"] = Change.model_validate(dict(date=p.date.isoformat() if p.date else None, time=p.time,
            shift_minutes=p.shift or None, text=p.new_text, type=p.new_type, remind_before=p.remind_before))
    if intent == "free":
        values["free"] = Free.model_validate(dict(mode="at" if p.time else {"windows": "slots"}.get(p.free_mode, p.free_mode),
            date=p.date.isoformat() if p.date else None, period=period, time=p.time,
            duration_min=p.duration, weekends=p.weekends))
    result = Result.model_validate(values)
    result._rule_parses = [p]
    return result


def parse(request: Input) -> Result:
    try:
        result = from_parse(nlu.parse(request.text, request.now), request.now.date())
        if result.intent == "create":
            many = nlu.parse_many(request.text, request.now)
            if many and len(many) > 1:
                # Re-evaluate confidence on the individual events. A single-item
                # parse of "... в 14 и ... в 17" appears uncertain because
                # it retains the second time inside the title. After a safe
                # split, that uncertainty no longer applies.
                pieces = [from_parse(item, request.now.date()) for item in many]
                result.items = [item for piece in pieces for item in piece.items]
                result.confidence = min(piece.confidence for piece in pieces)
                result.doubts = [doubt for piece in pieces for doubt in piece.doubts]
                result._rule_parses = many
        return refine(request, result)
    except ValidationError:
        # A rule result is subject to the same validation as a provider result.
        return Result(intent="unknown", layer="rules", confidence=0.0)
