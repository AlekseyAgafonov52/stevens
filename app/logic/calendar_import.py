"""Файл .ics из другого календаря (Google, Яндекс, iCloud, Outlook) → новые записи Стивенса.

Встреча со временем → meeting, событие на весь день → task, дело (VTODO) → task.
Еженедельный и ежедневный повтор остаётся повтором, остальные повторы раскладываем по дням на год вперёд.
Прошедшее тоже переносим (отметит выполненным импорт), отменённое и выполненное дело пропускаем.
Прошлые дни еженедельных повторов не переносим — их сотни; повтор начинается с сегодня.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
YEAR = 365
MAX_EXPANDED = 120  # дней одного «раз в месяц/год» за два года
# Outlook пишет пояса по-виндовому
WINDOWS_ZONES = {"Russian Standard Time": "Europe/Moscow", "UTC": "UTC", "GMT Standard Time": "Europe/London",
                 "W. Europe Standard Time": "Europe/Berlin", "Ekaterinburg Standard Time": "Asia/Yekaterinburg",
                 "N. Central Asia Standard Time": "Asia/Novosibirsk", "Kaliningrad Standard Time": "Europe/Kaliningrad"}
MOSCOW = timezone(timedelta(hours=3))


def is_ics(text: str) -> bool:
    return "BEGIN:VCALENDAR" in text[:2000].upper() or "BEGIN:VEVENT" in text[:20000].upper()


def zone(name: str | None):
    name = (name or "").strip().strip('"')
    name = WINDOWS_ZONES.get(name, name)
    try:
        return ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def unescape(value: str) -> str:
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)


def lines(text: str) -> list[tuple[str, dict, str]]:
    """Строки «ИМЯ;ПАРАМ=…:значение» с учётом переноса длинных строк (пробел в начале продолжения)."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        elif raw.strip():
            out.append(raw)
    parsed = []
    for line in out:
        head, sep, value = line.partition(":")
        # двоеточие внутри кавычек параметра (TZID="…") — редкость, но бывает
        while head.count('"') % 2 and sep:
            more, sep, value = value.partition(":")
            head += ":" + more
        if not sep:
            continue
        name, *params = head.split(";")
        parsed.append((name.strip().upper(), {k.upper(): v for k, _, v in (p.partition("=") for p in params)}, value))
    return parsed


def components(text: str) -> list[dict]:
    """VEVENT и VTODO: имя свойства → список (параметры, значение). Вложенные VALARM — в «alarms»."""
    found, stack = [], []
    for name, params, value in lines(text):
        if name == "BEGIN":
            stack.append({"kind": value.strip().upper(), "props": {}, "alarms": []})
        elif name == "END":
            if not stack:
                continue
            item = stack.pop()
            if item["kind"] == "VALARM" and stack:
                stack[-1]["alarms"].append(item)
            elif item["kind"] in ("VEVENT", "VTODO"):
                found.append(item)
        elif stack:
            stack[-1]["props"].setdefault(name, []).append((params, value))
    return found


def first(item: dict, name: str) -> tuple[dict, str] | None:
    values = item["props"].get(name)
    return values[0] if values else None


def moment(params: dict, value: str, local) -> date | datetime | None:
    """Дата (весь день) или время в поясе пользователя."""
    value = value.strip()
    try:
        if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
            return datetime.strptime(value[:8], "%Y%m%d").date()
        stamp = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    if value.endswith("Z"):
        return stamp.replace(tzinfo=timezone.utc).astimezone(local).replace(tzinfo=None)
    if source := zone(params.get("TZID")):
        return stamp.replace(tzinfo=source).astimezone(local).replace(tzinfo=None)
    return stamp  # «плавающее» время — уже местное


def duration(value: str) -> timedelta | None:
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value.strip())
    if not m:
        return None
    sign, w, d, h, mi, s = m.groups()
    delta = timedelta(weeks=int(w or 0), days=int(d or 0), hours=int(h or 0), minutes=int(mi or 0), seconds=int(s or 0))
    return -delta if sign == "-" else delta


