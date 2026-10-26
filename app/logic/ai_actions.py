"""LLM mutations are proposals bound to explicit owner-checked record snapshots.

Neither the provider nor its adapter can call this executor without a pending
proposal and a separate user confirmation. Changed records invalidate a proposal.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from app import features, nlu, series
from app.ai.schema import Result
from app.logic.record_import import snapshot
from app.logic.record_validation import apply_patch
from app.models import Record, TaskStatus, TaskType
from app.textfmt import shift_end

if TYPE_CHECKING:
    from app.routers.chat import Ctx

MUTATIONS = {"delete", "complete", "move", "edit", "fix", "undo"}


def enabled(result: Result) -> bool:
    return (features.on("f12") and (result.intent != "move" or features.on("f17"))
            and (not result.target or not result.target.series or features.on("f15")))


def permitted(ctx: Ctx, result: Result) -> bool:
    return enabled(result) and (result.intent != "delete" or "d2" in ctx.features) \
        and (result.intent != "complete" or "d3" in ctx.features)


def patch_record(record: Record, values: dict) -> str | None:
    values = dict(values)
    new_type = values.pop("type", None)
    if new_type:
        record.type = TaskType(new_type)
        record.status = None if record.type in (TaskType.meeting, TaskType.busy, TaskType.note) else TaskStatus.open
    return apply_patch(record, values or {"text": record.text})


async def propose(ctx: Ctx, result: Result, selected: list[Record] | None = None) -> dict:
    from app.routers import chat
    ctx.trace.update(intent=result.intent, layer="llm", confidence=result.confidence,
                     parse=result.model_dump(mode="json", by_alias=True),
                     doubts=[d.model_dump(exclude_none=True) for d in result.doubts])
    if result.intent not in MUTATIONS or result.confidence < 0.5 or not permitted(ctx, result):
        return chat.examples("not_understood", "not_understood", ctx, chat.EXAMPLES)
    target = result.target
    undo = None
    if selected is not None:
        rows = selected
    elif result.intent == "undo":
        undo = ctx.conv.undo
        ids = ctx.conv.bulk_deleted if undo and undo["id"] == "restore_all" else [undo.get("record_id")] if undo else []
        rows = await chat.records_by_ids(ctx, [rid for rid in ids if rid is not None])
        if undo and undo["id"] == "undo":
            expanded = []
            for row in rows:
                expanded += await series.upcoming(ctx.db, ctx.owner, row.series_id, ctx.today) if row.series_id else [row]
            rows = list({r.id: r for r in expanded}.values())
    elif target and target.ref == "shown":
        rows = await chat.records_by_ids(ctx, ctx.found)
    elif target is None or target.ref in ("focus", "last"):
        record = await chat.owned_record(ctx, ctx.conv.focus)
        rows = [record] if record else []
    else:
        conditions = []
        query = target.query
        if query and query.type:
            conditions.append(Record.type == TaskType(query.type))
        day = target.date or (query.date if query else None)
        if day:
            conditions.append(Record.date == day)
        if target.time:
            conditions.append(Record.time == target.time)
        if result.period:
            conditions += [Record.date >= result.period.start, Record.date <= result.period.end]
        if not conditions and not (query and (query.keywords or query.person)) and not target.all:
            return chat.reply("clarify", *ctx.say("clarify_generic"), awaiting=True, buttons=[chat.CANCEL])
        rows = await chat.owner_records(ctx, *conditions)
        if query:
            keys = nlu.keywords(" ".join([*query.keywords, query.person or ""]))
            rows = [r for r in rows if all(nlu.record_has(chat.record_words(r), key) for key in keys)]
    rows = [r for r in rows if ctx.owner.owns(r) and (result.intent == "undo" or r.deleted_at is None)]
    if not rows:
        return chat.reply("found", *ctx.say("found_none"), total=0)
    if selected is None and target and target.index is not None:
        ordered = chat.nearest_first(rows, ctx.now)
        index = target.index
        rows = ordered[index:index + 1] if index >= 0 else ordered[-1:]
        if not rows:
            return chat.reply("found", *ctx.say("found_none"), total=0)
    if len(rows) > 1 and not (target and (target.all or target.ref == "shown")) and result.intent != "undo":
        answer = chat.which_one(ctx, rows, "ai_select")
        assert ctx.conv.choices is not None
        ctx.conv.pending = chat.Pending("ai_select", {"result": result.model_dump(mode="json", by_alias=True),
                                                       "ids": ctx.conv.choices["ids"]})
        return answer
    if target and target.series == "all":
        if not features.on("f15"):
            return chat.examples("not_understood", "not_understood", ctx, chat.EXAMPLES)
        expanded = []
        for row in rows:
            expanded += await series.upcoming(ctx.db, ctx.owner, row.series_id, ctx.today) if row.series_id else [row]
        rows = list({r.id: r for r in expanded}.values())
    updates: dict[int, dict] = {}
    previews = []
    for record in rows:
        values: dict = {}
        change = result.change
        if result.intent == "complete":
            if record.type not in (TaskType.task, TaskType.reminder, TaskType.meeting):
                return chat.meeting_not_done(ctx, [record]) if record.type == TaskType.meeting else chat.reply(
                    "clarify", *ctx.say("completed_busy_no"), buttons=[chat.CANCEL])
            values["status"] = "done"
        elif result.intent in ("move", "edit", "fix"):
            if not change:
                return chat.reply("clarify", *ctx.say("clarify_generic"), awaiting=True, buttons=[chat.CANCEL])
            values = change.model_dump(exclude_none=True, by_alias=True)
            replacement = values.pop("replace", None)
            values.pop("restore", None)
            shift = values.pop("shift_minutes", None)
            if replacement:
                replaced = chat.replace_words(record.text, replacement["from"], replacement["to"])
                if not replaced:
                    return chat.reply("clarify", *ctx.say("clarify_generic"), awaiting=True, buttons=[chat.CANCEL])
                values["text"] = replaced
            if shift:
                if not record.date or not record.time:
                    return chat.reply("clarify", *ctx.say("clarify_generic"), awaiting=True, buttons=[chat.CANCEL])
                moment = datetime.fromisoformat(f"{values.get('date', record.date)}T{values.get('time', record.time)}") + timedelta(minutes=shift)
                values.update(date=moment.date().isoformat(), time=moment.strftime("%H:%M"))
            if result.intent == "move" and "time" in values and record.time and record.end_time:
                values["end_time"] = shift_end(record.time, record.end_time, values["time"])
            if not values:
                return chat.reply("clarify", *ctx.say("clarify_generic"), awaiting=True, buttons=[chat.CANCEL])
            day, time = values.get("date", record.date), values.get("time", record.time)
            if ("date" in values or "time" in values) and day and (day < ctx.today.isoformat() or (day == ctx.today.isoformat() and time and time <= ctx.now.strftime("%H:%M"))):
                return chat.reply("clarify", *ctx.say("clarify_date_past", {"when": day}), awaiting=True, buttons=[chat.CANCEL])
        # Validate a detached draft; preparing a confirmation cannot mutate ORM rows.
        draft = Record(type=record.type, text=record.text, date=record.date, time=record.time,
                       end_time=record.end_time, date_kind=record.date_kind, status=record.status,
                       remind_before=record.remind_before, repeat=record.repeat, series_id=record.series_id)
        if values and patch_record(draft, values):
            return chat.reply("clarify", *ctx.say("clarify_generic"), awaiting=True, buttons=[chat.CANCEL])
        updates[record.id] = values
        if result.intent in ("move", "edit", "fix"):
            previews.append(draft.to_contract(marks=["draft"]))
    data = {"result": result.model_dump(mode="json", by_alias=True), "ids": [r.id for r in rows],
            "before": {r.id: snapshot(r) for r in rows}, "updates": updates, "undo": undo}
    ctx.conv.pending = chat.Pending("ai_confirm", data)
    template = {"delete": "confirm_ai_delete", "complete": "confirm_ai_complete", "undo": "confirm_ai_undo"}.get(result.intent, "confirm_ai_change")
    return chat.reply("confirm", *ctx.say(template), total=len(rows), awaiting=True,
                      records=[r.to_contract() for r in rows[:chat.FOUND_LIMIT]] + previews[:chat.FOUND_LIMIT],
                      buttons=[chat.button_action("Да, верно", "confirm_yes"), chat.button_action("Нет", "cancel", style="secondary")])


async def execute(ctx: Ctx) -> dict:
    from app.routers import chat
    pending = ctx.conv.pending
    if not pending or pending.kind != "ai_confirm":
        return chat.reply("clarify", *ctx.say("clarify_generic"), buttons=[chat.CANCEL])
    data = pending.draft
    result = Result.model_validate(data["result"])
    ctx.trace.update(intent=result.intent, layer="llm", confidence=result.confidence,
                     parse=result.model_dump(mode="json", by_alias=True),
                     doubts=[d.model_dump(exclude_none=True) for d in result.doubts])
    if not permitted(ctx, result):
        return chat.examples("not_understood", "not_understood", ctx, chat.EXAMPLES)
    found = (await ctx.db.execute(chat.select(Record).where(ctx.owner.filter(), Record.id.in_(data["ids"])).with_for_update())).scalars().all()
    rows = list(found)
    if len(rows) != len(data["ids"]) or any(snapshot(r) != data["before"].get(r.id) for r in rows):
        ctx.conv.pending = None
        await ctx.db.rollback()
        return chat.reply("clarify", *ctx.say("ai_stale"), buttons=[chat.CANCEL])
    for record in rows:
        values = data["updates"][record.id]
        day, time = values.get("date", record.date), values.get("time", record.time)
        if ("date" in values or "time" in values) and day and (day < ctx.today.isoformat() or
                (day == ctx.today.isoformat() and time and time <= ctx.now.strftime("%H:%M"))):
            ctx.conv.pending = None
            await ctx.db.rollback()
            return chat.reply("clarify", *ctx.say("ai_stale"), buttons=[chat.CANCEL])
    ctx.conv.pending = None  # consume before any write; a repeated confirmation has no proposal
    if result.intent == "undo":
        action = data["undo"]
        if not action or action["id"] not in ("undo", "restore", "restore_all"):
            return chat.reply("clarify", *ctx.say("clarify_generic"), buttons=[chat.CANCEL])
        restoring = action["id"] != "undo"
        if ("d2" if restoring else "d10") not in ctx.features:
            return chat.examples("not_understood", "not_understood", ctx, chat.EXAMPLES)
        stamp = datetime.now(timezone.utc)
        for record in rows:
            record.deleted_at = None if restoring else stamp
        ids = {r.series_id for r in rows if r.series_id}
        if restoring:
            await series.set_ended(ctx.db, ctx.owner, ids, False)
        else:
            await ctx.db.flush()
            remaining = await chat.owner_records(ctx, Record.series_id.in_(ids), Record.date >= ctx.today.isoformat()) if ids else []
            await series.set_ended(ctx.db, ctx.owner, ids - {r.series_id for r in remaining}, True)
        await ctx.db.commit()
        ctx.conv.bulk_deleted = [] if restoring else data["ids"]
        return chat.reply("created" if restoring else "deleted",
            *ctx.say("bulk_restored" if restoring else "bulk_deleted", {"count": len(rows)}), total=len(rows),
            records=[r.to_contract(marks=["new"] if restoring else ["deleted"]) for r in rows[:chat.FOUND_LIMIT]],
            buttons=[] if restoring else [chat.button_action("Вернуть все", "restore_all", style="secondary")])
    stamp = datetime.now(timezone.utc)
    for record in rows:
        if result.intent == "delete":
            record.deleted_at = stamp
        elif patch_record(record, data["updates"][record.id]):
            await ctx.db.rollback()
            return chat.reply("clarify", *ctx.say("ai_stale"), buttons=[chat.CANCEL])
    if result.intent == "delete":
        await ctx.db.flush()
        ids = {r.series_id for r in rows if r.series_id}
        remaining = await chat.owner_records(ctx, Record.series_id.in_(ids), Record.date >= ctx.today.isoformat()) if ids else []
        await series.set_ended(ctx.db, ctx.owner, ids - {r.series_id for r in remaining}, True)
        ctx.conv.bulk_deleted = data["ids"]
    await ctx.db.commit()
    ctx.conv.focus = rows[0].id if result.intent != "delete" else None
    if result.intent == "delete":
        return chat.reply("deleted", *ctx.say("bulk_deleted", {"count": len(rows)}), total=len(rows),
                          records=[r.to_contract(marks=["deleted"]) for r in rows[:chat.FOUND_LIMIT]],
                          buttons=[chat.button_action("Вернуть все", "restore_all", style="secondary")])
    return chat.reply("completed" if result.intent == "complete" else "updated", *ctx.say("ai_changed"),
                      total=len(rows), records=[r.to_contract(marks=["new"]) for r in rows[:chat.FOUND_LIMIT]])
