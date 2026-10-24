"""Headless Edge/CDP: регистрация, диалог, контрактный импорт и отмена.

Нужны отдельный стенд http://127.0.0.1:18081 и Edge с CDP на 127.0.0.1:19222.
Личный профиль браузера не использовать. Артефакты — fix-results/.
"""
import base64
import json
from pathlib import Path
import time
import urllib.request
import uuid

import websocket

OUT = Path("fix-results")
OUT.mkdir(exist_ok=True)
targets = json.load(urllib.request.urlopen("http://127.0.0.1:19222/json/list"))
target = next(t for t in targets if t["type"] == "page")
ws = websocket.create_connection(target["webSocketDebuggerUrl"], origin="http://127.0.0.1:19222", timeout=15)
seq = 0
requests = []
exceptions = []


def command(method, **params):
    global seq
    seq += 1
    current = seq
    ws.send(json.dumps({"id": current, "method": method, "params": params}))
    while True:
        message = json.loads(ws.recv())
        if message.get("method") == "Network.requestWillBeSent":
            r = message["params"]["request"]
            if "/api/" in r["url"]:
                requests.append({"url": r["url"], "method": r["method"]})
        if message.get("method") == "Runtime.exceptionThrown":
            exceptions.append(message["params"]["exceptionDetails"].get("text"))
        if message.get("id") == current:
            if "error" in message:
                raise RuntimeError(message["error"])
            return message.get("result", {})


