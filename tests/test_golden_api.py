import asyncio, json, os, sys, uuid
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5433/stevens")
import httpx
from app.main import app
from app.routers import chat as chatmod
used = []
orig = chatmod.render
def spy(tid, *a, **k):
    used.append(tid); return orig(tid, *a, **k)
chatmod.render = spy

CLOCK = "2026-10-21T10:00:00+03:00"
async def main():
    d = json.load(open("golden_dataset_v2.json"))
    fails = 0
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            for case in d["cases"]:
                cid = "golden-" + uuid.uuid4().hex[:12]
                h = {"X-Client-Id": cid}
                await c.post("/api/sandbox/reset", headers=h)
                conv = str(uuid.uuid4())
                turns = case.get("turns") or [{"phrase": case["phrase"], "expected_response": case["expected_response"]}]
                for t in turns:
                    used.clear()
                    body = {"conversation_id": conv, "text": t.get("phrase") or t.get("button",""), "source": "text", "client_time": CLOCK, "timezone": "Europe/Moscow"}
                    if t.get("action"): body["action"] = t["action"]; body["source"] = "button"
                    r = (await c.post("/api/chat", json=body, headers=h)).json()
                    exp = t["expected_response"]
                    probs = []
                    if r["kind"] != exp.get("kind"): probs.append(f"kind {r['kind']}!={exp.get('kind')}")
                    if exp.get("template") and exp["template"] not in used: probs.append(f"tpl {used}!={exp['template']}")
                    if "awaiting_reply" in exp and r["awaiting_reply"] != exp["awaiting_reply"]: probs.append("awaiting")
                    rec = exp.get("record")
                    if rec and r["records"]:
                        got = r["records"][0]
                        for k, v in rec.items():
                            if got.get(k) != v: probs.append(f"{k} {got.get(k)!r}!={v!r}")
                    if probs:
                        fails += 1
                        print(f"#{case['id']} «{t['phrase']}» → {r['text']!r}\n    {probs}")
    print("fails:", fails)
asyncio.run(main())
