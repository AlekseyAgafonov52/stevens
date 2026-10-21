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
 # Исправления парсинга и плотный график (бэклог, 2026-10-21)
 ("П-1", [("Слушай а ты можешь сделать напоминание о том что 30 декабря созвон с Иваном в 15", None, "created", "created_meeting")]),
 ("П-2", [("Напомни про встречу с Машей 30 декабря в 15", None, "created", "created_meeting")]),
 ("П-3", [("Встреча с Петей 30 декабря в 2:00", None, "confirm", "confirm")]),
 ("П-4", [("Встреча с Петей 30 декабря в 15", None, "created", "created_meeting"),
          ("Созвон с Ваней 30 декабря в 15:15", None, "created", "dense_schedule")]),
 ("П-5", [("Встреча с Петей 30 декабря в 15", None, "created", "created_meeting"),
          ("Задача отправить договор 30 декабря в 15:15", None, "created", "created_task")]),
 # Несколько дел одной фразой
 ("М-1", [("Завтра в 10 созвон с Иваном, потом отправить договор Маше, а в пятницу сдать лабу", None, "confirm", "multi_confirm"),
          ("", "confirm_yes", "created", "multi_created")]),
 ("М-2", [("Напомни завтра в 10 позвонить Ивану и в 12 написать Маше", None, "confirm", "multi_confirm")]),
 ("М-3", [("Созвон с Иваном завтра, потом купить молоко", None, "clarify", "clarify_meeting_time")]),
 # Свободное время
 ("С-1", [("Встреча с Петей 30 декабря в 10", None, "created", "created_meeting"),
          ("Когда я свободен 30 декабря на час?", None, "clarify", "free_slots_plain")]),
 ("С-2", [("Найди время встретиться с Ваней 30 декабря", None, "clarify", "free_slots"),
          ("", "slot", "created", "created_meeting")]),
 ("Б-1", [("", "briefing", "list", "briefing_next")]),
]
EXPECT = {
 "С-2": lambda r: r["records"][0]["text"] == "Встреча с Ваней" and r["records"][0]["time"] == "09:00",
 "С-1": lambda r: [b["label"] for b in r["buttons"]] == ["09:00", "11:00", "13:00"],
 "М-1": lambda r: len(r["records"]) == 3 and all("new" in x["marks"] for x in r["records"]),
 "М-2": lambda r: [x["type"] for x in r["records"]] == ["reminder", "reminder"],
 "П-1": lambda r: r["records"][0]["text"] == "Созвон с Иваном" and r["records"][0]["type"] == "meeting",
 "П-2": lambda r: r["records"][0]["text"] == "Встреча с Машей",
 "П-3": lambda r: r["records"][0]["time"] == "14:00",
 "П-4": lambda r: len(r["records"]) == 2 and "15 минут" in r["text"],
 "П-5": lambda r: len(r["records"]) == 1,
}
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
                        if act == "briefing":  # фронт шлёт действие сам, без кнопки
                            b["action"] = {"id": "briefing"}; b["source"] = "text"
                        elif act == "slot":  # кнопка со временем шлёт текст
                            b["text"] = last["buttons"][0]["send"]["text"]; b["source"] = "button"
                        else:
                            btn = next(x for x in last["buttons"] if x["send"].get("action", {}).get("id") == act)
                            b["action"] = btn["send"]["action"]; b["text"] = btn["label"]; b["source"] = "button"
                    r = (await c.post("/api/chat", json=b, headers=h)).json(); last = r
                    ok = r["kind"] == kind and tpl in used and (text != turns[-1][0] or EXPECT.get(name, lambda r: True)(r))
                    print("OK " if ok else "BAD", name, r["kind"], used, r["text"], [(x["label"][:30], x.get("style")) for x in r["buttons"]], [x["marks"] for x in r["records"]][:2])
asyncio.run(main())
