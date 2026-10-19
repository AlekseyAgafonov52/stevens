import os
import json
import re
from typing import Literal, Optional, List
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import openai

load_dotenv()

YANDEX_FOLDER = os.getenv("YANDEX_FOLDER_ID")
YANDEX_KEY = os.getenv("YANDEX_API_KEY")

assert YANDEX_FOLDER is not None
assert YANDEX_KEY is not None

MODEL = "yandexgpt-lite"

client = openai.OpenAI(
    api_key=YANDEX_KEY,
    base_url="https://ai.api.cloud.yandex.net/v1",
    project=YANDEX_FOLDER,
)

class IntentSchema(BaseModel):
    intent: Literal[
        "create_task", "create_meeting", "create_reminder", 
        "list", "search", "help", "thanks", "off_topic", "unknown"
    ] = Field(description="Намерение")
    text: Optional[str] = Field(default=None, description="Суть задачи без дат и командных слов")
    date: Optional[str] = Field(default=None, description="Токен даты (today, tomorrow, monday...) или ISO")
    date_kind: Literal["exact", "deadline", "none"] = Field(default="exact")
    time: Optional[str] = Field(default=None, description="Время HH:MM")
    time_ambiguous: Optional[bool] = Field(default=False)
    period: Optional[str] = Field(default=None)
    filter_type: Optional[str] = Field(default=None)
    keyword: Optional[str] = Field(default=None)
    people: Optional[List[str]] = Field(default=None)
    organizations: Optional[List[str]] = Field(default=None)
    tense: Optional[Literal["past", "future"]] = Field(default=None)
    ask: Optional[Literal["when", "exists"]] = Field(default=None)
    missing: List[str] = Field(default_factory=list)
    confidence: Literal["high", "low"] = Field(default="high")


def clean_text(text: str | None) -> str | None:
    """Убирает командные слова, даты и делает первую букву заглавной."""
    if not text:
        return None
        
    # Убираем командные слова в начале
    text = re.sub(r'^(напомни(?: мне)?|поставь(?: задачу)?|запиши(?: задачу)?|добавь|запланируй|создай)\s+', '', text, flags=re.IGNORECASE)
    # Убираем "про", "о", "об"
    text = re.sub(r'^(про|о|об)\s+', '', text, flags=re.IGNORECASE)
    
    # Убираем даты и время в конце (например, "в среду в 15:00", "завтра в 10")
    text = re.sub(r'\s+(в|на)\s+(понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье|завтра|послезавтра|сегодня).*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+(в|на)\s+\d{1,2}(:\d{2})?.*', '', text, flags=re.IGNORECASE)
    
    text = text.strip().strip('"').strip("'")
    if text:
        text = text[0].upper() + text[1:]

    # Простая нормализация падежей (винительный -> именительный)
    replacements = {
        "Встречу": "Встреча",
        "Планёрку": "Планёрка",
        "Задачу": "Задача",
        "Демо": "Демо"
    }
    for wrong, right in replacements.items():
        if text.startswith(wrong):
            text = right + text[len(wrong):]
            
    return text


def normalize_date(date_val: str | None) -> str | None:
    """Приводит ответ нейросети к стандарту из golden_dataset."""
    if not date_val: return None
    d = date_val.lower()
    mapping = {
        "after_tomorrow": "day_after_tomorrow",
        "the_day_after_tomorrow": "day_after_tomorrow", # <-- Добавили
        "послезавтра": "day_after_tomorrow",
        "afterзавтра": "day_after_tomorrow",
        # ... остальные
    }
    return mapping.get(d, d)


def extract_json_from_text(text: str) -> dict | None:
    """План Б: вытаскиваем JSON из текста, если модель не вызвала функцию."""
    # Ищем блок от { до }
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def parse_user_input(text: str) -> Optional[IntentSchema]:
    tools = [{
        "type": "function",
        "name": "extract_intent",
        "description": "Извлекает намерение и параметры из запроса пользователя",
        "parameters": IntentSchema.model_json_schema(),
    }]

    system_prompt = """Ты — ассистент Стивенс. Твоя задача — разобрать текст в JSON.
ПРАВИЛА:
- Создание: intent = create_task/create_meeting/create_reminder. В поле text пиши ТОЛЬКО суть (например, "Позвонить Ивану"), без дат и без слов "напомни".
- Списки: intent = list. Укажи period (today, tomorrow, this_week, next_week).
- Поиск: intent = search. Укажи keyword или people.
- Погода/анекдоты/прочее: intent = off_topic (не пытайся искать это в базе).
- Даты: используй токены today, tomorrow, day_after_tomorrow, monday...sunday, end_of_week, next_week.
- Если встреча без времени — добавь "time" в missing.
- Имена людей ставь в именительный падеж (Иван, а не Иваном).

ПРИМЕРЫ:
Фраза: "Напомни завтра в 10 подготовить отчёт" -> intent: create_reminder, text: "Подготовить отчёт", date: "tomorrow", time: "10:00"
Фраза: "Что у меня сегодня?" -> intent: list, period: "today"
Фраза: "Какая завтра погода?" -> intent: off_topic
"""

    try:
        response = client.responses.create(
            model=f"gpt://{YANDEX_FOLDER}/{MODEL}",
            temperature=0.1,
            instructions=system_prompt,
            input=text,
            tools=tools,  # type: ignore
            store=False,
        )

        parsed_data = None

        # Попытка 1: Модель вызвала функцию
        for item in response.output:
            if getattr(item, "type", None) == "function_call" and getattr(item, "name", None) == "extract_intent":
                parsed_data = json.loads(getattr(item, "arguments"))
                break
        
        # Попытка 2: Модель написала JSON текстом
        if not parsed_data and response.output_text:
            parsed_data = extract_json_from_text(response.output_text)

        # Если совсем ничего не вышло
        if not parsed_data:
            if response.output_text and "не понял" not in response.output_text.lower():
                print(f"⚠️ Не удалось извлечь JSON из: {response.output_text[:50]}...")
            return None

        # Валидация и постобработка
        intent_obj = IntentSchema(**parsed_data)

        if intent_obj.text:
            intent_obj.text = clean_text(intent_obj.text)
        
        if not intent_obj.text and "create" in intent_obj.intent:
             intent_obj.text = clean_text(text)
        
        if intent_obj.date:
            intent_obj.date = normalize_date(intent_obj.date)
            
        if intent_obj.time and ":" not in intent_obj.time:
            try:
                intent_obj.time = f"{int(intent_obj.time):02d}:00"
            except ValueError:
                pass
        
        return intent_obj

    except Exception as e:
        print(f"❌ Ошибка Yandex API: {e}")
        return None


if __name__ == "__main__":
    print("Тестируем парсер (введите 'exit' для выхода):")
    while True:
        user_input = input("\nВы: ")
        if user_input.lower() == 'exit':
            break
        parsed = parse_user_input(user_input)
        if parsed:
            print(f"✅ {parsed.model_dump_json(indent=2)}")
        else:
            print("❌ Не удалось распарсить")