def evaluate(expression):
    result = command("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    if "exceptionDetails" in result:
        raise RuntimeError(result["exceptionDetails"])
    return result.get("result", {}).get("value")


def wait(expression, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if evaluate(expression):
            return
        time.sleep(0.1)
    raise RuntimeError("Browser condition timed out: " + expression)


def click_text(text, within="document"):
    evaluate(f"Array.from({within}.querySelectorAll('button')).find(b=>b.textContent.trim()==={json.dumps(text,ensure_ascii=False)}&&!b.disabled).click()")


def set_value(selector, text, kind="HTMLInputElement"):
    evaluate(f"(()=>{{const el=document.querySelector({json.dumps(selector)});Object.getOwnPropertyDescriptor({kind}.prototype,'value').set.call(el,{json.dumps(text,ensure_ascii=False)});el.dispatchEvent(new Event('input',{{bubbles:true}}));}})()")


def say(text):
    before = evaluate("document.querySelectorAll('.answer__text').length")
    set_value(".composer__field textarea", text, "HTMLTextAreaElement")
    evaluate("document.querySelector('button[aria-label=\"Отправить\"]').click()")
    wait(f"document.querySelectorAll('.answer__text').length>{before}")


try:
    command("Page.enable")
    command("Runtime.enable")
    command("Network.enable")
    command("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
    command("Page.navigate", url="http://127.0.0.1:18081")
    wait("!!document.querySelector('.auth__card')")
    click_text("Регистрация")
    set_value('input[autocomplete="username"]', "browser" + uuid.uuid4().hex[:10])
    set_value('input[autocomplete="new-password"]', "browser-audit-password")
    click_text("Создать аккаунт")
    wait("!!document.querySelector('.composer__field textarea')")
    say("Поставь встречу с дизайнером завтра")
    say("в 15")
    say("перенеси её на послезавтра в 16")
    click_text("Импорт и выгрузка") if evaluate("!!document.querySelector('.menu__list')") else None
    if not evaluate("!!document.querySelector('.transfer')"):
        evaluate("document.querySelector('.avatar').click()")
        click_text("Импорт и выгрузка")
    wait("!!document.querySelector('.transfer')")
    click_text("Выгрузить", "document.querySelector('.transfer')")
    wait("document.querySelector('.transfer__field').value.includes('records')")
    original = json.loads(evaluate("document.querySelector('.transfer__field').value"))
    assert len(original["records"]) == 1
    assert original["records"][0]["time"] == "16:00"
    edited = json.loads(json.dumps(original))
    edited["records"][0]["text"] = "Встреча после импорта"
    edited["records"].append({"type": "task", "text": "Задача из браузера", "date": None, "time": None, "date_kind": "none"})
    set_value(".transfer__field", json.dumps(edited, ensure_ascii=False), "HTMLTextAreaElement")
    click_text("Проверить", "document.querySelector('.transfer')")
    wait("!!document.querySelector('.transfer__sum')")
    assert "Добавлю 1, изменю 1, удалю 0." in evaluate("document.querySelector('.transfer__sum').textContent")
    click_text("Применить", "document.querySelector('.transfer')")
    wait("!document.querySelector('.transfer') && document.body.textContent.includes('Готово: добавил 1, изменил 1, удалил 0.')")
    click_text("Вернуть")
    wait("document.body.textContent.includes('Вернул всё как было до импорта.')")
    evaluate("document.querySelector('.avatar').click()")
    click_text("Импорт и выгрузка")
    click_text("Выгрузить", "document.querySelector('.transfer')")
    wait("document.querySelector('.transfer__field').value.includes('records')")
    restored = json.loads(evaluate("document.querySelector('.transfer__field').value"))
    assert restored["records"] == original["records"]
    # Ошибка в пакете должна отключить применение, а не обещать пропуск плохой строки.
    invalid = {"records": [{**original["records"][0], "time": None}]}
    set_value(".transfer__field", json.dumps(invalid, ensure_ascii=False), "HTMLTextAreaElement")
    click_text("Проверить", "document.querySelector('.transfer')")
    wait("!!document.querySelector('.transfer__item--error')")
    assert evaluate("Array.from(document.querySelector('.transfer').querySelectorAll('button')).find(b=>b.textContent.trim()==='Применить').disabled")
    # Порог удаления >10: показываем подтверждение; «Остаться» ничего не меняет.
    many = json.loads(json.dumps(original))
    many["records"] += [{"type": "note", "text": "Browser bulk " + str(i)} for i in range(11)]
    set_value(".transfer__field", json.dumps(many, ensure_ascii=False), "HTMLTextAreaElement")
    click_text("Проверить", "document.querySelector('.transfer')")
    wait("!!document.querySelector('.transfer__sum') && document.querySelector('.transfer__sum').textContent.includes('Добавлю 11')")
    click_text("Применить", "document.querySelector('.transfer')")
    wait("!document.querySelector('.transfer')")
    evaluate("document.querySelector('.avatar').click()")
    click_text("Импорт и выгрузка")
    click_text("Выгрузить", "document.querySelector('.transfer')")
    wait("document.querySelector('.transfer__field').value.includes('records')")
    assert len(json.loads(evaluate("document.querySelector('.transfer__field').value"))["records"]) == 12
    set_value(".transfer__field", json.dumps(original, ensure_ascii=False), "HTMLTextAreaElement")
    click_text("Проверить", "document.querySelector('.transfer')")
    wait("!!document.querySelector('.transfer__sum') && document.querySelector('.transfer__sum').textContent.includes('удалю 11')")
    click_text("Применить", "document.querySelector('.transfer')")
    wait("!!document.querySelector('.modal')")
    assert "Удалить 11 записей?" in evaluate("document.querySelector('.modal').textContent")
    click_text("Остаться", "document.querySelector('.modal')")
    click_text("Выгрузить", "document.querySelector('.transfer')")
    wait("document.querySelector('.transfer__field').value.includes('Browser bulk')")
    assert len(json.loads(evaluate("document.querySelector('.transfer__field').value"))["records"]) == 12
    evaluate("document.querySelector('.transfer button[aria-label=\"Закрыть\"]').click()")
    click_text("Вернуть")
    wait("Array.from(document.querySelectorAll('.answer__text')).filter(e=>e.textContent.includes('Вернул всё как было до импорта.')).length===2")
    for name, width, height, mobile in (("desktop", 1280, 900, False), ("mobile", 390, 844, True)):
        command("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=mobile)
        time.sleep(0.4)
        data = command("Page.captureScreenshot", format="png")["data"]
        (OUT / (name + ".png")).write_bytes(base64.b64decode(data))
    assert not exceptions, exceptions
    result = {"passed": True, "scenario": "register -> clarify -> create -> move -> export -> preview -> apply -> undo",
              "browser_exceptions": exceptions, "requests": requests, "original_restored": True,
              "invalid_preview_blocks_apply": True, "bulk_delete_confirmation_cancelled": True,
              "viewports": ["1280x900", "390x844"]}
    (OUT / "browser-flow.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Browser flow passed; original data restored; desktop/mobile screenshots saved.")
except Exception as error:
    (OUT / "browser-failure.json").write_text(json.dumps({"error": str(error), "requests": requests, "exceptions": exceptions}, ensure_ascii=False, indent=2), encoding="utf-8")
    raise
finally:
    try:
        command("Browser.close")
    except Exception:
        pass
    ws.close()
