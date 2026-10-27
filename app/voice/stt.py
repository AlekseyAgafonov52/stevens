"""Серверное распознавание речи через Yandex SpeechKit (контракт v1.6, раздел 4.3)."""
import logging
import os

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from app.voice.audio import AudioError, ogg_opus
from app import features
from app.owner import Owner, get_owner

logger = logging.getLogger(__name__)

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
    if not features.on("stt"):
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
        return {"text": (response.json().get("result") or "").strip()}
    except Exception as error:  
        logger.error("Yandex STT error: %s", type(error).__name__)
        return JSONResponse(status_code=503, content={"error": "stt_unavailable"})
