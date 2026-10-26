"""Single AI boundary: rules and provider return the same validated v1.6 Result."""
import asyncio
import os
import time

from app.ai.rules import parse as parse_rules
from app.ai.schema import Input, Result
from app.ai.provider import InvalidResponse, Unavailable

_blocked_until = 0.0


async def understand(request: Input, *, allow_llm: bool = True, force_llm: bool = False) -> Result:
    global _blocked_until
    fallback = parse_rules(request)
    if not allow_llm:
        return fallback
    if not force_llm:
        if fallback.intent != "unknown" and fallback.confidence >= 0.8:
            return fallback
        if time.monotonic() < _blocked_until or not (os.getenv("YANDEX_API_KEY") and os.getenv("YANDEX_FOLDER_ID")):
            return fallback
    try:
        from brain import parse_user_input
        candidate = await asyncio.wait_for(asyncio.to_thread(parse_user_input, request.text, context=request), timeout=10)
        if not isinstance(candidate, Result):
            raise InvalidResponse("invalid_parse_schema")
        candidate = Result.model_validate(candidate.model_dump(mode="json", by_alias=True))
        if candidate.layer != "llm":
            raise InvalidResponse("invalid_parse_layer")
    except (InvalidResponse, Unavailable, TimeoutError):
        _blocked_until = time.monotonic() + 60
        if force_llm:
            raise
        return fallback
    return candidate if force_llm or candidate.confidence > fallback.confidence else fallback
