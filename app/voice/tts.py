"""Озвучка ответов через Yandex SpeechKit.
 
Яндекс — основной голос, браузерный `speechSynthesis` (раздел 9) остаётся запасным:
сервер отвечает 503, и фронт озвучивает сам. Так Стивенс не замолкает ни при сбое
сети, ни при исчерпанной квоте.
 
Вход:  POST /api/tts, {"text": "…"} — короткая фраза из поля speech.
Выход: 200 audio/mpeg (MP3) — готовый звук. MP3, а не Ogg: Safari Ogg не проигрывает.
       422 invalid_request   — пустой текст или длиннее TTS_MAX_CHARS.
       503 tts_unavailable   — нет ключа, пауза после сбоя или служба не ответила.
"""
import logging
import os
import re
import time
from collections import OrderedDict
 
import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
 
from app import features, nlu
from app.owner import Owner, get_owner
 
logger = logging.getLogger(__name__)
 
router = APIRouter()
 
TTS_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
# Стивенс говорит о себе в мужском роде (раздел 0.3), поэтому мужской голос.
VOICE = os.getenv("STEVENS_TTS_VOICE", "filipp")
# Скорость речи: 1.0 — обычная, меньше — медленнее.
SPEED = os.getenv("STEVENS_TTS_SPEED", "0.9")
# Поле speech короткое по контракту (раздел 6): список вслух не читаем.
TTS_MAX_CHARS = 1000
# Шаблоны повторяются («К вашим услугам», «Готово: …»), поэтому держим готовый звук
# в памяти: это снимает и задержку перед ответом, и плату за повторный синтез.
CACHE_LIMIT = 256
# После сбоя столько секунд службу не трогаем: фронт получает 503 сразу и озвучивает
# браузером без ожидания. Та же пауза, что у нейросети в app/ai/understanding.py.
PAUSE_SECONDS = 60
 
# Цифру Яндекс читает в мужском роде: «1 дело» звучит как «один дело». Перед синтезом
# ставим числительное в род слова после него. Дни месяца и годы не трогаем:
# «21 октября» — порядковое, его Яндекс читает сам.
_MONTHS = {"января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
           "сентября", "октября", "ноября", "декабря"}
_ONE = {"masc": "один", "femn": "одна", "neut": "одно"}
_TWO = {"masc": "два", "femn": "две", "neut": "два"}
_COUNT_RE = re.compile(r"\b(\d+)\s+([А-Яа-яЁё]+)")
_PREV_WORD_RE = re.compile(r"([А-Яа-яЁё]+)\s*$")
 
_cache: OrderedDict[str, bytes] = OrderedDict()
# Одно соединение на все фразы: без него каждая платит за TLS, а первая не успевает за 2–4 с
_client = httpx.AsyncClient(timeout=10)
_blocked_until = 0.0
 
 
class Speech(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=TTS_MAX_CHARS)

_DAYS = {"пн": "понедельник", "вт": "вторник", "ср": "среду", "чт": "четверг", "пт": "пятницу", "сб": "субботу", "вс": "воскресенье"}
_MONTHS = {"янв": "января", "фев": "февраля", "мар": "марта", "апр": "апреля", "ма": "мая", "июн": "июня",
           "июл": "июля", "авг": "августа", "сен": "сентября", "окт": "октября", "ноя": "ноября", "дек": "декабря"}
_ORD = ["перв", "втор", "трет", "четвёрт", "пят", "шест", "седьм", "восьм", "девят", "десят", "одиннадцат", "двенадцат",
        "тринадцат", "четырнадцат", "пятнадцат", "шестнадцат", "семнадцат", "восемнадцат", "девятнадцат", "двадцат"]
_DAY_RE = re.compile(r"(?<![а-яё])(пн|вт|ср|чт|пт|сб|вс)(?=,?\s*\d)", re.I)
# «на 1 ноя», «на вс, 1 ноя» — винительный («на первое»); иначе родительный («встреча первого ноября», «с первого»)
_DATE_RE = re.compile(
    r"(?:(?<![а-яё])(на|(?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье),)\s+)?(?<![\d.:])(\d{1,2})\s+"
    r"(январ[яь]|феврал[яь]|марта?|апрел[яь]|ма[яй]|июн[яь]|июл[яь]|августа?|сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь]|"
    r"янв|фев|мар|апр|июн|июл|авг|сен|окт|ноя|дек)(?:\.(?=\s+[а-яё]))?(?![а-яё])", re.I)


def _ordinal(n: int, accusative: bool) -> str:
    tens, unit = ("", n) if n <= 20 else (("двадцать ", n - 20) if n < 30 else ("тридцать ", n - 30))
    if unit == 0:
        return "тридцатое" if accusative else "тридцатого"
    stem = _ORD[unit - 1]
    if stem == "трет":
        return tens + ("третье" if accusative else "третьего")
    return tens + stem + ("ое" if accusative else "ого")


