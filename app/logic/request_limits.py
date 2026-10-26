"""Ограниченные по памяти локальные лимиты и чтение тела до запуска обработчика."""
import asyncio
from collections import OrderedDict, deque
import hashlib
import math
import os
import time

from starlette.responses import JSONResponse


class RequestLimits:
    """Один процесс: лимиты IP + владельца; за кластером нужен общий edge-limiter."""
    def __init__(self, app):
        self.app = app
        self.windows = OrderedDict()
        self.clients = OrderedDict()
        self.auth_slots = asyncio.Semaphore(2)
        self.stt_slots = asyncio.Semaphore(4)
        self.chat_slots = asyncio.Semaphore(8)
        self.import_slots = asyncio.Semaphore(2)

    def hit(self, key, limit):
        now = time.monotonic()
        window = self.windows.pop(key, deque())
        while window and window[0] <= now - 60:
            window.popleft()
        wait = max(1, math.ceil(60 - (now - window[0]))) if len(window) >= limit else 0
        if not wait:
            window.append(now)
        self.windows[key] = window
        while len(self.windows) > 10000:
            self.windows.popitem(last=False)
        return wait

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path == "/api/health" or scope["method"] == "OPTIONS":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        ip = (scope.get("client") or ("unknown", 0))[0]
        # X-Forwarded-For не принимаем от произвольных клиентов.
        if ip in {p.strip() for p in os.getenv("STEVENS_TRUSTED_PROXIES", "").split(",") if p.strip()}:
            forwarded = headers.get(b"x-forwarded-for", b"").decode("ascii", "ignore")
            if forwarded and "," not in forwarded:
                ip = forwarded.strip()
        auth = path in ("/api/auth/login", "/api/auth/register")
        group, limit = ("auth", 30) if auth else ("transfer", 20) if "/import" in path or "/transfer" in path or path.endswith("/export") else (
            ("stt", 30) if path == "/api/stt" else ("reset", 10) if path in ("/api/sandbox/reset", "/api/sandbox/clear") else ("api", 180))
        if os.getenv("STEVENS_RATE_LIMIT", "1") != "0":
            wait = self.hit((ip, group), limit)
            client_id = headers.get(b"x-client-id") if not headers.get(b"authorization") else None
            if client_id and not wait:
                key = (ip, hashlib.sha256(client_id).digest())
                if key not in self.clients:
                    wait = self.hit((ip, "new_sandbox"), 10)
                if not wait:
                    self.clients.pop(key, None)
                    self.clients[key] = time.monotonic()
                    while len(self.clients) > 10000:
                        self.clients.popitem(last=False)
            identity = headers.get(b"authorization") or headers.get(b"x-client-id")
            if identity and not wait:
                digest = hashlib.sha256(identity).digest()
                wait = self.hit((digest, group), limit if auth else min(limit, 120))
            if wait:
                return await JSONResponse({"error": "rate_limited"}, status_code=429,
                                          headers={"Retry-After": str(wait)})(scope, receive, send)
        slots = (self.auth_slots if auth else self.stt_slots if path == "/api/stt" else
                 self.chat_slots if path == "/api/chat" else self.import_slots if path.endswith(("/import", "/apply", "/preview", "/export")) else None)
        if slots:
            try:
                await asyncio.wait_for(slots.acquire(), timeout=0.5)
            except TimeoutError:
                return await JSONResponse({"error": "rate_limited"}, status_code=429,
                                          headers={"Retry-After": "1"})(scope, receive, send)
        try:
            if scope["method"] not in ("POST", "PATCH", "PUT"):
                return await self.app(scope, receive, send)
            max_size = 1024 * 1024 if path == "/api/stt" else 8 * 1024 * 1024 if "import" in path or "/transfer" in path else 4096 if auth else 65536
            status, error = (413, "audio_too_long") if path == "/api/stt" else (422, "invalid_request")
            try:
                if int(headers.get(b"content-length", b"0")) > max_size:
                    return await JSONResponse({"error": error}, status_code=status)(scope, receive, send)
            except ValueError:
                return await JSONResponse({"error": "invalid_request"}, status_code=422)(scope, receive, send)
            body = bytearray()
            deadline = time.monotonic() + 15
            while True:
                try:
                    message = await asyncio.wait_for(receive(), timeout=max(0.01, deadline - time.monotonic()))
                except TimeoutError:
                    return await JSONResponse({"error": "invalid_request"}, status_code=422)(scope, receive, send)
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > max_size:
                    return await JSONResponse({"error": error}, status_code=status)(scope, receive, send)
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            delivered = False
            async def bounded_receive():
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            await self.app(scope, bounded_receive, send)
        finally:
            if slots:
                slots.release()
