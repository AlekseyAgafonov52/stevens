"""End-to-end v1.6 wire format, raw STT and persisted telemetry; isolated audit DB."""
import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:contract-test@127.0.0.1:55441/stevens_check")

import httpx
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.main import app
from app.models import ChatLog


async def main():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://contract") as client:
            assert (await client.get("/api/records", params={"from": "2026-10-01", "to": "2026-10-31"})).status_code == 422
            auth = await client.post("/api/auth/register", json={"login": "v16" + uuid4().hex[:12], "password": "test-password"})
            assert auth.status_code == 200, auth.text
            headers = {"Authorization": "Bearer " + auth.json()["token"]}
            body = {"conversation_id": str(uuid4()), "text": "напоминание: оплатить интернет", "source": "voice",
                    "client_time": "2026-10-21T10:00:00+03:00", "timezone": "Europe/Moscow", "raw_text": "напоминание оплатить интернет"}
            for field in ("conversation_id", "text", "source", "client_time", "timezone"):
                result = await client.post("/api/chat", headers=headers, json={k: v for k, v in body.items() if k != field})
                assert result.status_code == 422, (field, result.text)
            result = await client.post("/api/chat", headers=headers, json=body)
            assert result.status_code == 200 and result.json()["kind"] == "clarify", result.text
            # v1.6 does not need the legacy X-Stevens-Features header.
            result = await client.post("/api/chat", headers=headers, json={**body, "text": "завтра в 13"})
            assert result.json()["kind"] == "created", result.text
            assert any(b["send"].get("action", {}).get("id") == "undo" for b in result.json()["buttons"])
            result = await client.post("/api/chat", headers=headers, json={**body, "text": "удали её"})
            assert result.json()["kind"] == "deleted", result.text
            async with AsyncSessionLocal() as db:
                logs = list((await db.execute(select(ChatLog).where(ChatLog.conversation_id == body["conversation_id"]))).scalars())
                assert len(logs) == 3
                assert all(r.layer == "rules" and r.confidence is not None and r.parsed is not None and json.loads(r.parsed) for r in logs)
                assert logs[0].raw_text == body["raw_text"]
            result = await client.post("/api/stt", headers={**headers, "Content-Type": "audio/mpeg"}, content=b"bad")
            assert result.status_code == 415, result.text
            with patch.dict(os.environ, {"YANDEX_API_KEY": "", "YANDEX_FOLDER_ID": ""}):
                result = await client.post("/api/stt", headers={**headers, "Content-Type": "audio/webm"}, content=b"webm")
                assert result.status_code == 503, result.text
            original = httpx.AsyncClient
            observed = []

            def upstream(request):
                assert request.content == b"OggS-test"
                assert request.url.params["format"] == "oggopus"
                observed.append(True)
                return httpx.Response(200, json={"result": "Проверено"})

            def provider_client(*args, **kwargs):
                return original(*args, **kwargs, transport=httpx.MockTransport(upstream))

            with patch.dict(os.environ, {"YANDEX_API_KEY": "test", "YANDEX_FOLDER_ID": "test"}), \
                    patch("app.voice.stt.ogg_opus", new=AsyncMock(return_value=b"OggS-test")), \
                    patch("app.voice.stt.httpx.AsyncClient", provider_client):
                result = await client.post("/api/stt", headers={**headers, "Content-Type": "audio/webm;codecs=opus"}, content=b"webm")
                assert result.status_code == 200 and result.json() == {"text": "Проверено"}, result.text
            assert observed == [True]
            with patch.dict(os.environ, {"STEVENS_FEATURES": "f2,f3"}):
                assert (await client.get("/api/records/export", headers=headers)).status_code == 404
    print("PASS: v1.6 required fields/mode, legacy-free deletion, persisted AI telemetry, raw STT, import feature gate")


if __name__ == "__main__":
    asyncio.run(main())
