"""Пуш-уведомления (Web Push): приходят, даже когда вкладка закрыта.

Раз в 30 секунд смотрим записи тех, кто подписался: напоминание звонит в своё время,
встреча — за remind_before минут (по умолчанию 15). У пуша кнопки «Посмотреть» и «Через 10 минут» (public/sw.js);
отложенное лежит в push_snoozes и уходит ещё раз в свой срок. Время записи местное, поэтому пояс берём из подписки браузера.
Демо-записи песочницы (demo) не звонят — только то, что человек завёл сам.
Просроченные задачи, напоминания и встречи повторяются раз в час до выполнения.
Интервал считается от последней успешной отправки отдельно для каждой подписки.
"""
import asyncio
import base64
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal
from app.textfmt import plural
from app.models import AppSetting, PushSent, PushSnooze, PushSubscription, Record, TaskStatus, TaskType
from app.logic.push_targets import PushSession, allowed_endpoint, valid_keys
from app.templates import render

TICK_SECONDS = 30
# Опоздали больше чем на столько (сервер спал) — уже не шлём
LATE_LIMIT = timedelta(minutes=15)
CLAIMS = {"sub": "mailto:stevens@example.com"}
SNOOZE = timedelta(minutes=10)
OVERDUE_INTERVAL = timedelta(hours=1)

_vapid: Vapid | None = None


async def vapid() -> Vapid:
    """Ключи VAPID создаются один раз и хранятся в базе: подписки живут между перезапусками."""
    global _vapid
    if _vapid:
        return _vapid
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, "vapid_private_pem")
        if row:
            _vapid = Vapid.from_pem(row.value.encode())
        else:
            candidate = Vapid()
            candidate.generate_keys()
            await db.execute(pg_insert(AppSetting).values(key="vapid_private_pem", value=candidate.private_pem().decode())
                             .on_conflict_do_nothing())
            await db.commit()
            row = await db.get(AppSetting, "vapid_private_pem")
            if row is None:
                raise RuntimeError("VAPID key was not persisted")
            _vapid = Vapid.from_pem(row.value.encode())
    return _vapid


