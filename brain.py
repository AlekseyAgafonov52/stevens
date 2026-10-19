import os
import json
from typing import Literal, Optional, List
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import openai

load_dotenv()

YANDEX_FOLDER = os.getenv("YANDEX_FOLDER_ID")
YANDEX_KEY = os.getenv("YANDEX_API_KEY")

assert YANDEX_FOLDER is not None
assert YANDEX_KEY is not None

# Для парсинга лучше yandexgpt-lite (быстрее, дешевле, точнее следует инструкциям)
MODEL = "yandexgpt-lite" 

client = openai.OpenAI(
    api_key=YANDEX_KEY,
    base_url="https://ai.api.cloud.yandex.net/v1",
    project=YANDEX_FOLDER,
)

class IntentSchema(BaseModel):
    # В файле написано "intent": "create | list | search...", 
    # но "create" делится на task/meeting/reminder, поэтому используем эти значения
    intent: Literal["create_task", "create_meeting", "create_reminder", "list", "search", "help", "thanks", "off_topic", "unknown"] = Field(description="Намерение")
    
    # Поля для создания
    text: Optional[str] = Field(default=None, description="Текст задачи без дат и времени")
    date: Optional[str] = Field(default=None, description="Относительный токен (today, tomorrow, friday, next_week, end_of_week) или ISO-дата")
    date_kind: Literal["exact", "deadline", "none"] = Field(default="exact", description="Тип срока")
    time: Optional[str] = Field(default=None, description="Время HH:MM")
    time_ambiguous: Optional[bool] = Field(default=False, description="True, если непонятно утро/вечер (например, 'в 7')")
    
    # Для списков
    period: Optional[str] = Field(default=None, description="Период для list (today, this_week и т.д.)")
    filter_type: Optional[str] = Field(default=None, description="Тип записи для фильтрации (task, meeting, reminder)")
    
    # Для поиска
    keyword: Optional[str] = Field(default=None, description="Ключевое слово для поиска (например, 'договор')")
    people: Optional[List[str]] = Field(default=None, description="Имена людей в именительном падеже")
    organizations: Optional[List[str]] = Field(default=None, description="Названия компаний")
    tense: Optional[Literal["past", "future"]] = Field(default=None, description="Время поиска (прошлое/будущее)")
    ask: Optional[Literal["when", "exists"]] = Field(default=None, description="Что спрашивают (когда / есть ли)")
    
    # Служебное
    missing: List[str] = Field(default_factory=list, description="Список недостающих полей: 'time', 'date', 'person_or_topic'")
    confidence: Literal["high", "low"] = Field(default="high", description="Уверенность в разборе")


def parse_user_input(text: str) -> Optional[IntentSchema]:
    tools = [{
        "type": "function",
        "name": "extract_intent",
        "description": "Извлекает намерение и параметры из запроса пользователя",
        "parameters": IntentSchema.model_json_schema(),
    }]

    system_prompt = """Ты — ассистент Стивенс. Разбери запрос пользователя.
1. Если это создание задачи/встречи/напоминания, извлеки text, date, time.
2. Если просят показать планы — intent: list, укажи period.
3. Если просят найти что-то — intent: search, укажи keyword или people.
4. Если не хватает данных для действия (например, встреча без времени), добавь поле в missing.
5. Людей и компании ставь в именительный падеж (Иван, а не Иваном).
Не придумывай данные, которых нет в тексте."""

    try:
        response = client.responses.create(
            model=f"gpt://{YANDEX_FOLDER}/{MODEL}",
            temperature=0.1,
            instructions=system_prompt,
            input=text,
            tools=tools,  # type: ignore
            store=False, 
        )

        # Ищем вызов функции в output
        for item in response.output:
            # Проверяем тип элемента, чтобы Pylance не ругался
            if getattr(item, "type", None) == "function_call" and getattr(item, "name", None) == "extract_intent":
                args = json.loads(getattr(item, "arguments"))
                return IntentSchema(**args)

        # Если функция не вызвана — пробуем вытащить текст
        if response.output_text:
            print(f"⚠️ Модель ответила текстом вместо вызова функции: {response.output_text}")
        return None

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