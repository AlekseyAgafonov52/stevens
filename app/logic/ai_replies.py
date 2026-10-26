"""Provider replies may refine draft schedules; only explicit user input approves them."""
from __future__ import annotations
from typing import TYPE_CHECKING

from app.ai.schema import Result

if TYPE_CHECKING:
    from app.routers.chat import Ctx, Pending


async def answer(ctx: Ctx, pending: Pending, result: Result) -> dict | None:
    from app.routers import chat
    value = result.reply
    if result.intent != "reply" or result.confidence < 0.8 or value is None:
        return None
    # A model's interpretation of «yes» is never a user confirmation.
    if pending.kind not in ("draft", "new_time", "confirm_no") or value.kind not in ("time", "day", "day_time"):
        return None
    draft = dict(pending.draft)
    changed = False
    if value.date:
        draft["date"], draft["date_kind"] = value.date, "exact"
        changed = True
    if value.time:
        draft["time"], draft["ambiguous"] = value.time, False
        changed = True
    if not changed:
        return None
    ctx.trace.update(layer="llm", confidence=result.confidence, parse=result.model_dump(mode="json", by_alias=True))
    draft["confirmed"] = False
    draft["doubt"] = [*draft.get("doubt", []), {"why": "llm"}]
    return await chat.process_draft(ctx, draft)
