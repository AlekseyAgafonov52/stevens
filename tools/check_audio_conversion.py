"""Проверка STT на настоящем WebM; запуск в backend-образе с ffmpeg, без внешнего API."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost/unused")
os.environ.update(YANDEX_API_KEY="synthetic-test", YANDEX_FOLDER_ID="synthetic-test")
import httpx
from starlette.requests import Request
from app.voice.audio import AudioError, ogg_opus
from app.voice.stt import transcribe as stt
from app.owner import Owner


async def main():
    with TemporaryDirectory(prefix="stevens-audio-check-") as directory:
        base = Path(directory)
        def generate(name, seconds):
            file = base / name
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                f"sine=frequency=440:duration={seconds}", "-ac", "2", "-c:a", "libopus", "-b:a", "16k", str(file)], check=True)
            return file.read_bytes()
        webm = generate("short.webm", 0.5)
        normalized = await ogg_opus(webm, "audio/webm")
        assert normalized.startswith(b"OggS")
        output = base / "normalized.ogg"
        output.write_bytes(normalized)
        stream = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)]))["streams"][0]
        assert stream["channels"] == 1 and stream["codec_name"] == "opus"
        for body, kind, expected in ((b"invalid", "audio/webm", 415), (b"x" * (1024 * 1024 + 1), "audio/ogg", 413),
                                     (generate("long.webm", 31), "audio/webm", 413)):
            try:
                await ogg_opus(body, kind)
            except AudioError as error:
                assert error.status == expected
            else:
                raise AssertionError("invalid or long audio accepted")
        observed = []
        original_client = httpx.AsyncClient
        def upstream(request):
            assert request.url.params["format"] == "oggopus"
            assert request.url.params.get("folderId") == "synthetic-test"
            assert request.content.startswith(b"OggS")
            observed.append(True)
            return httpx.Response(200, json={"result": "Проверено"})
        def client(*args, **kwargs):
            return original_client(*args, **kwargs, transport=httpx.MockTransport(upstream))
        async def receive():
            return {"type": "http.request", "body": webm, "more_body": False}
        request = Request({"type": "http", "method": "POST", "path": "/api/stt", "headers": [(b"content-type", b"audio/webm")]}, receive)
        with patch("app.voice.stt.httpx.AsyncClient", client):
            assert await stt(request, owner=Owner(sandbox_id="audio-check")) == {"text": "Проверено"}
        assert observed == [True]
    print("Audio conversion and STT transport: passed (real WebM -> mono Ogg Opus; invalid/long rejected; no external API).")


if __name__ == "__main__":
    asyncio.run(main())
