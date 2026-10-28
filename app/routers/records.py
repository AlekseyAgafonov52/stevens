"""REST для календаря и правки."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import DateKind, Record, TaskStatus, TaskType
from app import series
from app.owner import Owner, get_owner
from app.logic.record_validation import apply_patch, valid_date

router = APIRouter(prefix="/api/records", tags=["records"])



def invalid(code: str = "invalid_fields") -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": code})


def not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "not_found"})


def order_key(record: Record):
    return (record.date or "9999-99-99", record.time or "99:99", record.id)


async def owned(db: AsyncSession, owner: Owner, record_id: int) -> Record | None:
    record = await db.get(Record, record_id)
    return record if record and owner.owns(record) else None


@router.get("")
async def list_records(
    from_: str = Query(alias="from"),
    to: str = Query(),
    owner: Owner = Depends(get_owner),
    db: AsyncSession = Depends(get_db),
):
    if not valid_date(from_) or not valid_date(to) or from_ > to:
        return invalid("invalid_period")
    await series.extend(db, owner, date.today())
    rows = (await db.execute(
        select(Record).where(owner.filter(), Record.deleted_at.is_(None), Record.date.is_not(None),
                             Record.date >= from_, Record.date <= to)
    )).scalars().all()
    return {"records": [r.to_contract() for r in sorted(rows, key=order_key)]}


@router.get("/{record_id}")
async def get_record(record_id: int, owner: Owner = Depends(get_owner), db: AsyncSession = Depends(get_db)):
    record = await owned(db, owner, record_id)
    if not record or record.deleted_at is not None:
        return not_found()
    return {"record": record.to_contract()}


CREATE_TYPES = {t.value: t for t in (TaskType.task, TaskType.reminder, TaskType.meeting, TaskType.busy)}


@router.post("", status_code=201)
async def create_record(
    body: object = Body(default=None),
    owner: Owner = Depends(get_owner),
    db: AsyncSession = Depends(get_db),
):
    """Новая запись из календаря: те же проверки, что у правки (apply_patch)."""
    if not isinstance(body, dict) or body.get("type") not in CREATE_TYPES:
        return invalid()
    kind = CREATE_TYPES[body["type"]]
    fields = {k: v for k, v in body.items() if k != "type"}
    fields.setdefault("text", "")
    record = owner.new_record(
        type=kind, text="", date=None, time=None, end_time=None, date_kind=DateKind.none,
        status=None if kind in (TaskType.meeting, TaskType.busy) else TaskStatus.open,
        created_at=datetime.now(timezone.utc),
    )
    problem = apply_patch(record, fields)
    if problem:
        return invalid(problem)
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return JSONResponse(status_code=201, content={"record": record.to_contract()})


@router.patch("/{record_id}")
async def patch_record(
    record_id: int,
    body: object = Body(default=None),
    owner: Owner = Depends(get_owner),
    db: AsyncSession = Depends(get_db),
):
    record = await owned(db, owner, record_id)
    if not record or record.deleted_at:
        return not_found()
    if not isinstance(body, dict):
        return invalid()
    problem = apply_patch(record, body, allow_type=True)
    if problem:
        await db.rollback()
        return invalid(problem)
    await db.commit()
    return {"record": record.to_contract()}


@router.delete("/{record_id}", status_code=204)
async def delete_record(record_id: int, owner: Owner = Depends(get_owner), db: AsyncSession = Depends(get_db)):
    record = await owned(db, owner, record_id)
    if not record:
        return not_found()
    if not record.deleted_at:
        record.deleted_at = datetime.now(timezone.utc)  # мягкое удаление
        await db.commit()
    return Response(status_code=204)


@router.post("/{record_id}/restore")
async def restore_record(record_id: int, owner: Owner = Depends(get_owner), db: AsyncSession = Depends(get_db)):
    record = await owned(db, owner, record_id)
    if not record:
        return not_found()
    record.deleted_at = None
    await db.commit()
    return {"record": record.to_contract()}
