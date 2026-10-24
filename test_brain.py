"""Explicit live-provider check against existing golden record expectations.

python test_brain.py --live
Offline validation belongs to tests/test_ai_parser.py; this command needs real credentials.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path

from brain import Input, Unavailable, parse_user_input


def run_tests() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="allow requests to the configured Yandex provider")
    args = parser.parse_args()
    if not args.live:
        parser.error("Use --live for real provider calls; use python tests/test_ai_parser.py for offline checks")
    data = json.loads(Path(__file__).with_name("golden_dataset_v2.json").read_text(encoding="utf-8"))
    clock = data["meta"]["test_clock"]
    failures = 0
    for case in data["cases"]:
        if "phrase" not in case:
            continue
        expected = case["expected_parse"]
        context = Input(text=case["phrase"], now=datetime.fromisoformat(clock["client_time"]),
                        timezone=clock["timezone"], source="text")
        try:
            result = parse_user_input(case["phrase"], context=context)
        except Unavailable:
            print("Provider unavailable; live checks stopped")
            return 1
        errors = []
        if result.intent != expected["intent"]:
            errors.append("intent")
        record = case["expected_response"].get("record")
        if record and expected["intent"] == "create":
            item = result.items[0] if result.items else None
            if item is None:
                errors.append("items")
            else:
                for field in ("type", "text", "date", "time", "date_kind"):
                    if field in record and getattr(item, field) != record[field]:
                        errors.append(field)
        failures += bool(errors)
        print(case["id"], "FAIL " + ",".join(errors) if errors else "OK")
    print("fails:", failures)
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if run_tests() else 0)
