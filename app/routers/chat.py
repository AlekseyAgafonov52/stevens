"""POST /api/chat — разделы 4–8 и 15 контракта v1.4.

Разбор фразы — app/nlu.py (правила) и, если правила не поняли, LLM (brain.py).
Даты, проверки, действия и тексты ответов — здесь, по шаблонам раздела 9.
"""
from __future__ import annotations

import os
import time as clock
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import nlu
from app.database import get_db
from app.models import DateKind, Record, TaskStatus, TaskType
from app.owner import Owner, get_owner
from app.schemas import ChatRequest
from app.templates import render
from app.textfmt import (
    MONTHS_GEN, TYPE_FORMS, TYPE_GEN_PLURAL, TYPE_WORD, capitalize, client_now, date_speech, date_text, parse_date, plural,
    when_text,
)

router = APIRouter(prefix="/api", tags=["chat"])

EXAMPLES = [
    "Напомни завтра в 10 утра позвонить Ивану",
    "Что у меня на следующей неделе?",
    "Найди задачу про презентацию",
]
HELP_EXAMPLES = EXAMPLES + ["Поставь встречу с Иваном завтра", "Что у меня с Иваном?"]
FOUND_LIMIT = 50
WHICH_LIMIT = 5


# ── Память диалога: незавершённое уточнение по conversation_id (Р-45) ──

@dataclass
class Pending:
    kind: str                      # draft | confirm | conflict | new_time | confirm_no | multi | multi_ask | move | move_when
    draft: dict = field(default_factory=dict)


@dataclass
class Conversation:
    pending: Pending | None = None
    variants: dict[str, int] = field(default_factory=dict)
    focus: int | None = None       # о какой записи шла речь: «перенеси её», «удали это»
    touched: float = field(default_factory=clock.time)


CONVERSATIONS: dict[tuple[str, str], Conversation] = {}
CONVERSATION_TTL = 2 * 3600


def conversation(owner: Owner, conversation_id: str) -> Conversation:
    now = clock.time()
    if len(CONVERSATIONS) > 5000:
        for key in [k for k, v in CONVERSATIONS.items() if now - v.touched > CONVERSATION_TTL]:
            del CONVERSATIONS[key]
    item = CONVERSATIONS.setdefault((owner.key, conversation_id), Conversation())
    item.touched = now
    return item


def forget(owner_key: str) -> None:
    """Сброс песочницы — забываем и незавершённые уточнения."""
    for key in [k for k in CONVERSATIONS if k[0] == owner_key]:
        del CONVERSATIONS[key]


# ── Сборка ответа ─────────────────────────────────────

def button_text(label: str, text: str | None = None, style: str | None = None) -> dict:
    button = {"label": label, "send": {"text": text or label}}
    if style:
        button["style"] = style
    return button


def button_action(label: str, action_id: str, record_id: int | None = None, style: str | None = None) -> dict:
    action = {"id": action_id}
    if record_id is not None:
        action["record_id"] = record_id
    button = {"label": label, "send": {"action": action}}
    if style:
        button["style"] = style
    return button


CANCEL = button_action("Отменить", "cancel", style="secondary")


def reply(kind: str, text: str, speech: str | None = None, *, records=None, nearest=None, total=None,
          awaiting: bool = False, buttons=None) -> dict:
    return {
        "message_id": f"m-{uuid4().hex[:10]}",
        "kind": kind,
        "text": text,
        "speech": speech,
        "records": records or [],
        "nearest": nearest,
        "total": total,
        "awaiting_reply": awaiting,
        "buttons": buttons or [],
    }


@dataclass
class Ctx:
    owner: Owner
    db: AsyncSession
    conv: Conversation
    now: datetime
    features: set[str]

    @property
    def today(self) -> date:
        return self.now.date()

    def say(self, template_id: str, values: dict | None = None, speech_values: dict | None = None,
            count_forms=None) -> tuple[str, str | None]:
        return render(template_id, values, speech_values, count_forms, self.conv.variants)

    def record_values(self, record: dict) -> tuple[dict, dict]:
        """{text} {when} {date} {time} для text и для speech."""
        value = parse_date(record.get("date"))
        text_vals = {"text": record["text"], "when": when_text(record, self.today), "time": record.get("time") or ""}
        speech_vals = {"when": when_text(record, self.today, speech=True)}
        if value:
            text_vals["date"] = date_text(value, self.today)
            speech_vals["date"] = date_speech(value, self.today)
        return text_vals, speech_vals


# ── Записи ────────────────────────────────────────────

def draft_record(draft: dict, marks: list[str]) -> dict:
    """Черновик в формате Record: id null, метка draft (раздел 6)."""
    return {
        "id": None, "type": draft["type"], "text": draft["text"], "date": draft.get("date"),
        "time": draft.get("time"), "date_kind": draft["date_kind"],
        "status": None if draft["type"] == "meeting" else "open",
        "created_at": None, "marks": marks, "highlight": None,
    }


async def owner_records(ctx: Ctx, *conditions) -> list[Record]:
    rows = await ctx.db.execute(select(Record).where(ctx.owner.filter(), Record.deleted_at.is_(None), *conditions))
    return list(rows.scalars().all())


def moment(record: Record) -> str:
    return f"{record.date or '9999-99-99'} {record.time or '00:00'}"


def is_future(record: Record, now: datetime) -> bool:
    if not record.date:
        return False
    if record.date != now.strftime("%Y-%m-%d"):
        return record.date > now.strftime("%Y-%m-%d")
    return not record.time or record.time >= now.strftime("%H:%M")


def record_words(record: Record) -> list[str]:
    return [w.strip(".,:;!?«»\"()") for w in record.text.replace("-", " ").split()]


def matches(record: Record, keys: list[str]) -> int:
    words = record_words(record)
    return sum(1 for key in keys if nlu.record_has(words, key))


def nearest_first(records: list[Record], now: datetime) -> list[Record]:
    """Ближайшие будущие по возрастанию, затем прошедшие от поздних к ранним."""
    future = sorted([r for r in records if is_future(r, now)], key=moment)
    past = sorted([r for r in records if not is_future(r, now)], key=moment, reverse=True)
    return future + past


async def find(ctx: Ctx, p: nlu.Parse, types: set[str] | None = None) -> list[Record]:
    conditions = []
    if p.filter_type:
        conditions.append(Record.type == TaskType(p.filter_type))
    elif types:
        conditions.append(Record.type.in_([TaskType(t) for t in types]))
    if p.period:
        conditions += [Record.date >= p.period.start.isoformat(), Record.date <= p.period.end.isoformat()]
    if p.date:
        conditions.append(Record.date == p.date.isoformat())
    rows = await owner_records(ctx, *conditions)
    if not p.keywords:
        return rows if (p.filter_type or p.period or p.date) else []
    if p.required:
        rows = [r for r in rows if all(nlu.record_has(record_words(r), key) for key in p.required)]
    scored = [(matches(r, p.keywords), r) for r in rows]
    best = [r for score, r in scored if score == len(p.keywords)]
    return best or [r for score, r in scored if score > 0]


