"""Озвучка ответов через Yandex SpeechKit.

Яндекс — основной голос, браузерный `speechSynthesis` (раздел 9) остаётся запасным:
сервер отвечает 503, и фронт озвучивает сам. Так Стивенс не замолкает ни при сбое
сети, ни при исчерпанной квоте.

Вход:  POST /api/tts, {"text": "…"} — короткая фраза из поля speech.
Выход: 200 audio/ogg (Ogg Opus) — готовый звук.
       422 invalid_request   — пустой текст или длиннее TTS_MAX_CHARS.
       503 tts_unavailable   — нет ключа, пауза после сбоя или служба не ответила.
"""
import logging
import os
import time
from collections import OrderedDict

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app import features
from app.owner import Owner, get_owner

logger = logging.getLogger(__name__)

router = APIRouter()

TTS_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
# Стивенс говорит о себе в мужском роде (раздел 0.3), поэтому мужской голос.
VOICE = os.getenv("STEVENS_TTS_VOICE", "filipp")
# Поле speech короткое по контракту (раздел 6): список вслух не читаем.
TTS_MAX_CHARS = 1000
# Шаблоны повторяются («К вашим услугам», «Готово: …»), поэтому держим готовый звук
# в памяти: это снимает и задержку перед ответом, и плату за повторный синтез.
CACHE_LIMIT = 256
# После сбоя столько секунд службу не трогаем: фронт получает 503 сразу и озвучивает
# браузером без ожидания. Та же пауза, что у нейросети в app/ai/understanding.py.
PAUSE_SECONDS = 60

_cache: OrderedDict[str, bytes] = OrderedDict()
_blocked_until = 0.0


class Speech(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=TTS_MAX_CHARS)


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
    text = " ".join(body.text.split())
    if not text:
        return JSONResponse(status_code=422, content={"error": "invalid_request"})

    # Кеш проверяем до паузы: уже озвученная фраза звучит даже когда служба недоступна.
    key = f"{VOICE}|{text}"
    if cached := _cache.get(key):
        _cache.move_to_end(key)
        return Response(content=cached, media_type="audio/ogg")
    if time.monotonic() < _blocked_until:
        return JSONResponse(status_code=503, content={"error": "tts_unavailable"})

    form = {
        "text": text,
        "lang": "ru-RU",
        "voice": VOICE,
        "format": "oggopus",
        "folderId": os.getenv("YANDEX_FOLDER_ID") or "",
    }
    headers = {"Authorization": f"Api-Key {os.getenv('YANDEX_API_KEY')}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(TTS_URL, data=form, headers=headers)
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
    return Response(content=audio, media_type="audio/ogg")