"""Серверное распознавание речи через Yandex SpeechKit."""
import logging
import os
import re

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from app.voice.audio import AudioError, ogg_opus
from app import features
from app.owner import Owner, get_owner

logger = logging.getLogger(__name__)

# Латинские сокращения SpeechKit в русском режиме пишет кириллицей наугад:
# «CRM» → «си роям», «си рэ эм», а с предлогом и вовсе «посираем».
# Возвращаем исходное написание — оно есть в демо-данных и тестовых фразах.
_CRM_RE = re.compile(r"\b(?:(по)\s*с[иеэ]|си)[\s-]*(?:ар|эр|рэ|ре|ра|ро|р)[\s-]*(?:эм|ем|ям|ам|м)\b", re.I)


def fix_latin(text: str) -> str:
    return _CRM_RE.sub(lambda m: ("по " if m.group(1) else "") + "CRM", text)
router = APIRouter()

STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
STT_MAX_BYTES = 1024 * 1024


@router.post("/api/stt")
async def transcribe(
    request: Request,
    owner: Owner = Depends(get_owner),
):
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    # Retain compatibility with older clients; v1.6 sends raw audio as the body.
    if content_type == "multipart/form-data":
        form = await request.form()
        file = form.get("file")
        if not isinstance(file, UploadFile):
            return JSONResponse(status_code=422, content={"error": "invalid_request"})
        content_type = (file.content_type or "").split(";")[0].strip().lower()
        audio = await file.read(STT_MAX_BYTES + 1)
    else:
        audio = await request.body()
    if content_type not in ("audio/ogg", "audio/webm"):
        return JSONResponse(status_code=415, content={"error": "unsupported_audio"})
    
    if len(audio) > STT_MAX_BYTES:
        return JSONResponse(status_code=413, content={"error": "audio_too_long"})
    if not audio:
        return {"text": ""}
    if not features.stt_ready():
        return JSONResponse(status_code=503, content={"error": "stt_unavailable"})
    
    try:
        audio = await ogg_opus(audio, content_type)
    except AudioError as error:
        return JSONResponse(status_code=error.status, content={"error": error.code})
    
    params = {
        "lang": "ru-RU",
        "format": "oggopus",
        "folderId": os.getenv("YANDEX_FOLDER_ID"),
    }
    headers = {"Authorization": f"Api-Key {os.getenv('YANDEX_API_KEY')}"}
    
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(STT_URL, params=params, content=audio, headers=headers)
        response.raise_for_status()
        return {"text": fix_latin((response.json().get("result") or "").strip())}
    except httpx.HTTPStatusError as error:
        # Код ответа отличает «нет прав или не тот каталог» (4xx) от сбоя службы (5xx).
        # Тело не пишем — та же политика, что в app/ai/provider.py.
        logger.error("Yandex STT: HTTP %s", error.response.status_code)
        return JSONResponse(status_code=503, content={"error": "stt_unavailable"})
    except Exception as error:
        logger.error("Yandex STT error: %s", type(error).__name__)
        return JSONResponse(status_code=503, content={"error": "stt_unavailable"})
