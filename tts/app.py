"""Озвучка Stevens голосом Silero «aidar». POST /api/tts {"text": "..."} → WAV.

Модель (~100 МБ) скачивается при первом запуске в /models (том tts_models), поэтому сборка образа
не зависит от сайта Silero. Пока модель грузится, /api/tts отвечает 503 — фронт говорит голосом браузера.
"""
import io
import os
import threading
import wave
from collections import OrderedDict

import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from normalize import normalize

SPEAKER = "aidar"
# 24 кГц заметно быстрее 48 кГц на слабом процессоре Codespaces, на слух почти не отличается
RATE = int(os.getenv("TTS_RATE", "24000"))
MODEL_URL = os.getenv("SILERO_MODEL_URL", "https://models.silero.ai/models/tts/ru/v4_ru.pt")
MODEL_PATH = os.path.join(os.getenv("MODELS_DIR", "/models"), "v4_ru.pt")

torch.set_num_threads(int(os.getenv("TTS_THREADS", str(os.cpu_count() or 2))))
app = FastAPI(title="Stevens TTS")

model = None
load_error: str | None = None
lock = threading.Lock()
cache: "OrderedDict[str, bytes]" = OrderedDict()
CACHE_SIZE = 200


def load() -> None:
    global model, load_error
    try:
        if not os.path.exists(MODEL_PATH):
            os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
            print("скачиваю модель Silero:", MODEL_URL, flush=True)
            tmp = MODEL_PATH + ".part"
            torch.hub.download_url_to_file(MODEL_URL, tmp)
            os.replace(tmp, MODEL_PATH)
        m = torch.package.PackageImporter(MODEL_PATH).load_pickle("tts_models", "model")
        m.to(torch.device("cpu"))
        # Прогрев: первая фраза после загрузки идёт в разы дольше, пусть это случится до первого ответа
        m.apply_tts(text="Добрый день.", speaker=SPEAKER, sample_rate=RATE, put_accent=True, put_yo=True)
        model = m
        print("модель готова, голос", SPEAKER, flush=True)
    except Exception as exc:  # без модели сервис живёт и отвечает 503 — фронт уйдёт на голос браузера
        load_error = repr(exc)
        print("модель не загрузилась:", load_error, flush=True)


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=load, daemon=True).start()


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


def to_wav(audio: torch.Tensor) -> bytes:
    pcm = (audio.clamp(-1, 1) * 32767).to(torch.int16).numpy().tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(pcm)
    return buf.getvalue()


@app.get("/api/tts/health")
def health():
    if model is None:
        raise HTTPException(503, load_error or "модель загружается")
    return {"ok": True, "speaker": SPEAKER}


@app.post("/api/tts")
def tts(body: TtsIn):
    if model is None:
        raise HTTPException(503, load_error or "модель загружается")
    text = normalize(body.text)
    if not text.strip():
        raise HTTPException(422, "нечего произносить")
    wav = cache.get(text)
    if wav is None:
        with lock:  # модель не потокобезопасна
            audio = model.apply_tts(text=text, speaker=SPEAKER, sample_rate=RATE, put_accent=True, put_yo=True)
        wav = to_wav(audio)
        cache[text] = wav
        if len(cache) > CACHE_SIZE:
            cache.popitem(last=False)
    else:
        cache.move_to_end(text)
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})
