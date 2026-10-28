"""Пуш-уведомления (Web Push): приходят, даже когда вкладка закрыта.

Раз в 30 секунд смотрим записи тех, кто подписался: напоминание звонит в своё время,
встреча — за remind_before минут (по умолчанию 15). У пуша кнопки «Посмотреть» и «Через 10 минут» (public/sw.js);
отложенное лежит в push_snoozes и уходит ещё раз в свой срок. Время записи местное, поэтому пояс берём из подписки браузера.
Демо-записи песочницы (demo) не звонят — только то, что человек завёл сам.
Просроченное — одной сводкой вечером (DIGEST_AT по местному времени), каждое дело попадает в неё один раз.
Сводка уходит на одно устройство — то, где человек был последним (seen_at подписки), а не на все сразу.
"""
import asyncio
import base64
import json
from datetime import datetime, time, timedelta, timezone
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

TICK_SECONDS = 30
# Опоздали больше чем на столько (сервер спал) — уже не шлём
LATE_LIMIT = timedelta(minutes=15)
CLAIMS = {"sub": "mailto:stevens@example.com"}
SNOOZE = timedelta(minutes=10)
# «Напомнить позже» в чате: не дальше чем на двое суток
SNOOZE_MAX_MINUTES = 2 * 24 * 60
# Вечерняя сводка о просроченном: с этого часа, раз в день; дела старше недели в неё не попадают
DIGEST_AT = time(19, 0)
DIGEST_LOOKBACK_DAYS = 7
# Отметки «уже было в сводке» живут дольше обычных, иначе дело вернулось бы в сводку
DIGEST_KEEP = timedelta(days=30)

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


def digest_key(record: Record) -> str:
    """Дело уже было в сводке. Перенесли на другой срок — ключ другой, и оно снова попадёт в сводку."""
    return f"do:{record_key(record)}"


def digest_day_key(account_id: int | None, sandbox_id: str | None, day: str) -> str:
    return f"dg:{account_id or ''}:{sandbox_id or ''}:{day}"


def digest_payload(records: list[Record]) -> str:
    """«2 дела остались без отметки» и сами дела строкой ниже."""
    title = f"{plural(len(records), 'дело осталось', 'дела остались', 'дел осталось')} без отметки"
    names = ", ".join(r.text for r in records[:3])
    if len(records) > 3:
        names += f" и ещё {len(records) - 3}"
    return json.dumps({
        "title": title, "body": names, "tag": "overdue-digest", "digest": True,
        "record_ids": [r.id for r in records],
    }, ensure_ascii=False)


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


