"""Импорт и выгрузка: все записи одним JSON — чтобы разобрать расписание в другой ИИ и вернуть правки разом.

GET  /api/transfer/export          — JSON всех записей (повтор — одной строкой с id «s12»)
POST /api/transfer/import          — {"text": "<JSON>", "apply": false} — предпросмотр «добавлю N, изменю M, удалю K»;
                                     с "apply": true — применяет то, что без ошибок

Строка без id — новая запись, с id — правка, с "delete": true — удаление. Строки, которых нет в тексте, не трогаем.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import series
from app.database import get_db
from app.models import DateKind, Record, Series, TaskStatus, TaskType
from app.owner import Owner, get_owner
from app.routers.records import TIME_RE, apply_patch, order_key, valid_date
from app.textfmt import parse_date

router = APIRouter(prefix="/api/transfer", tags=["transfer"])

MAX_ITEMS = 1000
FIELDS = ("text", "date", "time", "end_time", "status", "remind_before")
TYPE_WORDS = {"задача": "task", "встреча": "meeting", "напоминание": "reminder", "заметка": "note",
              "занятость": "busy"}
DAY_WORDS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

HOW = ("Правила для правок: строка без id — новая запись; строка с id — правка этой записи (меняйте только нужные "
       "поля); чтобы удалить, добавьте \"delete\": true. Строки, которые вы уберёте из списка, останутся как были. "
       "type: task — задача, reminder — напоминание, meeting — встреча, busy — занятость (нужны time и end_time), "
       "note — заметка (без даты). date — ГГГГ-ММ-ДД, time и end_time — ЧЧ:ММ, у задачи без срока date: null. "
       "status: open или done (только у задач и напоминаний). Повтор: id вида \"s12\", repeat.weekdays — дни недели "
       "(0 — понедельник … 6 — воскресенье), repeat.until — последний день или null, from — с какого дня. "
       "Верните JSON целиком в том же виде.")


def error(code: str, detail: str = "") -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": code, "detail": detail})


def today_of(value: object) -> date:
    """День пользователя: из client_time, иначе сервера."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            pass
    return date.today()


def record_item(record: Record) -> dict:
    item = {"id": record.id, "type": record.type.value if record.type else "task", "text": record.text}
    if record.type != TaskType.note:
        item.update(date=record.date, time=record.time)
    if record.type in (TaskType.busy, TaskType.meeting) and record.end_time:
        item["end_time"] = record.end_time
    if record.type in (TaskType.task, TaskType.reminder):
        item["status"] = record.status.value if record.status else "open"
    if record.type == TaskType.meeting and record.remind_before is not None:
        item["remind_before"] = record.remind_before
    return item


def series_item(row: Series, first: str) -> dict:
    item = {"id": f"s{row.id}", "type": row.type.value, "text": row.text, "time": row.time}
    if row.end_time:
        item["end_time"] = row.end_time
    item["repeat"] = {"weekdays": series.weekdays_of(row), "until": row.until}
    item["from"] = first
    return item


@router.get("/export")
async def export(client_time: str | None = None, owner: Owner = Depends(get_owner), db: AsyncSession = Depends(get_db)):
    today = today_of(client_time)
    rows = (await db.execute(select(Record).where(owner.filter(), Record.deleted_at.is_(None)))).scalars().all()
    single = sorted([r for r in rows if not r.series_id], key=order_key)
    upcoming: dict[int, str] = {}
    for r in rows:
        if r.series_id and r.date and r.date >= today.isoformat():
            upcoming[r.series_id] = min(upcoming.get(r.series_id, r.date), r.date)
    repeats = []
    if upcoming:
        found = (await db.execute(select(Series).where(series.owner_filter(owner), Series.id.in_(upcoming),
                                                       Series.ended.is_(False)))).scalars().all()
        repeats = [series_item(s, upcoming[s.id]) for s in sorted(found, key=lambda s: upcoming[s.id])]
    return {"stevens": 1, "exported": today.isoformat(), "how": HOW,
            "records": repeats + [record_item(r) for r in single]}


