"""Планирование импорта v1.6: проверки без изменения ORM-объектов."""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.models import DateKind, Record, TaskStatus, TaskType
from app.owner import Owner
from app.logic.record_validation import apply_patch, valid_date

FIELDS = ("type", "text", "date", "time", "end_time", "remind_before", "date_kind", "status",
          "created_at", "deleted_at", "series_id", "repeat", "demo")
CONTRACT_FIELDS = {"id", "type", "text", "date", "time", "end_time", "remind_before", "date_kind", "status",
                   "created_at", "repeat", "demo", "marks", "highlight", "stash"}


def snapshot(record: Record) -> dict:
    out: dict[str, object] = {"id": record.id}
    for key in FIELDS:
        value = getattr(record, key)
        out[key] = value.isoformat() if isinstance(value, datetime) else getattr(value, "value", value)
    return out


def restore(record: Record, data: dict) -> None:
    for key in FIELDS:
        value = data[key]
        if key in ("created_at", "deleted_at") and value is not None:
            value = datetime.fromisoformat(value)
        if key == "type" and value is not None:
            value = TaskType(value)
        if key == "status" and value is not None:
            value = TaskStatus(value)
        if key == "date_kind":
            value = DateKind(value)
        setattr(record, key, value)


@dataclass
class Plan:
    additions: list[Record] = field(default_factory=list)
    updates: list[tuple[Record, dict]] = field(default_factory=list)
    deletions: list[Record] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def fail(self, index: int, key: str, code: str) -> None:
        self.errors.append({"index": index + 1, "field": key, "code": code})

    def counts(self) -> dict:
        return {"add": len(self.additions), "update": len(self.updates), "delete": len(self.deletions)}


def build(owner: Owner, existing: list[Record], items: list) -> Plan:
    plan = Plan()
    by_id = {r.id: r for r in existing}
    seen = set()
    kept = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict) or set(item) - CONTRACT_FIELDS:
            plan.fail(index, "records", "invalid_fields")
            continue
        rid = item.get("id")
        if rid is not None and (isinstance(rid, bool) or not isinstance(rid, int) or not 1 <= rid <= 2147483647):
            plan.fail(index, "id", "invalid_fields")
            continue
        if rid is not None:
            if rid in seen:
                plan.fail(index, "id", "invalid_fields")
                continue
            seen.add(rid)
        current = by_id.get(rid) if rid is not None else None
        if current:
            kept.add(current.id)
            trial = Record()
            restore(trial, snapshot(current))
            trial.id = current.id
            if "type" in item and item["type"] != (current.type.value if current.type else None):
                plan.fail(index, "type", "invalid_fields")
                continue
            if "repeat" in item and item["repeat"] != current.repeat_contract():
                plan.fail(index, "repeat", "invalid_fields")
                continue
        else:
            try:
                kind = TaskType(item["type"]) if item.get("type") is not None else None
                date_kind = DateKind(item.get("date_kind", "none"))
            except (ValueError, TypeError):
                plan.fail(index, "type", "invalid_fields")
                continue
            trial = owner.new_record(type=kind, text="", date_kind=date_kind, demo=False,
                                     status=TaskStatus.open if kind in (TaskType.task, TaskType.reminder) else None,
                                     created_at=datetime.now(timezone.utc))
            if item.get("repeat") is not None:
                repeat = item["repeat"]
                if (not isinstance(repeat, dict) or set(repeat) - {"weekdays", "until"}
                        or not isinstance(repeat.get("weekdays"), list) or not repeat["weekdays"]
                        or any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in repeat["weekdays"])
                        or repeat.get("until") is not None and (not isinstance(repeat["until"], str) or not valid_date(repeat["until"]))):
                    plan.fail(index, "repeat", "invalid_fields")
                    continue
                repeat_text = ",".join(map(str, sorted(set(repeat["weekdays"]))))
                if repeat.get("until"):
                    repeat_text += ";" + repeat["until"]
                trial.repeat = repeat_text
                # Импортирует один день, не создает и не меняет серию целиком (§7 Ф26).
        body = {k: item[k] for k in ("text", "date", "time", "end_time", "status", "remind_before")
                if k in item and (current is None or item[k] != getattr(current, k))}
        if trial.type not in (TaskType.task, TaskType.reminder) and body.get("status") is None:
            body.pop("status", None)
        if trial.type != TaskType.meeting and body.get("remind_before") is None:
            body.pop("remind_before", None)
        if not body:
            if current is None:
                plan.fail(index, "text", "invalid_text")
            continue
        problem = apply_patch(trial, body)
        if problem:
            key = {"invalid_text": "text", "invalid_date": "date", "invalid_time": "time",
                   "invalid_status": "status", "invalid_remind_before": "remind_before",
                   "date_time_required": "time", "time_without_date": "time"}.get(problem, "records")
            plan.fail(index, key, problem)
            continue
        if current and "date_kind" in item and item["date_kind"] not in (current.date_kind.value, trial.date_kind.value):
            plan.fail(index, "date_kind", "invalid_fields")
            continue
        if current is None:
            plan.additions.append(trial)
        elif snapshot(trial) != snapshot(current):
            plan.updates.append((current, snapshot(trial)))
    plan.deletions = [r for r in existing if r.id not in kept]
    return plan