def payload(record: Record, snoozed: bool = False) -> str:
    """Заголовок — сам текст записи, без «Позвольте напомнить» (просьба Матвея 24.10).
    У встречи ниже строка «Через 15 минут у вас встреча.», у остального текста ниже нет."""
    body = ""
    if record.type == TaskType.meeting and not snoozed:
        body = f"Через {minutes_text(record.remind_minutes())} у вас встреча."
    return json.dumps({
        "title": record.text, "body": body, "tag": record_key(record),
        "record_id": record.id, "snoozed": snoozed,
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
        sent = set((await db.execute(select(PushSent.key))).scalars().all())
        snoozes = list((await db.execute(select(PushSnooze))).scalars().all())
        deferred = {(s.account_id, s.sandbox_id, s.record_id) for s in snoozes}
        dead: list[int] = []
        for (account_id, sandbox_id, _), group in owners.items():
            tz = zone(group[-1].timezone)
            now = datetime.now(tz)
            days = [(now - timedelta(days=1)).date().isoformat(), now.date().isoformat(),
                    (now + timedelta(days=1)).date().isoformat()]
            owner = Record.account_id == account_id if account_id else Record.sandbox_id == sandbox_id
            records = (await db.execute(
                select(Record).where(owner, Record.deleted_at.is_(None), Record.demo.is_(False),
                                     Record.type.in_([TaskType.reminder, TaskType.meeting]),
                                     Record.status.is_distinct_from(TaskStatus.done),
                                     Record.date >= days[0], Record.date <= days[-1])
            )).scalars().all()
            for record in records:
                at = fire_at(record, tz)
                if at is None or not now - LATE_LIMIT <= at <= now or record_key(record) in sent:
                    continue
                if (account_id, sandbox_id, record.id) in deferred:
                    continue
                for sub in group:
                    sub_key = f"{record_key(record)}:s{sub.id}"
                    if sub.id in dead or sub_key in sent:
                        continue
                    # Перед отправкой перечитываем: запись могли выполнить или перенести, пока шла очередь.
                    original = record_key(record)
                    await db.refresh(record)
                    if record.deleted_at is not None or record.status == TaskStatus.done or record_key(record) != original:
                        break
                    result = await asyncio.to_thread(send, sub, payload(record), key)
                    if result is False:
                        dead.append(sub.id)
                    elif result is True:
                        db.add(PushSent(key=sub_key))
                        sent.add(sub_key)
        await send_digests(db, key, subs, sent, dead)
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
            if complete:
                await db.delete(snooze)
        if dead:
            await db.execute(delete(PushSubscription).where(PushSubscription.id.in_(dead)))
        # Старые отметки больше не нужны; отметки сводки держим дольше
        now_utc = datetime.now(timezone.utc)
        await db.execute(delete(PushSent).where(PushSent.sent_at < now_utc - timedelta(days=3), ~PushSent.key.startswith("do:")))
        await db.execute(delete(PushSent).where(PushSent.sent_at < now_utc - DIGEST_KEEP))
        await db.commit()


def digest_due(record: Record, tz, now: datetime) -> bool:
    at = due_at(record, tz)
    return at is not None and at <= now


async def send_digests(db, key: Vapid, subs: list[PushSubscription], sent: set[str], dead: list[int]) -> None:
    """Вечерняя сводка: одна на человека в день, на устройство, где он был последним."""
    people: dict[tuple, list[PushSubscription]] = {}
    for sub in subs:
        people.setdefault((sub.account_id, sub.sandbox_id), []).append(sub)
    for (account_id, sandbox_id), group in people.items():
        group = sorted(group, key=lambda s: s.seen_at or s.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        tz = zone(group[0].timezone)
        now = datetime.now(tz)
        if now.time() < DIGEST_AT:
            continue
        day_key = digest_day_key(account_id, sandbox_id, now.date().isoformat())
        if day_key in sent:
            continue
        owner = Record.account_id == account_id if account_id else Record.sandbox_id == sandbox_id
        since = (now - timedelta(days=DIGEST_LOOKBACK_DAYS)).date().isoformat()
        rows = (await db.execute(
            select(Record).where(owner, Record.deleted_at.is_(None), Record.demo.is_(False),
                                 Record.type.in_([TaskType.task, TaskType.reminder, TaskType.meeting]),
                                 Record.status.is_distinct_from(TaskStatus.done),
                                 Record.date >= since, Record.date <= now.date().isoformat())
        )).scalars().all()
        overdue = sorted((r for r in rows if digest_due(r, tz, now) and digest_key(r) not in sent),
                         key=lambda r: (r.date or "", r.time or ""))
        delivered = not overdue
        if overdue:
            data = digest_payload(overdue)
            for sub in group:
                if sub.id in dead:
                    continue
                result = await asyncio.to_thread(send, sub, data, key)
                if result is False:
                    dead.append(sub.id)
                elif result is True:
                    delivered = True
                    break
        if not delivered:
            continue  # ни одно устройство не приняло — попробуем на следующем тике
        for marker in [day_key, *(digest_key(r) for r in overdue)]:
            db.add(PushSent(key=marker))
            sent.add(marker)


async def loop() -> None:
    while True:
        try:
            await tick()
        except Exception as error:
            print(f"⚠️ Пуши: {error}")
        await asyncio.sleep(TICK_SECONDS)