def _date(match: re.Match) -> str:
    before, day, month = match.group(1), int(match.group(2)), match.group(3).lower()
    if not 1 <= day <= 31:
        return match.group(0)
    full = _MONTHS["ма" if month in ("мая", "май") else month[:3]]
    return (f"{before} " if before else "") + f"{_ordinal(day, bool(before))} {full}"


def expand_dates(text: str) -> str:
    """Даты для голоса: «на вс, 1 ноя» → «на воскресенье, первое ноября». Цифрой Яндекс читает «один ноября»."""
    return _DATE_RE.sub(_date, _DAY_RE.sub(lambda m: _DAYS[m.group(1).lower()], text))
 
def agree_numbers(text: str) -> str:
    """«1 дело» → «одно дело», «2 встречи» → «две встречи», «Нашёл 1 запись» → «Нашёл одну запись».
 
    Род берём у слова после числа. Падеж важен только для женского «одна/одну»:
    после переходного глагола («нашёл», но не «остаётся») — винительный.
    Остаток пишем цифрой — «20 одна» Яндекс прочтёт как «двадцать одна».
    Без морфологии возвращаем как есть: лучше «один дело», чем молчание.
    """
    morph = nlu._MORPH
    if morph is None:
        return text
 
    def transitive_before(position: int) -> bool:
        prev = _PREV_WORD_RE.search(text[:position])
        if not prev:
            return False
        parse = morph.parse(prev.group(1))[0]
        return parse.tag.POS in ("VERB", "INFN") and parse.tag.transitivity == "tran"
 
    def fix(m: re.Match[str]) -> str:
        number, word = int(m.group(1)), m.group(2)
        last = number % 10
        if last not in (1, 2) or number % 100 in (11, 12):
            return m.group(0)
        low = word.lower()
        if low in _MONTHS or low.startswith("год"):
            return m.group(0)
        forms = _ONE if last == 1 else _TWO
        gender = next((p.tag.gender for p in morph.parse(word) if p.tag.gender in forms), None)
        if gender is None:
            return m.group(0)
        numeral = forms[gender]
        if numeral == "одна" and transitive_before(m.start()):
            numeral = "одну"
        rest = number - last
        spoken = f"{numeral} {word}"
        return f"{rest} {spoken}" if rest else spoken
 
    return _COUNT_RE.sub(fix, text)
 

# Ударения в омографах, которые Яндекс читает не так: «3 дела» звучало как «делА».
# Знак «+» перед ударной гласной — разметка SpeechKit.
_STRESS = [(re.compile(r"(\b(?:\d+|два|две|три|четыре)\s+)дела\b"), r"\1д+ела")]


def stress_marks(text: str) -> str:
    for pattern, replacement in _STRESS:
        text = pattern.sub(replacement, text)
    return text


def _fail(reason: str) -> JSONResponse:
    """Пауза и контрактная ошибка. Наружу — только код, без трассировки и тела ответа."""
    global _blocked_until
    _blocked_until = time.monotonic() + PAUSE_SECONDS
    logger.error("Yandex TTS: %s", reason)
    return JSONResponse(status_code=503, content={"error": "tts_unavailable"})
 
 
@router.post("/api/tts")
async def synthesize(body: Speech, owner: Owner = Depends(get_owner)):
    if not features.on("tts"):
        return JSONResponse(status_code=503, content={"error": "tts_unavailable"})
    text = stress_marks(agree_numbers(expand_dates(" ".join(body.text.split()))))
    if not text:
        return JSONResponse(status_code=422, content={"error": "invalid_request"})
 
    # Кеш проверяем до паузы: уже озвученная фраза звучит даже когда служба недоступна.
    key = f"{VOICE}|{SPEED}|{text}"
    if cached := _cache.get(key):
        _cache.move_to_end(key)
        return Response(content=cached, media_type="audio/mpeg")
    if time.monotonic() < _blocked_until:
        return JSONResponse(status_code=503, content={"error": "tts_unavailable"})
 
    form = {
        "text": text,
        "lang": "ru-RU",
        "voice": VOICE,
        "format": "mp3",
        "folderId": os.getenv("YANDEX_FOLDER_ID") or "",
        "speed": SPEED,
    }
    headers = {"Authorization": f"Api-Key {os.getenv('YANDEX_API_KEY')}"}
    try:
        response = await _client.post(TTS_URL, data=form, headers=headers)
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        # Код ответа отличает «нет прав, не тот каталог или кончилась квота» (4xx)
        # от сбоя службы (5xx). Тело не пишем — политика app/ai/provider.py.
        return _fail(f"HTTP {error.response.status_code}")
    except Exception as error:  # noqa: BLE001 — наружу всегда контрактная ошибка
        return _fail(type(error).__name__)
 
    audio = response.content
    if not audio:
        return _fail("empty_audio")
    _cache[key] = audio
    while len(_cache) > CACHE_LIMIT:
        _cache.popitem(last=False)
    return Response(content=audio, media_type="audio/mpeg")

