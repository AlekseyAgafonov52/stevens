"""Run inside Docker: docker compose exec backend python -m tools.diagnose_llm

No calendar writes. Expected labels are for manual inspection, not a certification.
"""
import asyncio
from datetime import datetime

from app.ai.schema import Input
from app.ai.quality import validate_input
from app.ai.understanding import understand

PHRASES = [
    ("Напомни завтра в 10 позвонить Ивану", "create"),
    ("Напомни мне завтра вечером проверить отчёт", "create"),
    ("Создай задачу на завтра: проверить отчёт", "create"),
    ("Поставь хоккей на пятницу в 18:00", "create"),
    ("Что у меня запланировано на завтра?", "list"),
    ("У меня завтра много дел?", "list"),
    ("Сколько у меня завтра встреч?", "list"),
    ("Расскажи, какой у меня будет день в пятницу", "list"),
    ("А какие планы на выходные?", "list"),
    ("Посоветуй интересный фильм", "off_topic"),
]


def printable(value: str) -> str:
    # ASCII only: safe output on PowerShell's legacy console encodings.
    return value.encode("unicode_escape").decode("ascii")


async def main():
    print("YandexGPT-only UTF-8 diagnostic; no calendar writes; each line calls API")
    passed = 0
    now = datetime.now().astimezone()
    for phrase, expected in PHRASES:
        try:
            request = Input(text=phrase, now=now)
            validate_input(request)  # кириллица, испорченная в PowerShell, — проверяем только здесь
            result = await understand(request, force_llm=True)
            ok = result.intent == expected
            passed += ok
            print(("PASS" if ok else "FAIL"), printable(phrase),
                  result.model_dump_json(exclude_none=True))
        except Exception as error:
            print("ERROR", printable(phrase), type(error).__name__, str(error))
    print(f"Intent pass: {passed}/{len(PHRASES)}. Check titles, dates, times separately.")


if __name__ == "__main__":
    asyncio.run(main())
