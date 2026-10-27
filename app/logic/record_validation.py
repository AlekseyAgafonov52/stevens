"""Общие инварианты записи: REST и импорт используют одну проверку."""
import enum
import re
from datetime import date

from app.models import DateKind, Record, TaskStatus, TaskType
from app.textfmt import shift_end

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def valid_date(value: str) -> bool:
    if not DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


# Какие поля есть у каждого типа (смена типа прячет лишние в stash и достаёт нужные обратно)
TYPE_FIELDS = {
    TaskType.task: {"date", "time", "date_kind", "status"},
    TaskType.reminder: {"date", "time", "status"},
    TaskType.meeting: {"date", "time", "end_time", "remind_before"},
    TaskType.busy: {"date", "time", "end_time"},
    TaskType.note: set(),
}
STASH_FIELDS = ("date", "time", "end_time", "remind_before", "date_kind", "status")


def stash_get(record: Record, field: str):
    value = getattr(record, field)
    return value.value if isinstance(value, enum.Enum) else value


def change_type(record: Record, new_type: TaskType, body: dict) -> None:
    """Сменить тип: поля, которых у нового типа нет, — в stash; нужные и пустые — из stash."""
    old_fields = TYPE_FIELDS[record.type] if record.type else set(STASH_FIELDS)
    new_fields = TYPE_FIELDS[new_type]
    stash = dict(record.stash or {})
    for field in STASH_FIELDS:
        if field in old_fields and field not in new_fields and stash_get(record, field) is not None:
            stash[field] = stash_get(record, field)
    for field in ("date", "time", "end_time", "remind_before", "status"):
        if field not in new_fields:
            continue
        if field in body:
            stash.pop(field, None)
        elif getattr(record, field) is None and field in stash:
            value = stash.pop(field)
            setattr(record, field, TaskStatus(value) if field == "status" else value)
    if new_type == TaskType.note:
        record.date, record.time = None, None
    if "end_time" not in new_fields:
        record.end_time = None
    if "remind_before" not in new_fields:
        record.remind_before = None
    record.status = (record.status or TaskStatus.open) if "status" in new_fields else None
    # Срок: у задачи вернуть «до …» / «без срока», у остальных — точная дата
    kind = stash.pop("date_kind", None) if new_type == TaskType.task else None
    if not record.date:
        record.date_kind = DateKind.none
    elif kind in ("exact", "deadline"):
        record.date_kind = DateKind(kind)
    elif record.date_kind != DateKind.deadline or new_type != TaskType.task:
        record.date_kind = DateKind.exact
    record.type = new_type
    record.stash = stash or None


def apply_patch(record: Record, body: dict, allow_type: bool = False) -> str | None:
    """Меняет запись по правилам 15.5. Возвращает код ошибки или None."""
    allowed = {"text", "date", "time", "end_time", "status", "remind_before"} | ({"type"} if allow_type else set())
    if not body or set(body) - allowed:
        return "invalid_fields"
    if "type" in body:
        try:
            new_type = TaskType(body["type"])
        except (ValueError, TypeError):
            return "invalid_fields"
        body = {k: v for k, v in body.items() if k != "type"}
        if new_type != record.type:
            change_type(record, new_type, body)
        if not body:
            body = {"text": record.text}
    text = body.get("text", record.text)
    if not isinstance(text, str) or not text.strip() or len(text.strip()) > 300:
        return "invalid_text"
    new_date = body["date"] if "date" in body else record.date
    new_time = body["time"] if "time" in body else record.time
    if new_date is not None and (not isinstance(new_date, str) or not valid_date(new_date)):
        return "invalid_date"
    if new_time is not None and (not isinstance(new_time, str) or not TIME_RE.match(new_time)):
        return "invalid_time"
    status = body.get("status")
    if "status" in body:
        if status not in ("open", "done") or record.type in (TaskType.note, TaskType.busy):
            return "invalid_status"

    remind = body.get("remind_before")
    if "remind_before" in body and (record.type != TaskType.meeting or isinstance(remind, bool)
                                    or not isinstance(remind, int) or not 0 <= remind <= 1440):
        return "invalid_remind_before"  # только у встречи, целое 0–1440

    if record.type == TaskType.note and (new_date is not None or new_time is not None):
        return "invalid_date"  # у заметки нет даты и времени
    new_end = body["end_time"] if "end_time" in body else record.end_time
    if "end_time" not in body and new_end and record.time and isinstance(new_time, str) and TIME_RE.match(new_time):
        new_end = shift_end(record.time, new_end, new_time)  # сдвинули начало — длина та же
    if new_end is not None and (not isinstance(new_end, str) or not TIME_RE.match(new_end)):
        return "invalid_time"
    if record.type == TaskType.busy and (new_end is None or new_end == new_time):
        return "date_time_required"  # у занятости есть и начало, и конец
    kind = record.date_kind
    if record.type in (TaskType.meeting, TaskType.reminder, TaskType.busy):
        # У встречи и напоминания дата и время обязательны
        if new_date is None or new_time is None:
            return "date_time_required"
        kind = DateKind.exact
    else:
        if "date" in body and new_date is None:
            new_time, kind = None, DateKind.none          # без срока
        elif new_date is None and new_time is not None:
            return "time_without_date"
        elif new_date is not None and record.date_kind == DateKind.none:
            kind = DateKind.exact                         # получила дату
        # deadline с новой датой остаётся deadline

    record.text = text.strip()
    record.date, record.time, record.date_kind = new_date, new_time, kind
    if "remind_before" in body:
        record.remind_before = remind
    record.end_time = new_end if record.type in (TaskType.busy, TaskType.meeting) and new_time else None
    if "status" in body:
        record.status = TaskStatus(status)
    return None



