"""Show when Stevens uses deterministic NLU vs needs YandexGPT.

Offline; no model calls, database, API key, or network traffic.

Usage:
  python tools/diagnose_complex_routes.py
  python tools/diagnose_complex_routes.py --now 2026-10-21T10:00 "Поставь два занятия на завтра: английский утром и программирование в 18"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.decomposition import requested_count, suspected_multiple
from app.ai.rules import parse as parse_rules
from app.ai.schema import Input

DEFAULT = [
    "Завтра математика в два, а физика в пять",
    "Поставь два занятия на завтра: английский утром и программирование в 18",
    "Запиши в пятницу встречу с Иваном в 12, с Олегом в 15 и созвон с Марией в 19",
    "В понедельник надо оплатить квартиру, забрать посылку в 16 и напомнить про тренировку в 20",
    "Составь встречу завтра с репетитором по математике в 14 и по физике в 17",
    "Поставь три занятия на завтра: английский в 12 и программирование в 18",
    "Встреча с Иваном и Марией завтра в 14",
]


def diagnostics(phrase: str, now: datetime) -> dict:
    parsed = parse_rules(Input(text=phrase, now=now))
    route = "yandexgpt" if parsed.intent == "unknown" or parsed.confidence < 0.8 else "rules"
    return {
        "text": phrase,
        "route_if_enabled": route,
        "confidence": parsed.confidence,
        "suspected_multiple": suspected_multiple(phrase),
        "requested_count": requested_count(phrase),
        "intent": parsed.intent,
        "items": [item.model_dump(exclude_none=True) for item in parsed.items],
        "note": "If YandexGPT is disabled or unavailable, rules are used; an unsafe merged create remains unknown."
                if route == "yandexgpt" else "High-confidence deterministic decomposition; no provider call.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phrases", nargs="*", help="Utterances; defaults to seven examples")
    parser.add_argument("--now", default="2026-10-21T10:00", help="Reference local time for date parsing")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now)
    for phrase in args.phrases or DEFAULT:
        print(json.dumps(diagnostics(phrase, now), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