# ── Создание: проверки раздела 8 ──────────────────────

def clarify(ctx: Ctx, template_id: str, draft: dict, quick: list[tuple[str, str]] | None = None,
            values: dict | None = None) -> dict:
    # Вопрос храним в черновике: непонятный ответ — задаём его ещё раз, контекст не теряем
    draft = {**draft, "ask": {"template": template_id, "values": values, "quick": quick}}
    ctx.conv.pending = Pending("draft", draft)
    text, speech = ctx.say(template_id, values)
    buttons = [button_text(label, send) for label, send in (quick or [])] + [CANCEL]
    return reply("clarify", text, speech, awaiting=True, buttons=buttons)


def ask_again(ctx: Ctx, pending: Pending) -> dict | None:
    """Ответ на уточнение не понят: повторяем тот же вопрос. None — вопроса нет, разбираем как новый запрос."""
    ask = pending.draft.get("ask")
    if not ask:
        return None
    return clarify(ctx, ask["template"], pending.draft, ask["quick"], ask["values"])


async def free_times(ctx: Ctx, day: str | None, kind: str) -> list[tuple[str, str]]:
    """Кнопки к вопросу «во сколько»: ближайшие свободные часы в этот день."""
    target = parse_date(day) if day else ctx.today
    if not target or target < ctx.today:
        target = ctx.today
    start = DAY_START
    if target == ctx.today:
        now = ctx.now.hour * 60 + ctx.now.minute
        start = max(DAY_START, (now // 60 + 1) * 60)
    rows = await owner_records(ctx, Record.date == target.isoformat(), Record.time.is_not(None))
    busy = [(minutes(r.time), minutes(r.time) + LENGTH.get(r.type.value, 30))
            for r in rows if r.status != TaskStatus.done]
    need = LENGTH.get(kind, 30)
    starts = [t for t in window_starts(free_windows(busy, start, need), need) if t % 60 == 0][:FREE_BUTTONS]
    return [(hhmm(t), f"в {hhmm(t)}") for t in starts]


FREE_BUTTONS = 3


async def process_draft(ctx: Ctx, draft: dict) -> dict:
    kind, has_date, has_time = draft["type"], bool(draft.get("date")), bool(draft.get("time"))
    times = await free_times(ctx, draft.get("date"), kind) if not has_time else []
    days = [("Сегодня", "сегодня"), ("Завтра", "завтра")]

    if not draft.get("text"):
        ctx.conv.pending = None
        text, speech = ctx.say("clarify_generic")
        return reply("clarify", text, speech, awaiting=True, buttons=[CANCEL])
    if kind == "meeting" and not draft.get("has_subject", True):
        return clarify(ctx, "clarify_meeting_person", draft)
    if kind == "reminder":
        if not has_date and not has_time:
            return clarify(ctx, "clarify_reminder_when", draft)
        if not has_time:
            return clarify(ctx, "clarify_reminder_time", draft, times)
        if not has_date:
            return clarify(ctx, "clarify_day", draft, days)
    if kind == "meeting":
        if not has_time:
            return clarify(ctx, "clarify_meeting_time", draft, times)
        if not has_date:
            return clarify(ctx, "clarify_day", draft, days)
    if kind == "task" and has_time and not has_date:
        return clarify(ctx, "clarify_day", draft, days)
    if kind == "task" and not has_date:
        draft["date_kind"], draft["time"] = "none", None
    elif draft.get("date_kind") == "none":
        draft["date_kind"] = "exact"

    # Дата или время в прошлом (Р-36)
    today = ctx.today.isoformat()
    if has_date and (draft["date"] < today or (draft["date"] == today and has_time
                                              and draft["date_kind"] == "exact"
                                              and draft["time"] <= ctx.now.strftime("%H:%M"))):
        past = dict(draft)
        values, _ = ctx.record_values(draft_record(draft, []))
        if draft["date"] < today:
            past["date"] = None
        past["time"] = None if kind != "task" else past.get("time")
        return clarify(ctx, "clarify_date_past", past, values={"when": values["when"]})

    # Высокий риск ошибки — «правильно понял?» (Р-19)
    if draft.get("ambiguous") and not draft.get("confirmed"):
        ctx.conv.pending = Pending("confirm", draft)
        values, speech_values = ctx.record_values(draft_record(draft, []))
        values["type"] = TYPE_WORD[kind]
        text, speech = ctx.say("confirm", values, speech_values)
        return reply("confirm", text, speech, records=[draft_record(draft, ["draft"])], awaiting=True, buttons=[
            button_action("Да, верно", "confirm_yes"),
            button_action("Нет", "confirm_no", style="secondary"),
        ])

    # Совпадение встреч: только встречи, по точному времени начала (Р-26)
    if kind == "meeting" and not draft.get("keep_both"):
        busy = await owner_records(ctx, Record.type == TaskType.meeting, Record.date == draft["date"],
                                   Record.time == draft["time"])
        if busy:
            ctx.conv.pending = Pending("conflict", draft)
            records = [draft_record(draft, ["draft"])] + [r.to_contract(marks=["conflict"]) for r in busy]
            if len(busy) == 1:
                text, speech = ctx.say("conflict_one", {"time": draft["time"], "text": busy[0].text})
            else:
                values, _ = ctx.record_values(draft_record(draft, []))
                text, speech = ctx.say("conflict_many", {"time": draft["time"], "count": len(busy),
                                                         "when": values["when"]})
            # «Перенести существующую» не присылаем: изменение фразой (Д1) не делаем (Р-28)
            return reply("conflict", text, speech, records=records, awaiting=True, buttons=[
                button_action("Другое время для новой", "change_new_time"),
                button_action("Оставить обе", "keep_both"),
                CANCEL,
            ])

    return await save(ctx, draft)


DENSE_MINUTES = 30  # порог плотного графика из отчёта аналитика: 12% пар встреч


def minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


async def dense_neighbours(ctx: Ctx, draft: dict) -> list[Record]:
    """Ближайшие встречи до и после новой, если до них меньше 30 минут. Точное совпадение — это конфликт."""
    if draft["type"] != "meeting" or not draft.get("time") or draft.get("keep_both"):
        return []
    same_day = await owner_records(ctx, Record.type == TaskType.meeting, Record.date == draft["date"],
                                   Record.time.is_not(None))
    start = minutes(draft["time"])
    before = [r for r in same_day if 0 < start - minutes(r.time) < DENSE_MINUTES]
    after = [r for r in same_day if 0 < minutes(r.time) - start < DENSE_MINUTES]
    near = []
    if before:
        near.append(max(before, key=lambda r: minutes(r.time)))
    if after:
        near.append(min(after, key=lambda r: minutes(r.time)))
    return near


async def save(ctx: Ctx, draft: dict) -> dict:
    ctx.conv.pending = None
    kind = draft["type"]
    near = await dense_neighbours(ctx, draft)
    record = ctx.owner.new_record(
        type=TaskType(kind), text=draft["text"][:300], date=draft.get("date"), time=draft.get("time"),
        date_kind=DateKind(draft["date_kind"]),
        status=None if kind == "meeting" else TaskStatus.open,
        created_at=datetime.now(timezone.utc),
    )
    ctx.db.add(record)
    await ctx.db.commit()
    await ctx.db.refresh(record)
    ctx.conv.focus = record.id
    data = record.to_contract(marks=["new"])
    values, speech_values = ctx.record_values(data)
    if draft.get("keep_both"):
        template = "conflict_keep_both"
    elif kind == "task":
        template = {"exact": "created_task", "deadline": "created_task_deadline", "none": "created_task_nodate"}[draft["date_kind"]]
    else:
        template = f"created_{kind}"
    text, speech = ctx.say(template, values, speech_values)
    if near:
        # Плотный график: встречу сохраняем, показываем её и соседей — любую можно открыть и поправить
        gap = min(abs(minutes(r.time) - minutes(record.time)) for r in near)
        tail, tail_speech = ctx.say("dense_schedule", {"count": gap})
        text = f"{text} {tail}"
        speech = f"{speech} {tail_speech}" if speech and tail_speech else speech
        others = sorted([data] + [r.to_contract() for r in near], key=lambda r: r["time"])
        return reply("created", text, speech, records=others, buttons=undo_button(ctx, record))
    return reply("created", text, speech, records=[data], buttons=undo_button(ctx, record))


# ── Несколько дел одной фразой ────────────────────────

def ready_draft(ctx: Ctx, draft: dict) -> bool:
    """Можно записать без уточнений: всё нужное есть и не в прошлом."""
    kind = draft["type"]
    if not draft.get("text") or (kind == "meeting" and not draft.get("has_subject", True)):
        return False
    if kind in ("meeting", "reminder") and not (draft.get("date") and draft.get("time")):
        return False
    if kind == "task" and draft.get("time") and not draft.get("date"):
        return False
    today = ctx.today.isoformat()
    if draft.get("date") and (draft["date"] < today or (draft["date"] == today and draft.get("time")
                                                        and draft["time"] <= ctx.now.strftime("%H:%M"))):
        return False
    if kind == "task" and not draft.get("date"):
        draft["date_kind"], draft["time"] = "none", None
    elif draft.get("date_kind") == "none":
        draft["date_kind"] = "exact"
    return True


def needs_only_time(ctx: Ctx, draft: dict) -> bool:
    """Встреча или напоминание, где есть всё, кроме времени: спросим его в общем списке."""
    if draft["type"] not in ("meeting", "reminder") or draft.get("time") or not draft.get("date"):
        return False
    return ready_draft(ctx, {**draft, "time": "23:59"})


async def ask_many(ctx: Ctx, drafts: list[dict]) -> dict:
    """Спрашиваем время по очереди: «Во сколько встреча с Машей завтра?». Все ответили — записываем."""
    missing = [i for i, d in enumerate(drafts) if not d.get("time")]
    if not missing:
        return await save_many(ctx, drafts)
    i = missing[0]
    draft = drafts[i]
    ctx.conv.pending = Pending("multi_ask", {"drafts": drafts, "i": i})
    day = parse_date(draft["date"])
    diff = (day - ctx.today).days
    when = {0: "сегодня", 1: "завтра", 2: "послезавтра"}.get(diff) or f"{day.day} {MONTHS_GEN[day.month - 1]}"
    what = draft["text"][:1].lower() + draft["text"][1:]
    template = "clarify_many_time" if draft["type"] == "meeting" else "clarify_many_reminder"
    text, speech = ctx.say(template, {"text": what, "day": when})
    records = [draft_record(d, ["draft"]) for d in drafts]
    buttons = [button_text(label, send) for label, send in await free_times(ctx, draft["date"], draft["type"])]
    return reply("clarify", text, speech, records=records, awaiting=True, buttons=buttons + [CANCEL])


async def answer_multi_ask(ctx: Ctx, pending: Pending, raw: str) -> dict | None:
    """Ответ на «Во сколько …?» в списке дел. None — времени в ответе нет."""
    time, _, _, _ = nlu.parse_when(raw, ctx.now)
    if not time:
        time, _ = nlu.reply_time(raw)
    if not time:
        return None
    drafts = [dict(d) for d in pending.draft["drafts"]]
    drafts[pending.draft["i"]]["time"] = time
    return await ask_many(ctx, drafts)


async def answer_many(ctx: Ctx, parses: list[nlu.Parse]) -> dict | None:
    """Несколько дел: показываем все карточки и спрашиваем «Записать все?». None — не вышло, разбираем как одно."""
    drafts = [draft_from(p, ctx.today) for p in parses]
    if not all(ready_draft(ctx, d) for d in drafts):
        if all(ready_draft(ctx, d) or needs_only_time(ctx, d) for d in drafts):
            return await ask_many(ctx, drafts)
        return None
    ctx.conv.pending = Pending("multi", {"drafts": drafts})
    text, speech = ctx.say("multi_confirm", {"count": len(drafts)})
    return reply("confirm", text, speech, records=[draft_record(d, ["draft"]) for d in drafts], awaiting=True,
                 buttons=[button_action("Да, записать все", "confirm_yes"),
                          button_action("Нет", "cancel", style="secondary")])


async def save_many(ctx: Ctx, drafts: list[dict]) -> dict:
    ctx.conv.pending = None
    saved = []
    for draft in drafts:
        record = ctx.owner.new_record(
            type=TaskType(draft["type"]), text=draft["text"][:300], date=draft.get("date"), time=draft.get("time"),
            date_kind=DateKind(draft["date_kind"]),
            status=None if draft["type"] == "meeting" else TaskStatus.open,
            created_at=datetime.now(timezone.utc),
        )
        ctx.db.add(record)
        saved.append(record)
    await ctx.db.commit()
    for record in saved:
        await ctx.db.refresh(record)
    text, speech = ctx.say("multi_created", {"count": len(saved)})
    return reply("created", text, speech, records=[r.to_contract(marks=["new"]) for r in saved])


# ── Свободное время ───────────────────────────────────

DAY_START, DAY_END = 9 * 60, 21 * 60   # ищем окна с 9 до 21
STEP = 30                               # кандидаты каждые полчаса
LENGTH = {"meeting": 60}                # встреча занимает час, остальное с временем — полчаса


def hhmm(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def free_windows(busy: list[tuple[int, int]], start: int, need: int) -> list[tuple[int, int]]:
    """Все свободные промежутки дня (начало, конец), куда помещается дело длиной need."""
    windows: list[tuple[int, int]] = []
    t = start
    for b, e in sorted(busy) + [(DAY_END, DAY_END)]:
        if b - t >= need:
            windows.append((t, min(b, DAY_END)))
        t = max(t, e)
        if t >= DAY_END:
            break
    return windows


def window_starts(windows: list[tuple[int, int]], need: int) -> list[int]:
    """Кнопки: начало каждого окна и дальше каждый ровный час, пока дело помещается."""
    starts: list[int] = []
    for b, e in windows:
        t = b
        while t + need <= e:
            starts.append(t)
            t = (t // 60 + 1) * 60
    return starts


async def answer_free(ctx: Ctx, p: nlu.Parse) -> dict:
    day = p.date or ctx.today
    start = DAY_START
    if day == ctx.today:
        now = ctx.now.hour * 60 + ctx.now.minute
        start = max(DAY_START, (now // STEP + 1) * STEP)
    if day < ctx.today:
        day = ctx.today
    rows = await owner_records(ctx, Record.date == day.isoformat(), Record.time.is_not(None))
    busy = [(minutes(r.time), minutes(r.time) + LENGTH.get(r.type.value, 30))
            for r in rows if r.status != TaskStatus.done]
    windows = free_windows(busy, start, p.duration)
    day_word = date_text(day, ctx.today)
    day_send = f"{day.day} {MONTHS_GEN[day.month - 1]}"
    need = {30: "полчаса", 60: "час", 90: "полтора часа"}.get(p.duration)
    if not need:
        need = (plural(p.duration // 60, "час", "часа", "часов") if p.duration % 60 == 0
                else plural(p.duration, "минута", "минуты", "минут"))
    if not windows:
        text, speech = ctx.say("free_none", {"day": day_word, "need": need})
        return reply("found", text, speech, total=0)
    # В тексте — все окна промежутками, кнопки — каждый час внутри них
    spans = [f"{hhmm(b)}–{hhmm(e)}" for b, e in windows]
    listed = spans[0] if len(spans) == 1 else ", ".join(spans[:-1]) + " и " + spans[-1]
    times = [hhmm(t) for t in window_starts(windows, p.duration)]
    text, speech = ctx.say("free_slots" if p.subject else "free_slots_plain",
                           {"day": day_word, "slots": listed, "need": need, "text": p.subject or ""})
    what = p.subject or "Встреча"
    buttons = [button_text(t, f"{what} {day_send} в {t}") for t in times]
    return reply("clarify", text, speech, buttons=buttons)


def undo_button(ctx: Ctx, record: Record) -> list[dict]:
    """Д10: «Отменить» под каждым created с одной сохранённой записью (15.4)."""
    return [button_action("Отменить", "undo", record.id, style="secondary")] if "d10" in ctx.features else []


def draft_from(p: nlu.Parse, today: date) -> dict:
    draft = {
        "type": p.type or "task",
        "text": p.text,
        "date": p.date.isoformat() if p.date else None,
        "time": p.time,
        "date_kind": p.date_kind if p.date else "none",
        "ambiguous": p.time_ambiguous,
        "has_subject": p.has_subject,
    }
    if p.date:
        draft["date_kind"] = p.date_kind
    elif draft["type"] == "task" and p.vague_period and p.period is None:
        draft["date_kind"] = "none"
    return draft


def merge_reply(pending: Pending, raw: str, now: datetime) -> dict | None:
    """Ответ на уточнение: «в 15», «завтра», «с Иваном». Не ответ — None."""
    draft = dict(pending.draft)
    time, ambiguous, time_spans, info = nlu.parse_when(raw, now)
    rest = " ".join(nlu._cut(raw, info.spans + time_spans).split()).strip(" ,.!?")
    changed = False
    if info.date:
        draft["date"] = info.date.isoformat()
        draft["date_kind"] = info.kind if draft["type"] == "task" else "exact"
        changed = True
    if not time and not draft.get("time"):
        # Сбивчивый ответ «есть 10… стой… поставь 10» — берём последнее время
        time, ambiguous = nlu.reply_time(raw)
    if time:
        draft["time"] = time
        draft["ambiguous"] = ambiguous and pending.kind != "confirm_no"
        if draft.get("date_kind") == "none":
            draft["date_kind"] = "exact"
        changed = True
    if draft["type"] == "meeting" and not draft.get("has_subject", True) and rest:
        noun = draft.get("text") or "Встреча"
        joined = rest if rest.lower().split()[0] in ("с", "со", "по", "о", "об", "про") else f"с {rest}"
        draft["text"] = f"{noun} {joined}"
        draft["has_subject"] = True
        changed = True
    if pending.kind == "confirm_no":
        draft["confirmed"] = True
    return draft if changed else None


# ── Разбор: правила, затем LLM ────────────────────────

def llm_enabled() -> bool:
    return bool(os.getenv("YANDEX_API_KEY") and os.getenv("YANDEX_FOLDER_ID"))


def llm_parse(text: str, now: datetime) -> nlu.Parse:
    """Если правила не поняли — спрашиваем LLM (brain.py) и переводим её ответ в Parse."""
    try:
        from brain import parse_user_input
        intent = parse_user_input(text)
    except Exception as error:  # noqa: BLE001 — LLM недоступна: «не понял»
        print(f"LLM недоступна: {error}")
        return nlu.Parse()
    if not intent or intent.intent == "unknown":
        return nlu.Parse()
    today = now.date()
    tokens = {"today": 0, "tomorrow": 1, "day_after_tomorrow": 2, "yesterday": -1}
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    def to_date(token: str | None) -> date | None:
        if not token:
            return None
        token = token.lower()
        if token in tokens:
            return today + timedelta(days=tokens[token])
        if token in weekdays:
            return today + timedelta(days=(weekdays.index(token) - today.weekday()) % 7)
        if token == "end_of_week":
            return nlu.week_bounds(today)[1]
        return parse_date(token)

    p = nlu.Parse()
    if intent.intent.startswith("create_"):
        p.intent, p.type = "create", intent.intent.removeprefix("create_")
        p.text = intent.text
        p.date = to_date(intent.date)
        p.time = intent.time if intent.time and len(intent.time) == 5 else None
        p.date_kind = intent.date_kind if p.date else "none"
        p.time_ambiguous = bool(intent.time_ambiguous)
    elif intent.intent in ("list", "search"):
        p.intent = intent.intent
        p.filter_type = intent.filter_type if intent.filter_type in TYPE_WORD else None
        if intent.intent == "search":
            words = " ".join(filter(None, [intent.keyword, *(intent.people or []), *(intent.organizations or [])]))
            p.keywords = nlu.keywords(words)
            p.ask, p.tense = intent.ask, intent.tense
        period = (intent.period or "today").lower()
        if period in ("this_week", "next_week"):
            start = nlu.week_bounds(today + timedelta(days=7 if period == "next_week" else 0))[0]
            label = "на этой неделе" if period == "this_week" else "на следующей неделе"
            p.period = nlu.Period(start, start + timedelta(days=6), label, label)
        elif intent.intent == "list":
            day = to_date(period) or today
            p.period = nlu.describe_period(day, day, today)
    else:
        p.intent = intent.intent
    return p


# ── Ответы по типу запроса ────────────────────────────

def examples(kind: str, template_id: str, ctx: Ctx, items: list[str]) -> dict:
    text, speech = ctx.say(template_id)
    return reply(kind, text, speech, buttons=[button_text(x) for x in items])


async def answer_list(ctx: Ctx, p: nlu.Parse) -> dict:
    period = p.period or nlu.describe_period(ctx.today, ctx.today, ctx.today)
    conditions = [Record.date.is_not(None), Record.date >= period.start.isoformat(), Record.date <= period.end.isoformat()]
    if p.filter_type:
        conditions.append(Record.type == TaskType(p.filter_type))
    rows = sorted(await owner_records(ctx, *conditions), key=lambda r: (r.date, r.time or "99:99", r.id))
    values = {"period": period.label, "count": len(rows)}
    speech_values = {"period": period.label_speech}
    if rows:
        if p.ask == "exists" and p.filter_type:
            text, speech = ctx.say("list_type_yes", values, speech_values, count_forms=TYPE_FORMS[p.filter_type])
        else:
            # Про один тип — его формы вместо «дело|дела|дел» (раздел 9)
            forms = TYPE_FORMS[p.filter_type] if p.filter_type else None
            text, speech = ctx.say("list_some", values, speech_values, count_forms=forms)
        return reply("list", text, speech, records=[r.to_contract() for r in rows], total=len(rows))

    # Пусто — ближайшая будущая запись (того же типа, если спрашивали про тип) (Р-17)
    after = max(period.end + timedelta(days=1), ctx.today).isoformat()
    later = [r for r in await owner_records(ctx, Record.date.is_not(None), Record.date >= after,
                                            *([Record.type == TaskType(p.filter_type)] if p.filter_type else []))
             if is_future(r, ctx.now)]
    nearest = min(later, key=moment) if later else None
    if nearest:
        rec_values, rec_speech = ctx.record_values(nearest.to_contract())
        values.update(rec_values)
        speech_values.update({"when": rec_speech["when"]})
    if p.filter_type:
        values["types_gen"] = TYPE_GEN_PLURAL[p.filter_type]
        text, speech = ctx.say("list_type_empty" if nearest else "list_type_empty_alone", values, speech_values)
    else:
        text, speech = ctx.say("list_empty_nearest" if nearest else "list_empty_none", values, speech_values)
    return reply("list", text, speech, nearest=nearest.to_contract() if nearest else None, total=0)


async def answer_briefing(ctx: Ctx) -> dict:
    """Утренний брифинг: при первом открытии за день фронт присылает действие briefing без текста."""
    hour = ctx.now.hour
    greeting = "Доброе утро" if hour < 12 else "Добрый день" if hour < 18 else "Добрый вечер"
    rows = sorted([r for r in await owner_records(ctx, Record.date == ctx.today.isoformat())
                   if r.status != TaskStatus.done], key=lambda r: (r.time or "99:99", r.id))
    if not rows:
        text, speech = ctx.say("briefing_empty", {"greeting": greeting})
        return reply("list", text, speech, total=0)
    upcoming = [r for r in rows if r.time and r.time > ctx.now.strftime("%H:%M")]
    values = {"greeting": greeting, "count": len(rows)}
    if upcoming:
        values.update({"time": upcoming[0].time, "text": upcoming[0].text})
        text, speech = ctx.say("briefing_next", values)
    else:
        text, speech = ctx.say("briefing", values)
    # Плотные места: встречи, между началами которых меньше 30 минут
    meetings = [r for r in rows if r.type == TaskType.meeting and r.time]
    dense = [(a, b) for a, b in zip(meetings, meetings[1:]) if 0 < minutes(b.time) - minutes(a.time) < DENSE_MINUTES]
    if dense:
        a, b = dense[0]
        tail, tail_speech = ctx.say("briefing_dense", {"start": a.time, "end": b.time,
                                                       "count": minutes(b.time) - minutes(a.time)})
        text = f"{text} {tail}"
        speech = f"{speech} {tail_speech}" if speech and tail_speech else speech
    return reply("list", text, speech, records=[r.to_contract() for r in rows], total=len(rows))


async def answer_search(ctx: Ctx, p: nlu.Parse) -> dict:
    found = await find(ctx, p)
    if not found:
        text, speech = ctx.say("found_none")
        return reply("found", text, speech, total=0)
    highlight = "date" if p.ask == "when" else None
    if p.ask == "when":
        past = sorted([r for r in found if not is_future(r, ctx.now) and r.date], key=moment, reverse=True)
        future = sorted([r for r in found if is_future(r, ctx.now)], key=moment)
        want_past = p.tense == "past" or not future
        ordered = (past + future) if want_past and past else (future + past)
        first = ordered[0]
        template = "found_when_last" if (want_past and past) else "found_when_next"
        values, speech_values = ctx.record_values(first.to_contract())
        text, speech = ctx.say(template, values, speech_values)
    else:
        ordered = nearest_first(found, ctx.now)
        if len(found) == 1:
            values, speech_values = ctx.record_values(found[0].to_contract())
            text, speech = ctx.say("found_one", values, speech_values)
        else:
            text, speech = ctx.say("found_some", {"count": len(found)})
    if len(found) == 1 or p.ask == "when":
        ctx.conv.focus = ordered[0].id
    records = [r.to_contract(highlight=highlight) for r in ordered[:FOUND_LIMIT]]
    return reply("found", text, speech, records=records, total=len(found))


def is_ahead(record: Record, now: datetime) -> bool:
    """Впереди: будущее по дате или открытое дело без даты."""
    return is_future(record, now) or (not record.date and record.status != TaskStatus.done)


async def answer_person(ctx: Ctx, p: nlu.Parse) -> dict:
    """Досье: все встречи и дела с человеком — сначала впереди, потом прошлые."""
    conditions = [Record.type == TaskType(p.filter_type)] if p.filter_type else []
    if p.period:
        conditions += [Record.date >= p.period.start.isoformat(), Record.date <= p.period.end.isoformat()]
    rows = [r for r in await owner_records(ctx, *conditions)
            if any(nlu.record_has(record_words(r), key) for key in p.keywords)]
    ahead = sorted([r for r in rows if is_ahead(r, ctx.now)], key=moment)
    past = sorted([r for r in rows if not is_ahead(r, ctx.now)], key=moment, reverse=True)
    values = {"name": p.person, "count": len(rows)}
    meet = button_text("Найти время для встречи", f"Найди время встретиться с {p.person}")
    if p.period:
        values["period"] = p.period.label
        speech_values = {"period": p.period.label_speech}
        if not rows:
            text, speech = ctx.say("person_period_none", values, speech_values)
            return reply("person", text, speech, total=0, buttons=[meet])
        text, speech = ctx.say("person_period", values, speech_values,
                               count_forms=TYPE_FORMS[p.filter_type] if p.filter_type else None)
        ahead, past = sorted(rows, key=moment), []  # за период — просто по порядку, как в списке
    elif not rows:
        text, speech = ctx.say("person_none", values)
        return reply("person", text, speech, total=0, buttons=[meet])
    else:
        first = ahead[0] if ahead and ahead[0].date else past[0] if past else ahead[0]
        rec_values, rec_speech = ctx.record_values(first.to_contract())
        forms = TYPE_FORMS[p.filter_type] if p.filter_type else ("дело", "дела", "дел")
        values.update(rec_values, ahead=plural(len(ahead), *forms))
        text, speech = ctx.say("person_ahead" if first in ahead else "person_past", values,
                               {"when": rec_speech["when"]})
    ordered = ahead + past
    ctx.conv.focus = ordered[0].id  # «перенеси её на завтра» — про ближайшее
    records = [r.to_contract() for r in ordered[:FOUND_LIMIT]]
    return reply("person", text, speech, records=records, total=len(rows),
                 buttons=[meet] if not ahead else [])


def which_one(ctx: Ctx, candidates: list[Record], action_id: str) -> dict:
    ctx.conv.pending = None
    chosen = nearest_first(candidates, ctx.now)[:WHICH_LIMIT]
    text, speech = ctx.say("which_one")
    buttons = []
    for record in chosen:
        value = parse_date(record.date)
        label = f"{record.text} · {date_text(value, ctx.today) if value else 'без срока'}"
        buttons.append(button_action(label, action_id, record.id))
    return reply("clarify", text, speech, records=[r.to_contract() for r in chosen], awaiting=True,
                 buttons=buttons + [CANCEL])


async def delete_one(ctx: Ctx, record: Record, template: str = "deleted") -> dict:
    record.deleted_at = datetime.now(timezone.utc)
    await ctx.db.commit()
    data = record.to_contract(marks=["deleted"])
    values, speech_values = ctx.record_values(data)
    text, speech = ctx.say(template, values, speech_values)
    buttons = [] if template == "undo_done" else [button_action("Вернуть", "restore", record.id, style="secondary")]
    return reply("deleted", text, speech, records=[data], buttons=buttons)


async def complete_one(ctx: Ctx, record: Record) -> dict:
    if record.type == TaskType.meeting:
        text, speech = ctx.say("completed_meeting_no")
        return reply("clarify", text, speech, awaiting=True, buttons=[CANCEL])
    record.status = TaskStatus.done
    await ctx.db.commit()
    ctx.conv.focus = record.id
    data = record.to_contract()
    values, speech_values = ctx.record_values(data)
    text, speech = ctx.say("completed", values, speech_values)
    return reply("completed", text, speech, records=[data])


def single(ctx: Ctx, found: list[Record]) -> Record | None:
    """Одна запись — она. Несколько с одинаковым текстом (повторы) — ближайшая из них."""
    if len({r.text.lower() for r in found}) == 1:
        return nearest_first(found, ctx.now)[0]
    return None


async def focused(ctx: Ctx, p: nlu.Parse, types: set[str] | None = None) -> list[Record]:
    """«Её», «это» — запись, о которой только что шла речь; «последнюю» без контекста — последняя созданная."""
    if not p.ref or p.keywords:
        return []
    record = await owned_record(ctx, ctx.conv.focus)
    if record and record.deleted_at is None and (not types or record.type.value in types):
        return [record]
    if ctx.conv.focus is None:
        conditions = [Record.type == TaskType(p.filter_type)] if p.filter_type else []
        if types and not p.filter_type:
            conditions.append(Record.type.in_([TaskType(t) for t in types]))
        rows = await ctx.db.execute(select(Record).where(ctx.owner.filter(), Record.deleted_at.is_(None),
                                                         Record.created_at.is_not(None), *conditions)
                                    .order_by(Record.created_at.desc(), Record.id.desc()).limit(1))
        return list(rows.scalars().all())
    return []


async def answer_delete(ctx: Ctx, p: nlu.Parse) -> dict:
    if near := await focused(ctx, p):
        return await delete_one(ctx, near[0])
    if not (p.keywords or p.date or p.filter_type):
        text, speech = ctx.say("clarify_generic")
        return reply("clarify", text, speech, awaiting=True, buttons=[CANCEL])
    found = await find(ctx, p)
    if p.time:
        found = [r for r in found if r.time == p.time] or found
    if not found:
        text, speech = ctx.say("found_none")
        return reply("found", text, speech, total=0)
    if one := single(ctx, found):
        return await delete_one(ctx, one)
    return which_one(ctx, found, "delete")


async def answer_complete(ctx: Ctx, p: nlu.Parse) -> dict:
    if p.filter_type == "meeting":
        text, speech = ctx.say("completed_meeting_no")
        return reply("clarify", text, speech, awaiting=True, buttons=[CANCEL])
    if near := await focused(ctx, p):
        return await complete_one(ctx, near[0])
    if not (p.keywords or p.date or p.filter_type):
        text, speech = ctx.say("clarify_generic")
        return reply("clarify", text, speech, awaiting=True, buttons=[CANCEL])
    found = await find(ctx, p, types={"task", "reminder"})
    open_ones = [r for r in found if r.status != TaskStatus.done] or found
    if not open_ones:
        meetings = await find(ctx, nlu.Parse(keywords=p.keywords, date=p.date), types={"meeting"})
        if meetings:
            text, speech = ctx.say("completed_meeting_no")
            return reply("clarify", text, speech, awaiting=True, buttons=[CANCEL])
        text, speech = ctx.say("found_none")
        return reply("found", text, speech, total=0)
    if one := single(ctx, open_ones):
        return await complete_one(ctx, one)
    return which_one(ctx, open_ones, "complete")


# ── Перенос фразой: «перенеси её на завтра», «сдвинь встречу с Иваном на час позже» ──

def move_changes(p: nlu.Parse) -> dict:
    return {"date": p.date.isoformat() if p.date else None, "time": p.time, "shift": p.shift}


async def answer_move(ctx: Ctx, p: nlu.Parse) -> dict:
    changes = move_changes(p)
    found = await focused(ctx, p)
    if not found and p.keywords:
        found = await find(ctx, nlu.Parse(keywords=p.keywords, required=p.required, filter_type=p.filter_type))
    if not found:
        if p.ref:
            text, speech = ctx.say("clarify_generic")
            return reply("clarify", text, speech, awaiting=True, buttons=[CANCEL])
        text, speech = ctx.say("found_none")
        return reply("found", text, speech, total=0)
    future = [r for r in found if is_future(r, ctx.now) or not r.date] or found
    if one := single(ctx, future):
        return await move_one(ctx, one, changes)
    answer = which_one(ctx, future, "move")
    ctx.conv.pending = Pending("move", changes)
    return answer


async def day_windows(ctx: Ctx, day: date, need: int, skip: int | None = None) -> list[tuple[int, int]]:
    """Свободные окна дня длиной need; skip — запись, которую переносим (её место свободно)."""
    if day < ctx.today:
        return []
    start = DAY_START
    if day == ctx.today:
        start = max(DAY_START, (ctx.now.hour * 60 + ctx.now.minute) // STEP * STEP + STEP)
    rows = await owner_records(ctx, Record.date == day.isoformat(), Record.time.is_not(None))
    busy = [(minutes(r.time), minutes(r.time) + LENGTH.get(r.type.value, 30))
            for r in rows if r.status != TaskStatus.done and r.id != skip]
    return free_windows(busy, start, need)


MOVE_DAYS = 3   # кнопок с ближайшими свободными днями
MOVE_TIMES = 8  # кнопок со временем


def needs_time(record: Record) -> bool:
    """Задаче без времени хватает дня; встрече, напоминанию и делу со временем нужно время."""
    return record.type != TaskType.task or bool(record.time)


async def ask_move_day(ctx: Ctx, record: Record, time: str | None = None) -> dict:
    """«На какой день перенести?» — ближайшие дни со свободным окном и тот же день через неделю."""
    ctx.conv.pending = Pending("move_when", {"record_id": record.id, "time": time})
    need = LENGTH.get(record.type.value, 30)
    days: list[date] = []
    for shift in range(14):
        day = ctx.today + timedelta(days=shift)
        if len(days) == MOVE_DAYS:
            break
        if day.isoformat() == record.date and not time:
            continue
        windows = await day_windows(ctx, day, need, skip=record.id)
        if time:
            t = minutes(time)
            fits = any(b <= t and t + need <= e for b, e in windows)
        else:
            fits = bool(windows)
        if fits:
            days.append(day)
    # Тот же день недели на следующей неделе: от дня записи, а если она в прошлом — от сегодня
    base = max(parse_date(record.date) or ctx.today, ctx.today)
    next_week = base + timedelta(days=7)
    if next_week not in days:
        days.append(next_week)
    buttons = [button_text(capitalize(date_text(d, ctx.today)), f"{d.day} {MONTHS_GEN[d.month - 1]} {d.year}")
               for d in days]
    text, speech = ctx.say("move_ask_day", {"text": record.text})
    return reply("clarify", text, speech, records=[record.to_contract()], awaiting=True, buttons=buttons + [CANCEL])


async def ask_move_time(ctx: Ctx, record: Record, day: date) -> dict:
    """«Во сколько?» — свободные окна выбранного дня кнопками."""
    ctx.conv.pending = Pending("move_when", {"record_id": record.id, "date": day.isoformat()})
    need = LENGTH.get(record.type.value, 30)
    windows = await day_windows(ctx, day, need, skip=record.id)
    values = {"day": date_text(day, ctx.today), "text": record.text}
    if not windows:
        text, speech = ctx.say("move_ask_time_full", values, {"day": date_speech(day, ctx.today)})
        return reply("clarify", text, speech, records=[record.to_contract()], awaiting=True, buttons=[CANCEL])
    spans = [f"{hhmm(b)}–{hhmm(e)}" for b, e in windows]
    values["slots"] = spans[0] if len(spans) == 1 else ", ".join(spans[:-1]) + " и " + spans[-1]
    times = [hhmm(t) for t in window_starts(windows, need)][:MOVE_TIMES]
    text, speech = ctx.say("move_ask_time", values, {"day": date_speech(day, ctx.today)})
    buttons = [button_text(t, f"в {t}") for t in times]
    return reply("clarify", text, speech, records=[record.to_contract()], awaiting=True, buttons=buttons + [CANCEL])


async def move_one(ctx: Ctx, record: Record, changes: dict) -> dict:
    """Переносим, только когда сказаны и день, и время (или сдвиг «на час позже»); иначе спрашиваем."""
    ctx.conv.focus = record.id
    new_date, new_time = changes.get("date"), changes.get("time")
    if changes.get("shift") and record.time:
        new_date = new_date or record.date
        start = max(0, min(minutes(record.time) + changes["shift"], 23 * 60 + 59))
        new_time = hhmm(start)
    if not new_date:
        return await ask_move_day(ctx, record, new_time)
    if not new_time and needs_time(record):
        day = parse_date(new_date)
        if day and day >= ctx.today:
            return await ask_move_time(ctx, record, day)
    today = ctx.today.isoformat()
    if new_date < today or (new_date == today and new_time and new_time <= ctx.now.strftime("%H:%M")):
        ctx.conv.pending = Pending("move_when", {"record_id": record.id})
        values, _ = ctx.record_values({**record.to_contract(), "date": new_date, "time": new_time,
                                       "date_kind": "exact"})
        text, speech = ctx.say("clarify_date_past", values={"when": values["when"]})
        return reply("clarify", text, speech, awaiting=True, buttons=[CANCEL])
    ctx.conv.pending = None
    record.date, record.time = new_date, new_time
    if record.date_kind == DateKind.none:
        record.date_kind = DateKind.exact
    await ctx.db.commit()
    data = record.to_contract(marks=["new"])
    values, speech_values = ctx.record_values(data)
    text, speech = ctx.say("moved", values, speech_values)
    if record.type == TaskType.meeting and record.time:
        busy = [r for r in await owner_records(ctx, Record.type == TaskType.meeting, Record.date == record.date,
                                               Record.time == record.time) if r.id != record.id]
        if busy:
            tail, _ = ctx.say("moved_busy", {"text": busy[0].text})
            text = f"{text} {tail}"
            return reply("updated", text, speech, records=[data] + [r.to_contract(marks=["conflict"]) for r in busy])
    return reply("updated", text, speech, records=[data])


async def answer_move_when(ctx: Ctx, pending: Pending, raw: str) -> dict | None:
    """Ответ на «На какое время перенести?»: «на 16», «завтра в 11». Не ответ — None."""
    record = await owned_record(ctx, pending.draft.get("record_id"))
    p = nlu.parse("перенеси " + raw, ctx.now)
    if not record or p.intent != "move" or p.keywords:
        return None
    changes = move_changes(p)
    changes["time"] = changes["time"] or pending.draft.get("time")
    changes["date"] = changes["date"] or pending.draft.get("date")
    return await move_one(ctx, record, changes)


# ── Кнопки-действия (раздел 6, 15.3) ──────────────────

async def owned_record(ctx: Ctx, record_id: int | None) -> Record | None:
    if record_id is None:
        return None
    record = await ctx.db.get(Record, record_id)
    return record if record and ctx.owner.owns(record) else None


async def handle_action(ctx: Ctx, action_id: str, record_id: int | None) -> dict | None:
    """Ответ на нажатие. None — действие не наше или доп выключен: разбираем текст."""
    pending = ctx.conv.pending
    if action_id == "cancel":
        ctx.conv.pending = None
        text, speech = ctx.say("cancelled")
        return reply("cancelled", text, speech)
    if action_id == "briefing":
        return await answer_briefing(ctx)
    if action_id == "confirm_yes" and pending and pending.kind == "multi":
        return await save_many(ctx, pending.draft["drafts"])
    if action_id == "confirm_yes" and pending and pending.kind == "confirm":
        return await process_draft(ctx, {**pending.draft, "confirmed": True})
    if action_id == "confirm_no" and pending and pending.kind == "confirm":
        ctx.conv.pending = Pending("confirm_no", {**pending.draft, "ambiguous": False})
        text, speech = ctx.say("confirm_no")
        return reply("clarify", text, speech, awaiting=True, buttons=[CANCEL])
    if action_id == "keep_both" and pending and pending.kind == "conflict":
        return await save(ctx, {**pending.draft, "keep_both": True})
    if action_id == "change_new_time" and pending and pending.kind == "conflict":
        ctx.conv.pending = Pending("new_time", {**pending.draft, "time": None})
        text, speech = ctx.say("conflict_new_time")
        return reply("clarify", text, speech, awaiting=True, buttons=[CANCEL])

    feature = {"undo": "d10", "restore": "d2", "delete": "d2", "complete": "d3"}.get(action_id)
    if feature and feature in ctx.features:
        record = await owned_record(ctx, record_id)
        if not record:
            text, speech = ctx.say("found_none")
            return reply("found", text, speech, total=0)
        ctx.conv.pending = None
        if action_id == "undo":
            return await delete_one(ctx, record, "undo_done")
        if action_id == "delete":
            return await delete_one(ctx, record)
        if action_id == "complete":
            return await complete_one(ctx, record)
        record.deleted_at = None
        await ctx.db.commit()
        ctx.conv.focus = record.id
        data = record.to_contract(marks=["new"])
        values, speech_values = ctx.record_values(data)
        text, speech = ctx.say("restored", values, speech_values)
        return reply("created", text, speech, records=[data], buttons=undo_button(ctx, record))
    if action_id == "move" and pending and pending.kind == "move":
        record = await owned_record(ctx, record_id)
        if record:
            return await move_one(ctx, record, pending.draft)
    if pending and action_id in ("confirm_yes", "confirm_no", "keep_both", "change_new_time"):
        return None
    return None


# ── Эндпоинт ──────────────────────────────────────────

def is_new_request(p: nlu.Parse, raw: str) -> bool:
    if p.intent in ("list", "search", "help", "off_topic", "delete", "complete", "thanks", "move"):
        return True
    if p.intent == "create":
        return bool(nlu.CREATE_VERB_RE.search(raw.strip().lower()) or (p.text and len(nlu.keywords(p.text)) >= 2))
    return False


@router.post("/chat")
async def chat_endpoint(
    payload: ChatRequest,
    owner: Owner = Depends(get_owner),
    db: AsyncSession = Depends(get_db),
    x_stevens_features: str | None = Header(default=None),
):
    features = {f.strip().lower() for f in (x_stevens_features or "").split(",") if f.strip()}
    ctx = Ctx(owner=owner, db=db, conv=conversation(owner, payload.conversation_id),
              now=client_now(payload.client_time), features=features)
    try:
        return await respond(ctx, payload)
    except Exception as error:  # noqa: BLE001 — сбой: kind error, «Повторить» добавит фронт
        print(f"chat error: {error!r}")
        await db.rollback()
        text, speech = ctx.say("error_backend")
        return reply("error", text, speech)


async def respond(ctx: Ctx, payload: ChatRequest) -> dict:
    if payload.action:
        answer = await handle_action(ctx, payload.action.id, payload.action.record_id)
        if answer:
            return answer

    raw = payload.text.strip()
    p = nlu.parse(raw, ctx.now)

    # Ответ на уточнение (Р-45); не ответ — новый запрос, уточнение забываем (Р-33)
    pending = ctx.conv.pending
    if pending and pending.kind == "move_when" and not is_new_request(p, raw):
        if answer := await answer_move_when(ctx, pending, raw):
            return answer
    asking = pending and pending.kind in ("draft", "new_time", "confirm_no", "multi_ask", "multi", "confirm", "conflict")
    if asking and nlu.is_cancel_reply(raw):
        # «Стой», «убери всё» в ответ на вопрос — отмена, а не удаление записей
        ctx.conv.pending = None
        text, speech = ctx.say("cancelled")
        return reply("cancelled", text, speech)
    if pending and pending.kind in ("draft", "new_time", "confirm_no", "multi_ask") and not is_new_request(p, raw):
        if pending.kind == "multi_ask":
            answer = await answer_multi_ask(ctx, pending, raw)
        else:
            merged = merge_reply(pending, raw, ctx.now)
            answer = await process_draft(ctx, merged) if merged else None
        if answer:
            return answer
        if pending.kind == "multi_ask":
            return await ask_many(ctx, pending.draft["drafts"])
        if answer := ask_again(ctx, pending):
            return answer
    ctx.conv.pending = None

    if p.intent == "unknown" and llm_enabled():
        p = llm_parse(raw, ctx.now)

    if p.intent == "delete" and "d2" not in ctx.features:
        p.intent = "unknown"
    if p.intent == "complete" and "d3" not in ctx.features:
        p.intent = "unknown"

    if p.intent == "create":
        many = nlu.parse_many(raw, ctx.now)
        if many and (answer := await answer_many(ctx, many)):
            return answer
        return await process_draft(ctx, draft_from(p, ctx.today))
    if p.intent == "free":
        return await answer_free(ctx, p)
    if p.intent == "list":
        return await answer_list(ctx, p)
    if p.intent == "search":
        return await answer_search(ctx, p)
    if p.intent == "person":
        return await answer_person(ctx, p)
    if p.intent == "delete":
        return await answer_delete(ctx, p)
    if p.intent == "complete":
        return await answer_complete(ctx, p)
    if p.intent == "move":
        return await answer_move(ctx, p)
    if p.intent == "help":
        return examples("help", "help", ctx, HELP_EXAMPLES)
    if p.intent == "thanks":
        text, speech = ctx.say("thanks")
        return reply("thanks", text, speech)
    if p.intent == "off_topic":
        return examples("off_topic", "off_topic", ctx, EXAMPLES)
    return examples("not_understood", "not_understood", ctx, EXAMPLES)
