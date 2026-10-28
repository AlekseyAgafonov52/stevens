"""Контракт v1.6 §4.5: экспорт, предпросмотр, атомарный импорт и отмена."""
from datetime import date, datetime, timedelta, timezone
import json
import os
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import chatlog, series
from app.database import get_db
from app.logic import calendar_import
from app.logic.record_import import Plan, build, restore, snapshot
from app.models import Account, ChatLog, Record, Sandbox, Series, TaskStatus, TaskType
from app.owner import Owner, bearer, get_owner
from app.routers.records import order_key
from app.storage.imports import ImportOperation
from app.templates import render

router = APIRouter(prefix="/api/records", tags=["import"])
MAX_RECORDS = 10000


async def import_owner(authorization: str | None = Header(default=None), x_client_id: str | None = Header(default=None),
                       db: AsyncSession = Depends(get_db)):
    if not authorization and not x_client_id:
        raise HTTPException(status_code=422, detail={"error": "invalid_request"})
    if authorization is not None and not bearer(authorization):
        raise HTTPException(status_code=401, detail={"error": "invalid_token"})
    return await get_owner(authorization=authorization, x_client_id=x_client_id, db=db)


def invalid(code: str = "invalid_fields"):
    return JSONResponse(status_code=422, content={"error": code})


async def owner_lock(db: AsyncSession, owner: Owner):
    if owner.account is not None:
        query = select(Account).where(Account.id == owner.account.id)
    else:
        query = select(Sandbox).where(Sandbox.client_id == owner.sandbox_id)
    await db.execute(query.with_for_update())


async def records(db: AsyncSession, owner: Owner, *, lock=False):
    query = select(Record).where(owner.filter(), Record.deleted_at.is_(None)).order_by(Record.id)
    if lock:
        query = query.with_for_update()
    return list((await db.execute(query)).scalars())


@router.get("/export")
async def export_records(owner: Owner = Depends(import_owner), db: AsyncSession = Depends(get_db)):
    rows = sorted(await records(db, owner), key=order_key)
    return {"version": 1, "exported_at": datetime.now(timezone.utc).isoformat(),
            "timezone": os.getenv("TZ", "Europe/Moscow"), "records": [r.to_contract() for r in rows]}


class AddPlan(Plan):
    """Только добавление (файл календаря или JSON без id): то, что уже есть, не трогаем и не удаляем."""

    def __init__(self) -> None:
        super().__init__()
        self.drafts: list[dict] = []  # повторы: создаём серией при применении
        self.same = 0                 # уже есть в Стивенсе или повторяется в файле
        self.skipped = 0              # отменённое и закончившиеся повторы из файла
        self.past = 0                 # прошедшее: добавим выполненным, чтобы не напоминало

    def counts(self) -> dict:
        return {"add": len(self.additions) + len(self.drafts), "update": 0, "delete": 0}

    def extra(self) -> dict:
        return {k: v for k, v in (("same", self.same), ("skipped", self.skipped), ("past", self.past)) if v}


def single_key(r) -> tuple:
    kind = r.type.value if hasattr(r.type, "value") else r.type
    return kind, (r.text or "").strip().lower(), r.date, r.time


async def add_plan(owner: Owner, db: AsyncSession, items: list, skipped: int = 0) -> AddPlan:
    plan = AddPlan()
    plan.skipped = skipped
    today = date.today().isoformat()
    have = {single_key(r) for r in await records(db, owner)}
    rows = (await db.execute(select(Series).where(series.owner_filter(owner), Series.ended.is_(False)))).scalars()
    have_series = {(s.type.value, s.text.strip().lower(), s.time, s.weekdays) for s in rows}
    for index, item in enumerate(items):
        skip = item.pop("_except", []) if isinstance(item, dict) else []
        one = build(owner, [], [item])
        for e in one.errors:
            plan.errors.append({**e, "index": index + 1})
        if one.errors or not one.additions:
            continue
        trial = one.additions[0]
        repeat = item.get("repeat")
        if repeat is not None:
            days = sorted(set(repeat["weekdays"]))
            key = (trial.type.value, trial.text.lower(), trial.time, ",".join(map(str, days)))
            if key in have_series:
                plan.same += 1
                continue
            have_series.add(key)
            plan.drafts.append({"type": trial.type.value, "text": trial.text, "time": trial.time,
                                "end_time": trial.end_time, "date": max(trial.date or "", date.today().isoformat()),
                                "repeat": {"days": days, "until": repeat.get("until")}, "except": set(skip)})
            continue
        if single_key(trial) in have:
            plan.same += 1
            continue
        have.add(single_key(trial))
        if trial.date and trial.date < today and "status" not in item \
                and trial.type in (TaskType.task, TaskType.reminder, TaskType.meeting):
            trial.status = TaskStatus.done  # прошлое уже было: без «просрочено» и пушей
            plan.past += 1
        plan.additions.append(trial)
    return plan


async def make_plan(body, owner, db, *, lock):
    if isinstance(body, dict) and isinstance(body.get("ics"), str):
        if not calendar_import.is_ics(body["ics"]):
            return invalid("bad_ics")
        local = calendar_import.zone(body.get("timezone") if isinstance(body.get("timezone"), str) else None) \
            or calendar_import.zone(os.getenv("TZ"))
        items, skipped = calendar_import.convert(body["ics"], date.today(), local)
        if not items:
            return invalid("empty_ics")
        if len(items) > MAX_RECORDS:
            return invalid()
        if lock:
            await owner_lock(db, owner)
        return await add_plan(owner, db, items, skipped)
    if not isinstance(body, dict) or not isinstance(body.get("records"), list) or not body["records"]:
        return invalid("empty_import")
    if len(body["records"]) > MAX_RECORDS:
        return invalid()
    if lock:
        await owner_lock(db, owner)
    if body.get("mode") == "add" or all(isinstance(i, dict) and i.get("id") is None for i in body["records"]):
        # Одни новые записи — добавляем к имеющимся, а не заменяем ими всё
        return await add_plan(owner, db, list(body["records"]))
    return build(owner, await records(db, owner, lock=lock), body["records"])