# ── Разбор текста ─────────────────────────────────────

def read_json(text: str) -> object:
    """JSON из вставленного текста: с ```json, с лишними словами вокруг, с «ёлочками» и запятой в конце."""
    text = text.strip()
    if fence := re.search(r"```(?:json)?\s*(.*?)```", text, re.S):
        text = fence.group(1).strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise ValueError("нет фигурных или квадратных скобок")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    body = text[start:end + 1]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        fixed = re.sub(r"[“”„«»]", '"', body)
        fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError as exc:
            raise ValueError(f"строка {exc.lineno}: {exc.msg}") from exc


def items_of(data: object) -> list:
    """Список строк: {"records": [...]} или просто [...]; плюс "delete": [id, …] как короткая форма."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        raise ValueError("ожидался список записей")
    items = list(data.get("records") or [])
    for key in ("add", "update"):
        items += list(data.get(key) or [])
    for rid in data.get("delete") or []:
        items.append({"id": rid, "delete": True})
    if not items and ("text" in data or "id" in data):
        items = [data]  # одна запись без обёртки
    return items


def type_of(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    value = TYPE_WORDS.get(value, value)
    return value if value in TaskType.__members__ else None


def weekdays_of(value: object) -> list[int] | None:
    if not isinstance(value, list) or not value:
        return None
    days = []
    for day in value:
        if isinstance(day, str) and day.strip().lower()[:2] in DAY_WORDS:
            day = DAY_WORDS.index(day.strip().lower()[:2])
        if isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6:
            return None
        days.append(day)
    return sorted(set(days))


def series_id_of(value: object) -> int | None:
    if isinstance(value, str) and (m := re.fullmatch(r"s(\d+)", value.strip(), re.I)):
        return int(m.group(1))
    return None


class Plan:
    """Что сделаем: по строке на действие, ошибки — отдельно."""

    def __init__(self) -> None:
        self.items: list[dict] = []
        self.errors: list[dict] = []
        self.unchanged = 0
        self.later: list = []  # повторы создаём после остального: series.create сам сохраняет

    def add(self, action: str, item: dict, before: dict | None = None) -> None:
        self.items.append({"action": action, "record": item, **({"before": before} if before else {})})

    def fail(self, index: int, item: object, why: str) -> None:
        text = item.get("text") if isinstance(item, dict) else None
        self.errors.append({"index": index + 1, "text": text if isinstance(text, str) else None, "error": why})

    def summary(self) -> dict:
        count = {a: sum(1 for i in self.items if i["action"] == a) for a in ("add", "update", "delete")}
        return {**count, "unchanged": self.unchanged, "errors": self.errors, "items": self.items}


ERRORS = {
    "invalid_text": "нет текста или он длиннее 300 знаков",
    "invalid_date": "дата не в виде ГГГГ-ММ-ДД",
    "invalid_time": "время не в виде ЧЧ:ММ",
    "invalid_status": "status бывает open или done, и только у задач и напоминаний",
    "invalid_remind_before": "remind_before — минуты от 0 до 1440, только у встречи",
    "date_time_required": "нужны дата и время (у занятости — ещё end_time)",
    "time_without_date": "время без даты",
    "invalid_fields": "лишние поля",
}


def patch_body(item: dict) -> dict:
    return {k: item[k] for k in FIELDS if k in item}


def new_record(owner: Owner, kind: str, item: dict) -> tuple[Record | None, str | None]:
    record = owner.new_record(type=TaskType(kind), text=str(item.get("text") or "").strip() or "?",
                              date_kind=DateKind.none, created_at=datetime.now(timezone.utc),
                              status=None if kind in ("meeting", "busy", "note") else TaskStatus.open)
    body = patch_body(item)
    body.setdefault("text", item.get("text"))
    if kind == "note":
        body.pop("date", None), body.pop("time", None)
    problem = apply_patch(record, body)
    return (None, problem) if problem else (record, None)


async def plan_series_new(db: AsyncSession, owner: Owner, plan: Plan, index: int, item: dict, kind: str,
                          today: date, apply: bool) -> None:
    days = weekdays_of(item["repeat"].get("weekdays") if isinstance(item["repeat"], dict) else None)
    until = item["repeat"].get("until") if isinstance(item["repeat"], dict) else None
    start = item.get("from") or item.get("date") or today.isoformat()
    text = item.get("text")
    time, end = item.get("time"), item.get("end_time")
    if not days:
        return plan.fail(index, item, "repeat.weekdays — дни недели числами 0–6")
    if not isinstance(text, str) or not text.strip() or len(text) > 300:
        return plan.fail(index, item, ERRORS["invalid_text"])
    if kind == "note":
        return plan.fail(index, item, "заметка не повторяется")
    if (until is not None and (not isinstance(until, str) or not valid_date(until))) or not isinstance(start, str) \
            or not valid_date(start):
        return plan.fail(index, item, ERRORS["invalid_date"])
    if time is not None and (not isinstance(time, str) or not TIME_RE.match(time)) \
            or end is not None and (not isinstance(end, str) or not TIME_RE.match(end)):
        return plan.fail(index, item, ERRORS["invalid_time"])
    if kind in ("meeting", "reminder", "busy") and not time or kind == "busy" and (not end or end == time):
        return plan.fail(index, item, ERRORS["date_time_required"])
    draft = {"type": kind, "text": text.strip(), "time": time, "end_time": end if kind in ("busy", "meeting") else None,
             "date": max(start, today.isoformat()), "repeat": {"days": days, "until": until}}
    shown = {"type": kind, "text": draft["text"], "time": time, "end_time": draft["end_time"],
             "repeat": {"weekdays": days, "until": until}, "from": draft["date"]}
    plan.add("add", shown)
    if apply:
        plan.later.append(draft)


async def end_series(db: AsyncSession, owner: Owner, row: Series, today: date) -> list[Record]:
    rows = await series.upcoming(db, owner, row.id, today)
    stamp = datetime.now(timezone.utc)
    for r in rows:
        r.deleted_at = stamp
    row.ended = True
    return rows


async def plan_series_edit(db: AsyncSession, owner: Owner, plan: Plan, index: int, item: dict, sid: int,
                           today: date, apply: bool) -> None:
    row = (await db.execute(select(Series).where(series.owner_filter(owner), Series.id == sid))).scalars().first()
    if not row or row.ended:
        return plan.fail(index, item, f"повтора s{sid} нет")
    upcoming = await series.upcoming(db, owner, sid, today)
    first = upcoming[0].date if upcoming else today.isoformat()
    before = series_item(row, first)
    if item.get("delete") is True:
        plan.add("delete", before)
        if apply:
            await end_series(db, owner, row, today)
        return
    after = {**before, **{k: item[k] for k in ("text", "time", "end_time", "repeat", "from") if k in item}}
    if isinstance(after.get("repeat"), dict):
        after["repeat"] = {"weekdays": weekdays_of(after["repeat"].get("weekdays")) or before["repeat"]["weekdays"],
                           "until": after["repeat"].get("until")}
    if after == before:
        plan.unchanged += 1
        return
    if after["repeat"] != before["repeat"] or after["from"] != before["from"]:
        # Другие дни или начало — старый повтор закрываем, ставим новый
        mark = len(plan.items)
        await plan_series_new(db, owner, plan, index, {**after, "type": row.type.value}, row.type.value, today, apply)
        if len(plan.items) > mark:
            plan.items[-1] = {"action": "update", "record": plan.items[-1]["record"], "before": before}
            if apply:
                await end_series(db, owner, row, today)
        return
    text, time, end = after["text"], after["time"], after.get("end_time")
    if not isinstance(text, str) or not text.strip() or len(text) > 300:
        return plan.fail(index, item, ERRORS["invalid_text"])
    if (time is not None and (not isinstance(time, str) or not TIME_RE.match(time))) or \
            (end is not None and (not isinstance(end, str) or not TIME_RE.match(end))):
        return plan.fail(index, item, ERRORS["invalid_time"])
    if row.type == TaskType.busy and (not time or not end or end == time):
        return plan.fail(index, item, ERRORS["date_time_required"])
    plan.add("update", after, before)
    if apply:
        row.text, row.time, row.end_time = text.strip(), time, end
        for r in upcoming:
            r.text, r.time, r.end_time = row.text, time, end if row.type in (TaskType.busy, TaskType.meeting) else None


async def build(db: AsyncSession, owner: Owner, items: list, today: date, apply: bool) -> Plan:
    plan = Plan()
    ids = [i["id"] for i in items if isinstance(i, dict) and isinstance(i.get("id"), int) and not isinstance(i["id"], bool)]
    existing = {r.id: r for r in (await db.execute(select(Record).where(owner.filter(), Record.id.in_(ids)))).scalars()} \
        if ids else {}
    seen: set = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            plan.fail(index, item, "строка не в фигурных скобках")
            continue
        rid = item.get("id")
        if rid is not None and rid in seen:
            plan.fail(index, item, f"id {rid} встречается дважды")
            continue
        seen.add(rid)
        if (sid := series_id_of(rid)) is not None:
            await plan_series_edit(db, owner, plan, index, item, sid, today, apply)
            continue
        if rid is None:
            kind = type_of(item.get("type")) or ("busy" if item.get("end_time") and not item.get("type") else None)
            if not kind:
                plan.fail(index, item, "type: task, reminder, meeting, busy или note")
                continue
            if item.get("repeat"):
                await plan_series_new(db, owner, plan, index, item, kind, today, apply)
                continue
            record, problem = new_record(owner, kind, item)
            if problem:
                plan.fail(index, item, ERRORS.get(problem, problem))
                continue
            plan.add("add", record_item(record))
            if apply:
                db.add(record)
            continue
        record = existing.get(rid) if isinstance(rid, int) and not isinstance(rid, bool) else None
        if not record or record.deleted_at:
            plan.fail(index, item, f"записи с id {rid} нет")
            continue
        before = record_item(record)
        if item.get("delete") is True:
            plan.add("delete", before)
            record.deleted_at = datetime.now(timezone.utc)
            continue
        if (kind := type_of(item.get("type"))) and kind != before["type"]:
            plan.fail(index, item, "тип записи так не меняется — удалите её и добавьте новую")
            continue
        body = {k: v for k, v in patch_body(item).items() if before.get(k) != v}
        if not body:
            plan.unchanged += 1
            continue
        problem = apply_patch(record, body)
        if problem:
            plan.fail(index, item, ERRORS.get(problem, problem))
            continue
        plan.add("update", record_item(record), before)
    return plan


@router.post("/import")
async def import_records(body: object = Body(default=None), owner: Owner = Depends(get_owner),
                         db: AsyncSession = Depends(get_db)):
    if not isinstance(body, dict) or not isinstance(body.get("text"), str) or not body["text"].strip():
        return error("empty", "вставьте JSON")
    try:
        items = items_of(read_json(body["text"]))
    except (ValueError, AttributeError, TypeError) as exc:
        return error("bad_json", str(exc))
    if not items:
        return error("empty", "в JSON нет записей")
    if len(items) > MAX_ITEMS:
        return error("too_many", f"не больше {MAX_ITEMS} строк за раз")
    today = today_of(body.get("client_time"))
    apply = body.get("apply") is True
    plan = await build(db, owner, items, today, apply)
    if not apply:
        await db.rollback()  # предпросмотр: правки в сессии были только для проверки
        return {"applied": False, **plan.summary()}
    await db.commit()
    for draft in plan.later:
        await series.create(db, owner, draft, today)
    return {"applied": True, **plan.summary()}
