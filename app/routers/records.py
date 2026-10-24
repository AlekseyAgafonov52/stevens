"""REST для календаря и правки — раздел 15.5 контракта v1.4."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import DateKind, Record, TaskStatus, TaskType
from app import series
from app.owner import Owner, get_owner
from app.logic.record_validation import DATE_RE, TIME_RE, apply_patch, valid_date

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
    problem = apply_patch(record, body)
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
