import asyncio, os, sys, uuid
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app.main import app
from app.routers import chat as chatmod
used=[]; orig=chatmod.render
chatmod.render=lambda tid,*a,**k:(used.append(tid),orig(tid,*a,**k))[1]
CLOCK = "2026-10-21T10:00:00+03:00"
CASES = [
 ("Д-1", [("Отметь задачу передать отчёт на согласование выполненной", None, "completed", "completed")]),
 ("Д-2", [("Отметь встречу с Марией по интеграции выполненной", None, "clarify", "completed_meeting_no")]),
 ("Д-3", [("Удали встречу с Марией в субботу", None, "deleted", "deleted")]),
 ("Д-4", [("Удали встречу с Марией в субботу", None, "deleted", "deleted"), ("", "restore", "created", "restored")]),
 ("Д-5", [("Удали задачу про договор", None, "clarify", "which_one")]),
 ("Д-6", [("Напомни завтра в 10 позвонить Ивану", None, "created", "created_reminder"), ("", "undo", "deleted", "undo_done")]),
 ("Д-7", [("Удали встречу с Марией в субботу", None, "not_understood", "not_understood")]),
]
async def main():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            for name, turns in CASES:
                cid = "d-" + uuid.uuid4().hex[:12]
                h = {"X-Client-Id": cid}
                if name != "Д-7": h["X-Stevens-Features"] = "d2,d3,d10"
                await c.post("/api/sandbox/reset", headers=h)
                conv = str(uuid.uuid4()); last=None
                for text, act, kind, tpl in turns:
                    used.clear()
                    b = {"conversation_id": conv, "text": text, "source": "text", "client_time": CLOCK, "timezone": "Europe/Moscow"}
                    if act:
                        btn = next(x for x in last["buttons"] if x["send"].get("action", {}).get("id") == act)
                        b["action"] = btn["send"]["action"]; b["text"] = btn["label"]; b["source"] = "button"
                    r = (await c.post("/api/chat", json=b, headers=h)).json(); last = r
                    ok = r["kind"] == kind and tpl in used
                    print("OK " if ok else "BAD", name, r["kind"], used, r["text"], [(x["label"][:30], x.get("style")) for x in r["buttons"]], [x["marks"] for x in r["records"]][:2])
asyncio.run(main())