def extra(plan) -> dict:
    return plan.extra() if isinstance(plan, AddPlan) else {}


@router.post("/import/preview")
async def preview(body: object = Body(default=None), owner: Owner = Depends(import_owner), db: AsyncSession = Depends(get_db)):
    plan = await make_plan(body, owner, db, lock=False)
    if isinstance(plan, JSONResponse):
        return plan
    out = {**plan.counts(), **extra(plan), "errors": plan.errors}
    if isinstance(body, dict) and body.get("details") is True:
        out.update(details(plan))
    return out


def details(plan) -> dict:
    """Для окна импорта: сколько каких записей и первые строки списка «что будет»."""
    def row(action, kind, text, day, time, end, repeat=None):
        return {"action": action, "type": kind, "text": text, "date": day, "time": time, "end_time": end,
                "repeat": repeat}
    rows = [row("add", d["type"], d["text"], d["date"], d["time"], d["end_time"],
                {"weekdays": d["repeat"]["days"], "until": d["repeat"].get("until")})
            for d in getattr(plan, "drafts", [])]
    rows += [row("add", r.type.value, r.text, r.date, r.time, r.end_time) for r in plan.additions]
    rows += [row("update", r.type.value, v["text"], v["date"], v["time"], v["end_time"]) for r, v in plan.updates]
    rows += [row("delete", r.type.value, r.text, r.date, r.time, r.end_time) for r in plan.deletions]
    kinds: dict[str, int] = {}
    for r in rows:
        if r["action"] == "add":
            key = "repeat" if r["repeat"] else r["type"]
            kinds[key] = kinds.get(key, 0) + 1
    order = {"delete": 0, "update": 1, "add": 2}
    rows.sort(key=lambda r: (order[r["action"]], r["date"] or "9999", r["time"] or "99:99"))
    return {"kinds": kinds, "items": rows[:100]}


def log_import(db, owner, counts, template, operation_id):
    if chatlog.enabled():
        text, _ = render(template, counts)
        db.add(ChatLog(who=chatlog.who(owner), conversation_id=operation_id, source="button", text="",
                       action="import", kind="updated" if template == "import_done" else "deleted",
                       template=template, reply=text, records=sum(counts.values()), llm=False, ms=0))


@router.post("/import/apply")
async def apply(body: object = Body(default=None), owner: Owner = Depends(import_owner), db: AsyncSession = Depends(get_db)):
    plan = await make_plan(body, owner, db, lock=True)
    if isinstance(plan, JSONResponse):
        return plan
    if plan.errors:
        await db.rollback()
        return JSONResponse(status_code=422, content={**plan.counts(), **extra(plan), "errors": plan.errors})
    before = [snapshot(r) for r, _ in plan.updates] + [snapshot(r) for r in plan.deletions]
    for row, values in plan.updates:
        restore(row, values)
    now = datetime.now(timezone.utc)
    for row in plan.deletions:
        row.deleted_at = now
    counts = plan.counts()
    db.add_all(plan.additions)
    await db.flush()
    for draft in getattr(plan, "drafts", []):
        skip = draft.pop("except")
        _, made = await series.create(db, owner, draft, date.today(), commit=False)
        for r in made:
            if r.date in skip:
                r.deleted_at = now  # день, убранный в том календаре
        plan.additions += made
    affected = [r for r, _ in plan.updates] + plan.deletions + plan.additions
    operation_id = uuid4().hex
    await db.execute(delete(ImportOperation).where(ImportOperation.expires_at < now))
    db.add(ImportOperation(id=operation_id, owner_key=owner.key, expires_at=now + timedelta(hours=2),
        snapshot=json.dumps({"before": before, "after": [snapshot(r) for r in affected],
                             "added": [r.id for r in plan.additions], "counts": counts})))
    log_import(db, owner, counts, "import_done", operation_id)
    await db.commit()
    return {**counts, **extra(plan), "undo_id": operation_id}


@router.post("/import/undo")
async def undo(body: object = Body(default=None), owner: Owner = Depends(import_owner), db: AsyncSession = Depends(get_db)):
    if not isinstance(body, dict) or not isinstance(body.get("undo_id"), str) or len(body["undo_id"]) != 32:
        return invalid()
    await owner_lock(db, owner)
    operation = (await db.execute(select(ImportOperation).where(ImportOperation.id == body["undo_id"],
        ImportOperation.owner_key == owner.key).with_for_update())).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not operation or operation.consumed_at or operation.expires_at <= now:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    data = json.loads(operation.snapshot)
    ids = [s["id"] for s in data["after"]]
    found = list((await db.execute(select(Record).where(owner.filter(), Record.id.in_(ids)).with_for_update())).scalars())
    by_id = {r.id: r for r in found}
    if any(s["id"] not in by_id or snapshot(by_id[s["id"]]) != s for s in data["after"]):
        return invalid()  # Не затирать правки пользователя, сделанные после импорта.
    for old in data["before"]:
        restore(by_id[old["id"]], old)
    for rid in data["added"]:
        by_id[rid].deleted_at = now
    # Повторы из импорта больше не продлеваем
    await series.set_ended(db, owner, {by_id[rid].series_id for rid in data["added"] if by_id[rid].series_id}, True)
    operation.consumed_at = now
    log_import(db, owner, data["counts"], "import_undone", operation.id)
    await db.commit()
    return data["counts"]
