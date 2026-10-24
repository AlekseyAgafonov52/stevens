"""Контракт v1.6 §4.5: экспорт, предпросмотр, атомарный импорт и отмена."""
from datetime import datetime, timedelta, timezone
import json
import os
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import chatlog
from app.database import get_db
from app.logic.record_import import build, restore, snapshot
from app.models import Account, ChatLog, Record, Sandbox
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


async def make_plan(body, owner, db, *, lock):
    if not isinstance(body, dict) or not isinstance(body.get("records"), list) or not body["records"]:
        return invalid("empty_import")
    if len(body["records"]) > MAX_RECORDS:
        return invalid()
    if lock:
        await owner_lock(db, owner)
    return build(owner, await records(db, owner, lock=lock), body["records"])


@router.post("/import/preview")
async def preview(body: object = Body(default=None), owner: Owner = Depends(import_owner), db: AsyncSession = Depends(get_db)):
    plan = await make_plan(body, owner, db, lock=False)
    if isinstance(plan, JSONResponse):
        return plan
    return {**plan.counts(), "errors": plan.errors}


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
        return JSONResponse(status_code=422, content={**plan.counts(), "errors": plan.errors})
    before = [snapshot(r) for r, _ in plan.updates] + [snapshot(r) for r in plan.deletions]
    for row, values in plan.updates:
        restore(row, values)
    now = datetime.now(timezone.utc)
    for row in plan.deletions:
        row.deleted_at = now
    db.add_all(plan.additions)
    await db.flush()
    affected = [r for r, _ in plan.updates] + plan.deletions + plan.additions
    operation_id = uuid4().hex
    await db.execute(delete(ImportOperation).where(ImportOperation.expires_at < now))
    db.add(ImportOperation(id=operation_id, owner_key=owner.key, expires_at=now + timedelta(hours=2),
        snapshot=json.dumps({"before": before, "after": [snapshot(r) for r in affected],
                             "added": [r.id for r in plan.additions], "counts": plan.counts()})))
    log_import(db, owner, plan.counts(), "import_done", operation_id)
    await db.commit()
    return {**plan.counts(), "undo_id": operation_id}


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
    operation.consumed_at = now
    log_import(db, owner, data["counts"], "import_undone", operation.id)
    await db.commit()
    return data["counts"]
