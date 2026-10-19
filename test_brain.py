import json
from brain import parse_user_input

def run_tests():
    with open("golden_dataset_v2.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    cases = data["cases"]
    passed = 0
    failed = 0

    for case in cases:
        if "phrase" not in case: # Пропускаем диалоги (turns) для простоты
            continue
            
        phrase = case["phrase"]
        expected = case["expected_parse"]
        
        print(f"\nТест {case['id']}: {phrase}")
        result = parse_user_input(phrase)
        
        if not result:
            print("❌ Нейросеть вернула None")
            failed += 1
            continue
            
        # Проверяем ключевые поля
        errors = []
        
        # Умная проверка intent (чтобы create_task == create)
        expected_intent = expected.get("intent", "")
        actual_intent = result.intent
        if expected_intent == "create":
            if not actual_intent.startswith("create_"):
                errors.append(f"intent: ожидалось create, получено {actual_intent}")
        elif expected_intent != actual_intent:
            errors.append(f"intent: ожидалось {expected_intent}, получено {actual_intent}")

        if expected.get("text") and result.text != expected.get("text"):
            errors.append(f"text: ожидалось '{expected.get('text')}', получено '{result.text}'")
            
        if expected.get("date") and result.date != expected.get("date"):
             errors.append(f"date: ожидалось {expected.get('date')}, получено {result.date}")
             
        if expected.get("time") and result.time != expected.get("time"):
             errors.append(f"time: ожидалось {expected.get('time')}, получено {result.time}")

        if errors:
            print(f"❌ ОШИБКА:")
            for err in errors:
                print(f"   - {err}")
            failed += 1
        else:
            print("✅ OK")
            passed += 1

    print(f"\n--- ИТОГИ ---")
    print(f"Пройдено: {passed}")
    print(f"Провалено: {failed}")

if __name__ == "__main__":
    run_tests()