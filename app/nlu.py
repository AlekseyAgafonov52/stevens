"""Разбор фразы без LLM: правила для русского языка.

Работает всегда и без ключей Yandex. Если правила не поняли фразу, а ключи
заданы, чат спрашивает LLM (brain.py) — см. app/routers/chat.py.
Даты считаются от «сегодня» пользователя (client_time), а не от часов сервера.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.textfmt import MONTHS_GEN, MONTHS_PREP, MONTHS_SHORT, capitalize, date_speech, date_text, week_bounds

I = re.IGNORECASE
E = "[её]"  # «ё» и «е» пишут вперемешку

WEEKDAYS = {
    "понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3, "пятниц": 4, "суббот": 5, "воскресень": 6,
}
WEEKDAY_RE = r"(понедельник|вторник|сред[ауе]|четверг|пятниц[ауе]|суббот[ауе]|воскресень[ея])"
MONTH_RE = r"(январ[яь]|феврал[яь]|март[а]?|апрел[яь]|ма[яй]|июн[яь]|июл[яь]|август[а]?|сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь])"
MONTH_PREP_RE = r"(январе|феврале|марте|апреле|мае|июне|июле|августе|сентябре|октябре|ноябре|декабре)"

MEETING_NOUNS = {
    "встречу": "Встреча", "встреча": "Встреча", "встречи": "Встреча",
    "созвон": "Созвон", "планерку": "Планёрка", "планёрку": "Планёрка", "планерка": "Планёрка",
    "планёрка": "Планёрка", "совещание": "Совещание", "демо": "Демо", "звонок": "Звонок",
}
MEETING_WORD_RE = rf"(встреч|созвон|план{E}рк|совещани|демо\b)"

STOPWORDS = {
    "с", "со", "по", "про", "о", "об", "на", "в", "во", "к", "ко", "для", "и", "у", "меня", "мне", "мою", "мой",
    "моя", "мои", "мои", "все", "всё", "эту", "этот", "это", "её", "ее", "его", "их", "за", "из", "от", "до",
    "задачу", "задача", "задачи", "задач", "встречу", "встреча", "встречи", "встреч", "напоминание",
    "напоминания", "напоминаний", "запись", "записи", "дело", "дела", "когда", "найди", "найти", "покажи",
    "был", "была", "было", "были", "будет", "есть", "ли", "что", "где", "какую", "какой", "какие", "я",
    "ставил", "ставила", "когда-то", "выполненной", "выполненным", "выполнено", "отметь", "удали", "удалить",
    "сделал", "сделала", "сделано", "который", "которую", "мы", "нам", "нас", "а", "же", "уже", "там",
    "сегодня", "завтра", "вчера", "послезавтра",
}


@dataclass
class Period:
    start: date
    end: date
    label: str          # {period} в text: «на сегодня», «на этой неделе»…
    label_speech: str   # то же для speech


@dataclass
class Parse:
    intent: str = "unknown"  # create list search help thanks off_topic delete complete unknown
    type: str | None = None
    text: str | None = None
    date: date | None = None
    date_kind: str = "exact"
    time: str | None = None
    time_ambiguous: bool = False
    period: Period | None = None
    filter_type: str | None = None
    keywords: list[str] = field(default_factory=list)
    ask: str | None = None      # when | exists
    tense: str | None = None    # past | future
    vague_period: bool = False  # «на следующей неделе» без дня у создания
    has_subject: bool = True    # у встречи есть участник или тема
    thanks: bool = False        # в сообщении есть благодарность


# ── Время ─────────────────────────────────────────────

TIME_HM = re.compile(r"(?:\bв\s+|\bна\s+|^|\s)(\d{1,2})[:.](\d{2})\b", I)
TIME_H = re.compile(r"\bв\s+(\d{1,2})(?:\s*(?:час(?:а|ов)?|ч\.?))?(?:\s+(утра|дня|вечера|ночи))?(?=\s|$|[,.!?])", I)
TIME_WORDS = re.compile(r"\b(утром|вечером|днём|днем)\b", I)


def _parse_time(text: str) -> tuple[str | None, bool, list[tuple[int, int]]]:
    """Время HH:MM, признак «утро или вечер — неясно» и куски фразы, где оно было."""
    spans: list[tuple[int, int]] = []
    m = TIME_HM.search(text)
    if m:
        h, mm = int(m.group(1)), int(m.group(2))
        if h < 24 and mm < 60:
            spans.append(m.span())
            ampm = re.search(r"\s+(утра|дня|вечера|ночи)\b", text[m.end():m.end() + 8], I)
            if ampm and ampm.group(1).lower() in ("вечера", "дня") and h < 12:
                h += 12
            return f"{h:02d}:{mm:02d}", False, spans
    m = TIME_H.search(text)
    if m:
        h = int(m.group(1))
        part = (m.group(2) or "").lower()
        if h > 23:
            return None, False, spans
        spans.append(m.span())
        ambiguous = False
        if part in ("вечера", "дня") and h < 12:
            h += 12
        elif part == "ночи" and h == 12:
            h = 0
        elif not part:
            word = TIME_WORDS.search(text)
            if word and word.group(1).lower() == "вечером" and h < 12:
                h += 12
            elif word and word.group(1).lower() in ("днём", "днем") and h < 8:
                h += 12
            elif not word and 1 <= h <= 7:
                # «в 7» — утро или вечер? Ставим вечер и переспрашиваем (Р-19)
                h += 12
                ambiguous = True
        return f"{h:02d}:00", ambiguous, spans
    return None, False, spans


# ── Дата ──────────────────────────────────────────────

def _weekday_index(word: str) -> int:
    word = word.lower()
    for stem, index in WEEKDAYS.items():
        if word.startswith(stem):
            return index
    return 0


def _month_index(word: str) -> int:
    word = word.lower()
    for i, name in enumerate(MONTHS_GEN):
        if word[:3] == name[:3]:
            return i
    return 0


@dataclass
class _DateInfo:
    date: date | None = None
    kind: str = "exact"
    period: Period | None = None
    spans: list[tuple[int, int]] = field(default_factory=list)


def _day_period(day: date, today: date, label: str | None = None, speech: str | None = None) -> Period:
    diff = (day - today).days
    if label is None:
        if diff == 0:
            label, speech = "на сегодня", "на сегодня"
        elif diff == 1:
            label, speech = "завтра", "завтра"
        elif diff == -1:
            label, speech = "вчера", "вчера"
        else:
            label, speech = f"на {date_text(day, today)}", f"на {date_speech(day, today)}"
    return Period(day, day, label, speech or label)


def _range_label(start: date, end: date) -> tuple[str, str]:
    if start.month == end.month:
        return (f"с {start.day} по {end.day} {MONTHS_SHORT[end.month - 1]}",
                f"с {start.day} по {end.day} {MONTHS_GEN[end.month - 1]}")
    return (f"с {start.day} {MONTHS_SHORT[start.month - 1]} по {end.day} {MONTHS_SHORT[end.month - 1]}",
            f"с {start.day} {MONTHS_GEN[start.month - 1]} по {end.day} {MONTHS_GEN[end.month - 1]}")


def _parse_date(text: str, now: datetime, time: str | None) -> _DateInfo:
    today = now.date()
    info = _DateInfo()

    def found(m: re.Match, day: date | None = None, kind: str = "exact", period: Period | None = None):
        info.spans.append(m.span())
        if day is not None:
            info.date, info.kind = day, kind
        if period is not None:
            info.period = period

    # Сроки: «до конца недели», «до пятницы», «к пятнице», «до 25 октября»
    m = re.search(r"\b(?:до|к)\s+конц[ау]\s+недели\b", text, I)
    if m:
        found(m, week_bounds(today)[1], "deadline")
    m = m or re.search(rf"\b(?:до|к)\s+{WEEKDAY_RE}\b", text, I)
    if m and not info.date:
        target = _weekday_index(m.group(1))
        found(m, today + timedelta(days=(target - today.weekday()) % 7 or 7), "deadline")
    m2 = re.search(rf"\bдо\s+(\d{{1,2}})\s+{MONTH_RE}\b", text, I)
    if m2 and not info.date:
        try:
            found(m2, date(today.year, _month_index(m2.group(2)) + 1, int(m2.group(1))), "deadline")
        except ValueError:
            pass

    # Периоды: неделя, месяц
    m = re.search(r"\b(?:на|в)\s+(?:эт(?:ой|у)|текущ(?:ей|ую))\s+недел[еюи]\b", text, I)
    if m:
        s, e = week_bounds(today)
        found(m, period=Period(s, e, "на этой неделе", "на этой неделе"))
    m = re.search(r"\b(?:на|в)\s+следующ(?:ей|ую)\s+недел[еюи]\b", text, I)
    if m:
        s, e = week_bounds(today + timedelta(days=7))
        found(m, period=Period(s, e, "на следующей неделе", "на следующей неделе"))
    m = re.search(r"\b(?:на|в)\s+прошл(?:ой|ую)\s+недел[еюи]\b", text, I)
    if m:
        s, e = week_bounds(today - timedelta(days=7))
        found(m, period=Period(s, e, "на прошлой неделе", "на прошлой неделе"))
    m = re.search(rf"\bв\s+{MONTH_PREP_RE}\b", text, I)
    if m:
        index = MONTHS_PREP.index(m.group(1).lower())
        year = today.year + (1 if index + 1 < today.month - 6 else 0)
        start = date(year, index + 1, 1)
        end = (date(year + (index == 11), (index + 1) % 12 + 1, 1) - timedelta(days=1))
        found(m, period=Period(start, end, f"в {MONTHS_PREP[index]}", f"в {MONTHS_PREP[index]}"))
    m = re.search(r"\bв\s+(?:этом|текущем)\s+месяце\b", text, I)
    if m:
        start = today.replace(day=1)
        end = (start.replace(month=start.month % 12 + 1, year=start.year + (start.month == 12)) - timedelta(days=1))
        found(m, period=Period(start, end, "в этом месяце", "в этом месяце"))

    # Конкретный день
    if not info.date:
        m = re.search(r"\b(?:на\s+)?(позавчера|вчера|сегодня|послезавтра|завтра)\b", text, I)
        if m:
            shift = {"позавчера": -2, "вчера": -1, "сегодня": 0, "завтра": 1, "послезавтра": 2}[m.group(1).lower()]
            found(m, today + timedelta(days=shift))
    if not info.date:
        m = re.search(rf"\b(?:в|во|на)\s+(прошл(?:ый|ую|ое)|следующ(?:ий|ую|ее)|эт(?:от|у|о))?\s*{WEEKDAY_RE}\b", text, I)
        if m:
            target = _weekday_index(m.group(2))
            which = (m.group(1) or "").lower()
            if which.startswith("прошл"):
                delta = (today.weekday() - target) % 7 or 7
                day = today - timedelta(days=delta)
            elif which.startswith("следующ"):
                day = week_bounds(today + timedelta(days=7))[0] + timedelta(days=target)
            else:
                day = today + timedelta(days=(target - today.weekday()) % 7)
                # Сегодняшний день недели, но время уже прошло — значит, через неделю
                if day == today and time and time <= now.strftime("%H:%M"):
                    day += timedelta(days=7)
            found(m, day)
    if not info.date:
        m = re.search(rf"\b(?:на\s+)?(\d{{1,2}})\s+{MONTH_RE}(?:\s+(\d{{4}}))?\b", text, I)
        if m:
            try:
                year = int(m.group(3)) if m.group(3) else today.year
                found(m, date(year, _month_index(m.group(2)) + 1, int(m.group(1))))
            except ValueError:
                pass
    if not info.date:
        m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b(?!:)", text)
        if m and not re.search(r"\d[:.]\d{2}\b", m.group(0)):
            try:
                if m.group(1):
                    found(m, date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
                else:
                    found(m, date(int(m.group(6) or today.year), int(m.group(5)), int(m.group(4))))
            except ValueError:
                pass
    return info


# ── Ключевые слова для поиска ─────────────────────────

def stem(word: str) -> str:
    """Грубая основа слова: «Иваном» и «Иван» → «ива», «договору» → «догов»."""
    word = word.lower().replace("ё", "е")
    return word if len(word) <= 3 else word[: max(3, len(word) - 2)]


def keywords(text: str) -> list[str]:
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", text)
    return [stem(w) for w in words if w.lower().replace("ё", "е") not in STOPWORDS and len(w) >= 2 and not w.isdigit()]


def _filter_type(text: str) -> str | None:
    lower = text.lower()
    if re.search(MEETING_WORD_RE, lower):
        return "meeting"
    if re.search(r"напоминани", lower):
        return "reminder"
    if re.search(r"\bзадач", lower):
        return "task"
    return None


def _cut(text: str, spans: list[tuple[int, int]]) -> str:
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + " " + text[end:]
    return text


# ── Главная функция ───────────────────────────────────

THANKS_RE = re.compile(r"\b(спасибо|благодарю|благодарствую|спс)\b[,!.\s]*(стивенс|stevens)?[,!.]*", I)
HELP_RE = re.compile(r"(что\s+ты\s+умеешь|что\s+умеешь|чем\s+(?:ты\s+)?(?:можешь\s+)?помочь|^помощь|^справка|как\s+(?:тобой|этим)\s+пользоваться)", I)
DELETE_RE = re.compile(r"^(?:пожалуйста\s+)?(удали(?:те)?|удалить|убери|сотри)\b", I)
COMPLETE_RE = re.compile(rf"(\bотметь\b.*\bвыполнен|\bя\s+(?:уже\s+)?(?:сделал|сделала|выполнил|выполнила|закончил|закончила)\b|^(?:сделал|сделала|выполнил|выполнила)\b|\bотметь\b.*\bсделан)", I)
SEARCH_RE = re.compile(rf"(\bнайди\b|\bнайти\b|\bпоищи\b|\bищи\b|^когда\b(?!-)|\bкогда\s+(?:у\s+меня\s+)?(?:был|была|было|будет)\b|\bставил)", I)
LIST_RE = re.compile(rf"(что\s+у\s+меня|какие\s+(?:у\s+меня\s+)?(?:планы|дела|задачи|встречи|напоминания)|^покажи|что\s+(?:я\s+)?запланировано|есть\s+ли\s+у\s+меня|что\s+(?:было|будет)|мо[её]\s+расписание|\bпланы\s+на\b|чем\s+я\s+занят)", I)
OFFTOPIC_RE = re.compile(r"(погод|анекдот|шутк|курс\s+(?:доллар|евро|валют)|новост|рецепт|кто\s+так|переведи|столиц|сколько\s+будет|расскажи\s+(?:о|про)\s+себе|как\s+дела|фильм|музык|игр[ау]|стих)", I)
CREATE_VERB_RE = re.compile(r"^(?:пожалуйста\s+)?(напомни(?:те)?(?:\s+мне)?|поставь|запиши|добавь|создай|запланируй|назначь|внеси|заведи)\b", I)
REMIND_RE = re.compile(r"(^напомни|\bнапомни\b|\bнапоминани)", I)


def parse(raw: str, now: datetime) -> Parse:
    text = " ".join(raw.strip().split())
    result = Parse()

    # Благодарность: одна — thanks; с просьбой — выполняем просьбу (Р-124)
    thanks = THANKS_RE.search(text)
    if thanks:
        result.thanks = True
        rest = _cut(text, [thanks.span()]).strip(" ,.!")
        if not rest:
            result.intent = "thanks"
            return result
        text = rest

    lower = text.lower()
    time, ambiguous, time_spans = _parse_time(text)
    info = _parse_date(text, now, time)

    if HELP_RE.search(lower):
        result.intent = "help"
        return result

    if DELETE_RE.search(lower) or COMPLETE_RE.search(lower):
        result.intent = "delete" if DELETE_RE.search(lower) else "complete"
        result.filter_type = _filter_type(lower)
        rest = _cut(text, info.spans + time_spans)
        result.keywords = keywords(rest)
        result.date = info.date
        result.time = time if not ambiguous else None
        return result

    if SEARCH_RE.search(lower) and not CREATE_VERB_RE.search(lower):
        result.intent = "search"
        result.filter_type = _filter_type(lower)
        if re.search(r"\bкогда\b(?!-)", lower):
            result.ask = "when"
            result.tense = "past" if re.search(r"\b(был|была|было|были)\b", lower) else "future"
        rest = _cut(text, info.spans + time_spans)
        result.keywords = keywords(rest)
        if info.period:
            result.period = info.period
        elif info.date:
            result.period = _day_period(info.date, now.date())
        return result

    if LIST_RE.search(lower) and not CREATE_VERB_RE.search(lower):
        result.intent = "list"
        result.filter_type = _filter_type(lower)
        if re.search(r"есть\s+ли", lower):
            result.ask = "exists"
        today = now.date()
        if info.period:
            result.period = info.period
        elif info.date:
            result.period = _day_period(info.date, today)
        elif re.search(r"\bна\s+неделю\b|\bнеделе\b", lower):
            s, e = week_bounds(today)
            result.period = Period(s, e, "на этой неделе", "на этой неделе")
        else:
            result.period = _day_period(today, today)
        return result

    if OFFTOPIC_RE.search(lower) and not CREATE_VERB_RE.search(lower):
        result.intent = "off_topic"
        return result

    # Создание
    is_reminder = bool(REMIND_RE.search(lower))
    is_meeting = bool(re.search(MEETING_WORD_RE, lower)) and not is_reminder
    has_verb = bool(CREATE_VERB_RE.search(lower))
    has_need = bool(re.search(r"\b(нужно|надо|необходимо|не\s+забыть)\b", lower))
    is_task_word = bool(re.search(r"^(?:поставь|запиши|добавь|создай)\s+задач", lower))
    if not (has_verb or is_meeting or has_need or is_task_word or ((info.date or time) and len(keywords(_cut(text, info.spans + time_spans))) >= 1)):
        return result  # unknown

    result.intent = "create"
    result.type = "reminder" if is_reminder else "meeting" if is_meeting else "task"
    result.time = time
    result.time_ambiguous = ambiguous
    result.date = info.date
    result.date_kind = info.kind if info.date else ("none" if result.type == "task" and not time else "exact")
    result.vague_period = bool(info.period) and not info.date

    body = _cut(text, info.spans + time_spans)
    body = re.sub(r"^\s*(?:пожалуйста\s+)?(?:напомни(?:те)?|поставь|запиши|добавь|создай|запланируй|назначь|внеси|заведи)(?:\s+мне)?\b", " ", body, flags=I)
    body = re.sub(r"^\s*(?:новую\s+|новое\s+)?(?:задачу|задача|напоминание)\b", " ", body, flags=I)
    body = re.sub(r"\b(?:у\s+меня|мне|нужно|надо|необходимо|не\s+забыть|пожалуйста)\b", " ", body, flags=I)
    body = re.sub(r"\b(?:утром|вечером|днём|днем)\b", " ", body, flags=I)
    body = " ".join(body.split()).strip(" ,.:;!—-")
    if result.type == "reminder":
        body = re.sub(r"^(?:про|о|об|насчёт|насчет)\s+", "", body, flags=I)
    # Существительное встречи — в именительный падеж: «встречу с Иваном» → «Встреча с Иваном»
    first = body.split(" ", 1)
    if first and first[0].lower() in MEETING_NOUNS:
        noun = MEETING_NOUNS[first[0].lower()]
        rest = first[1] if len(first) > 1 else ""
        result.has_subject = bool(keywords(rest))
        body = f"{noun} {rest}".strip()
    elif result.type == "meeting":
        result.has_subject = bool(keywords(body))
    body = body.strip(" ,.:;!—-")
    result.text = capitalize(body) if body else None
    return result


def parse_reply(raw: str, now: datetime) -> Parse:
    """Ответ на уточнение: только дата, время или участник («в 15», «завтра», «с Иваном»)."""
    return parse(raw, now)


def describe_period(start: date, end: date, today: date) -> Period:
    if start == end:
        return _day_period(start, today)
    label, speech = _range_label(start, end)
    return Period(start, end, label, speech)