def remind_of(item: dict) -> int | None:
    for alarm in item["alarms"]:
        trigger = first(alarm, "TRIGGER")
        if trigger and trigger[0].get("RELATED", "START").upper() == "START" and (d := duration(trigger[1])) is not None:
            minutes = int(-d.total_seconds() // 60)
            if 0 <= minutes <= 1440:
                return minutes
    return None


def text_of(item: dict) -> str:
    summary = first(item, "SUMMARY")
    text = " ".join(unescape(summary[1]).split()) if summary else ""
    return (text or "Без названия")[:300]


def rule_of(value: str) -> dict:
    return {k.upper(): v for k, _, v in (p.partition("=") for p in value.strip().split(";") if p)}


def step(day: date, freq: str, n: int, anchor: date) -> date | None:
    """Следующий день «раз в N дней/недель/месяцев/лет» от anchor (n — номер повтора)."""
    if freq == "DAILY":
        return anchor + timedelta(days=n)
    if freq == "WEEKLY":
        return anchor + timedelta(weeks=n)
    if freq == "MONTHLY":
        month = anchor.month - 1 + n
        try:
            return anchor.replace(year=anchor.year + month // 12, month=month % 12 + 1)
        except ValueError:
            return None  # 31-го в коротком месяце нет
    if freq == "YEARLY":
        try:
            return anchor.replace(year=anchor.year + n)
        except ValueError:
            return None  # 29 февраля
    return None


def occurrences(start: date, rule: dict, last: date) -> list[date]:
    """Дни повтора с start по last (включительно) по FREQ/INTERVAL/BYDAY/COUNT."""
    freq = rule.get("FREQ", "").upper()
    interval = max(1, int(rule["INTERVAL"])) if rule.get("INTERVAL", "").isdigit() else 1
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    byday = [DAYS[d[-2:]] for d in rule.get("BYDAY", "").upper().split(",") if d[-2:] in DAYS]
    nth = re.fullmatch(r"([+-]?\d)(MO|TU|WE|TH|FR|SA|SU)", rule.get("BYDAY", "").upper())
    days: list[date] = []
    n = 0
    while len(days) < 2000:
        if freq == "MONTHLY" and nth:
            # «каждый второй вторник», «последняя пятница»
            month = start.month - 1 + n * interval
            year, month = start.year + month // 12, month % 12 + 1
            if date(year, month, 1) > last:
                break
            which, weekday = int(nth.group(1)), DAYS[nth.group(2)]
            span = [date(year, month, 1) + timedelta(days=i) for i in range(31)]
            span = [d for d in span if d.month == month and d.weekday() == weekday]
            batch = [span[which - 1 if which > 0 else which]] if 0 < abs(which) <= len(span) else []
            batch = [d for d in batch if d >= start]
        elif freq == "WEEKLY" and byday:
            week = start - timedelta(days=start.weekday()) + timedelta(weeks=n * interval)
            if week > last:
                break
            batch = [week + timedelta(days=d) for d in sorted(byday)]
            batch = [d for d in batch if d >= start]
        else:
            day = step(start, freq, n * interval, start)
            if day is None and freq in ("MONTHLY", "YEARLY"):
                n += 1
                if n > 2000:
                    break
                continue
            if day is None or day > last:
                break
            batch = [day]
        for day in batch:
            if count is not None and len(days) >= count:
                return days
            if day <= last:
                days.append(day)
        n += 1
    return days


def convert(text: str, today: date, local=None) -> tuple[list[dict], int]:
    """(записи для импорта, сколько событий пропущено как прошедшие/отменённые)."""
    local = local or MOSCOW
    horizon = today + timedelta(days=YEAR)
    events = components(text)
    out: list[dict] = []
    skipped = 0
    # Перенесённые дни повтора (RECURRENCE-ID): у основного события этот день убираем
    moved: dict[str, set[date]] = {}
    masters = {first(e, "UID")[1].strip() for e in events if first(e, "UID") and first(e, "RRULE")}
    for e in events:
        uid, rid = first(e, "UID"), first(e, "RECURRENCE-ID")
        if uid and rid and uid[1].strip() in masters and (when := moment(rid[0], rid[1], local)) is not None:
            moved.setdefault(uid[1].strip(), set()).add(when if isinstance(when, date) and not isinstance(when, datetime)
                                                        else when.date())
    for e in events:
        status = (first(e, "STATUS") or ({}, ""))[1].strip().upper()
        if status in ("CANCELLED", "COMPLETED"):
            skipped += 1
            continue
        text = text_of(e)
        if e["kind"] == "VTODO":
            due = first(e, "DUE")
            when = moment(*due, local) if due else None
            if when is None:
                out.append({"type": "task", "text": text, "date": None, "time": None})
            else:
                day = when.date() if isinstance(when, datetime) else when
                out.append({"type": "task", "text": text, "date": day.isoformat(),
                            "time": when.strftime("%H:%M") if isinstance(when, datetime) else None})
            continue
        start_prop = first(e, "DTSTART")
        start = moment(*start_prop, local) if start_prop else None
        if start is None:
            skipped += 1
            continue
        all_day = not isinstance(start, datetime)
        end = None
        if not all_day:
            if (end_prop := first(e, "DTEND")) and isinstance(found := moment(*end_prop, local), datetime):
                end = found
            elif (dur := first(e, "DURATION")) and (d := duration(dur[1])) is not None:
                end = start + d
        day0 = start if all_day else start.date()
        base = {"type": "task" if all_day else "meeting", "text": text, "time": None if all_day else start.strftime("%H:%M")}
        if end and end.date() == day0 and end > start:
            base["end_time"] = end.strftime("%H:%M")
        if not all_day and (remind := remind_of(e)) is not None:
            base["remind_before"] = remind
        rrule = first(e, "RRULE")
        uid = (first(e, "UID") or ({}, ""))[1].strip()
        exdates: set[date] = set(moved.get(uid, set()))
        for params, value in e["props"].get("EXDATE", []):
            for part in value.split(","):
                if (when := moment(params, part, local)) is not None:
                    exdates.add(when.date() if isinstance(when, datetime) else when)
        if not rrule:
            out.append({**base, "date": day0.isoformat()})
            continue
        rule = rule_of(rrule[1])
        until = None
        if "UNTIL" in rule and (when := moment({}, rule["UNTIL"], local)) is not None:
            until = when.date() if isinstance(when, datetime) else when
        freq = rule.get("FREQ", "").upper()
        interval = rule.get("INTERVAL", "1")
        byday = [d for d in rule.get("BYDAY", "").upper().split(",") if d]
        simple = interval in ("", "1") and (
            freq == "DAILY" and not byday or freq == "WEEKLY" and all(d in DAYS for d in byday))
        if simple and "COUNT" in rule:
            days = occurrences(day0, rule, date.max - timedelta(days=400))
            until = days[-1] if days else day0
        if simple and (until or horizon) < today:
            skipped += 1  # закончившийся еженедельный повтор
            continue
        if simple and not any(k.startswith("BY") and k != "BYDAY" for k in rule):
            weekdays = list(range(7)) if freq == "DAILY" else sorted({DAYS[d] for d in byday} or {day0.weekday()})
            out.append({**base, "date": max(day0, today).isoformat(),
                        "repeat": {"weekdays": weekdays, "until": until.isoformat() if until else None},
                        "_except": sorted(d.isoformat() for d in exdates if d >= today)})
            continue
        # Раз в две недели, раз в месяц, день рождения раз в год — по дням: год назад и год вперёд
        days = [d for d in occurrences(day0, rule, min(until or horizon, horizon))
                if d >= today - timedelta(days=YEAR) and d not in exdates]
        if not days:
            skipped += 1
        for d in days[-MAX_EXPANDED:]:
            out.append({**base, "date": d.isoformat()})
    return out, skipped
