"""Серверное распознавание речи через Yandex SpeechKit (контракт v1.6, раздел 4.3)."""
import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, File, UploadFile
from fastapi.responses import JSONResponse

from app.voice.audio import AudioError, ogg_opus

logger = logging.getLogger(__name__)

router = APIRouter()

STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
STT_MAX_BYTES = 1024 * 1024


@router.post("/api/stt")
async def transcribe(
    file: UploadFile = File(..., description="Аудио (ogg/webm, до 1 МБ)"),
):
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ("audio/ogg", "audio/webm"):
        return JSONResponse(status_code=415, content={"error": "unsupported_audio"})
    
    audio = await file.read()
    if len(audio) > STT_MAX_BYTES:
        return JSONResponse(status_code=413, content={"error": "audio_too_long"})
    if not audio:
        return {"text": ""}
    
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
        return {"text": (response.json().get("result") or "").strip()}
    except Exception as error:  
        logger.error("Yandex STT error: %s", type(error).__name__)
        return JSONResponse(status_code=503, content={"error": "stt_unavailable"})