async def public_key() -> str:
    """applicationServerKey для pushManager.subscribe — точка в base64url без '='."""
    key = (await vapid()).public_key
    if key is None:
        raise RuntimeError("VAPID public key is unavailable")
    raw = key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def zone(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def fire_at(record: Record, tz) -> datetime | None:
    if not record.date or not record.time or record.demo or record.deleted_at is not None:
        return None
    if record.type not in (TaskType.reminder, TaskType.meeting) or record.status == TaskStatus.done:
        return None
    try:
        at = datetime.fromisoformat(f"{record.date}T{record.time}").replace(tzinfo=tz)
    except ValueError:  # кривые дата или время в одной записи не должны останавливать пуши всем
        return None
    return at - timedelta(minutes=record.remind_minutes()) if record.type == TaskType.meeting else at


def due_at(record: Record, tz) -> datetime | None:
    """An undated item is never overdue; a date without a time lasts the whole day."""
    if record.demo or record.deleted_at is not None or record.status == TaskStatus.done or not record.date \
            or record.type not in (TaskType.task, TaskType.reminder, TaskType.meeting):
        return None
    try:
        start = datetime.fromisoformat(f"{record.date}T{record.time or '00:00'}").replace(tzinfo=tz)
        if not record.time:
            return start + timedelta(days=1)
        if record.type == TaskType.meeting and record.end_time:
            end = datetime.fromisoformat(f"{record.date}T{record.end_time}").replace(tzinfo=tz)
            return end + timedelta(days=1) if end <= start else end
        return start
    except ValueError:
        return None


def overdue_key(record: Record, subscription_id: int) -> str:
    return f"o:{record_key(record)}:s{subscription_id}"


def overdue_due(record: Record, tz, now: datetime, previous: datetime | None = None) -> bool:
    at = due_at(record, tz)
    if at is None:
        return False
    now = now.astimezone(timezone.utc)
    if now - at.astimezone(timezone.utc) < OVERDUE_INTERVAL:
        return False
    if previous is not None:
        previous = previous.replace(tzinfo=timezone.utc) if previous.tzinfo is None else previous.astimezone(timezone.utc)
        if now - previous < OVERDUE_INTERVAL:
            return False
    return True


def minutes_text(total: int) -> str:
    """15 → «15 минут», 30 → «полчаса», 60 → «час», 120 → «2 часа»."""
    if total == 30:
        return "полчаса"
    if total == 60:
        return "час"
    if total % 60 == 0:
        return plural(total // 60, "час", "часа", "часов")
    return plural(total, "минуту", "минуты", "минут")


def record_key(record: Record) -> str:
    """Тот же ключ, что у уведомлений во вкладке: одно и то же не покажется дважды."""
    return f"{record.id}@{record.date}T{record.time}"


def payload(record: Record, snoozed: bool = False, overdue: bool = False) -> str:
    """Заголовок — сам текст записи, без «Позвольте напомнить» (просьба Матвея 24.10).
    У встречи ниже строка «Через 15 минут у вас встреча.», у остального текста ниже нет."""
    body = ""
    if overdue:
        body, _ = render("push_overdue")
    elif record.type == TaskType.meeting and not snoozed:
        body = f"Через {minutes_text(record.remind_minutes())} у вас встреча."
    return json.dumps({
        "title": record.text, "body": body, "tag": record_key(record),
        "record_id": record.id, "snoozed": snoozed, "overdue": overdue,
    }, ensure_ascii=False)


def send(sub: PushSubscription, data: str, key: Vapid) -> bool | None:
    """True — доставлено, False — подписка отозвана, None — нужна повторная попытка."""
    if not allowed_endpoint(sub.endpoint) or not valid_keys({"p256dh": sub.p256dh, "auth": sub.auth}):
        return False
    try:
        with PushSession() as session:
            answer = webpush(
                {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=data, vapid_private_key=key, vapid_claims=dict(CLAIMS), ttl=600, timeout=10,
                requests_session=session,
            )
            status = getattr(answer, "status_code", None)
            if status in (404, 410):
                return False
            if not isinstance(status, int) or not 200 <= status < 300:
                return None
    except WebPushException as error:
        status = error.response.status_code if error.response is not None else None
        if status in (404, 410):
            return False
        print(f"⚠️ Пуш не ушёл: HTTP {status}")
        return None
    except Exception as error:  # сеть и прочее — попробуем со следующей записью
        print(f"⚠️ Пуш не ушёл: {type(error).__name__}")
        return None
    return True


async def tick() -> None:
    key = await vapid()
    async with AsyncSessionLocal() as db:
        if not (await db.execute(select(func.pg_try_advisory_xact_lock(78109324)))).scalar():
            return  # Другой процесс уже обрабатывает очередь уведомлений.
        subs = (await db.execute(select(PushSubscription))).scalars().all()
        owners: dict[tuple, list[PushSubscription]] = {}
        for sub in subs:
            owners.setdefault((sub.account_id, sub.sandbox_id, sub.timezone), []).append(sub)
        deliveries = {row.key: row for row in (await db.execute(select(PushSent))).scalars().all()}
        sent = set(deliveries)
        snoozes = list((await db.execute(select(PushSnooze))).scalars().all())
        deferred = {(s.account_id, s.sandbox_id, s.record_id) for s in snoozes}

        def mark(record, sub, now):
            marker = overdue_key(record, sub.id)
            if marker in deliveries:
                deliveries[marker].sent_at = now.astimezone(timezone.utc)
            else:
                row = PushSent(key=marker, sent_at=now.astimezone(timezone.utc))
                db.add(row)
                deliveries[marker] = row
        dead: list[int] = []
        for (account_id, sandbox_id, _), group in owners.items():
            tz = zone(group[-1].timezone)
            now = datetime.now(tz)
            days = [(now - timedelta(days=1)).date().isoformat(), now.date().isoformat(),
                    (now + timedelta(days=1)).date().isoformat()]
            owner = Record.account_id == account_id if account_id else Record.sandbox_id == sandbox_id
            records = (await db.execute(
                select(Record).where(owner, Record.deleted_at.is_(None), Record.demo.is_(False),
                                     Record.type.in_([TaskType.task, TaskType.reminder, TaskType.meeting]),
                                     Record.status.is_distinct_from(TaskStatus.done),
                                     Record.date <= days[-1])
            )).scalars().all()
            for record in records:
                at = fire_at(record, tz)
                normal = at is not None and now - LATE_LIMIT <= at <= now and record_key(record) not in sent
                for sub in group:
                    sub_key = f"{record_key(record)}:s{sub.id}"
                    marker = deliveries.get(overdue_key(record, sub.id))
                    overdue = (account_id, sandbox_id, record.id) not in deferred and overdue_due(
                        record, tz, now, marker.sent_at if marker else None)
                    regular = normal and sub_key not in sent and (account_id, sandbox_id, record.id) not in deferred
                    if sub.id in dead or not (regular or overdue):
                        continue
                    # Recheck before delivery: the user may complete or move it while the queue runs.
                    original = record_key(record)
                    await db.refresh(record)
                    if record.deleted_at is not None or record.status == TaskStatus.done or record_key(record) != original:
                        continue
                    refreshed_at = fire_at(record, tz)
                    regular = regular and refreshed_at is not None and now - LATE_LIMIT <= refreshed_at <= now
                    overdue = overdue and overdue_due(record, tz, now, marker.sent_at if marker else None)
                    if not (regular or overdue):
                        continue
                    data = payload(record, overdue=overdue and not regular)
                    result = await asyncio.to_thread(send, sub, data, key)
                    if result is False:
                        dead.append(sub.id)
                    elif result is True:
                        mark(record, sub, datetime.now(timezone.utc))
                        if regular:
                            db.add(PushSent(key=sub_key))
                            sent.add(sub_key)
        # Отложенные «Через 10 минут»: запись могли уже выполнить или удалить — тогда молчим
        due = [s for s in snoozes if s.at <= datetime.now(timezone.utc)]
        for snooze in due:
            record = await db.get(Record, snooze.record_id)
            if record is None or record.deleted_at is not None or record.status == TaskStatus.done:
                await db.delete(snooze)
                continue
            group = [sub for (a, s, _), values in owners.items()
                     if (a, s) == (snooze.account_id, snooze.sandbox_id) for sub in values]
            data = payload(record, snoozed=True)
            complete = True
            for sub in group:
                sub_key = f"z{snooze.id}:s{sub.id}"
                if sub.id in dead or sub_key in sent:
                    continue
                result = await asyncio.to_thread(send, sub, data, key)
                if result is False:
                    dead.append(sub.id)
                elif result is None:
                    complete = False
                else:
                    db.add(PushSent(key=sub_key))
                    sent.add(sub_key)
                    mark(record, sub, datetime.now(timezone.utc))
            if complete:
                await db.delete(snooze)
        if dead:
            await db.execute(delete(PushSubscription).where(PushSubscription.id.in_(dead)))
        # Старые отметки больше не нужны
        await db.execute(delete(PushSent).where(PushSent.sent_at < datetime.now(timezone.utc) - timedelta(days=3)))
        await db.commit()


async def loop() -> None:
    while True:
        try:
            await tick()
        except Exception as error:
            print(f"⚠️ Пуши: {error}")
        await asyncio.sleep(TICK_SECONDS)
