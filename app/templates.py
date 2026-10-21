"""Шаблоны ответов — разделы 9 и 15.6 контракта v1.4, слово в слово.

Для ответа выбирается ID, затем случайный вариант (подряд один и тот же
не повторяем). Переменные: {text} {date} {time} {when} {period} {type}
{types_gen} {count:ф1|ф2|ф3}; с заглавной буквы — {Period}, {Type}, {When}.
"""
from __future__ import annotations

import random
import re

from app.textfmt import capitalize, plural

# ID → (варианты text, озвучка или None)
TEMPLATES: dict[str, tuple[list[str], str | None]] = {
    "created_task": ([
        "Записал задачу на {when}: «{text}».",
        "Готово: «{text}» — {when}.",
        "Задача «{text}» стоит на {when}.",
    ], "Записал на {when}."),
    "created_task_deadline": ([
        "Записал: «{text}», срок — до {date}.",
        "Готово: «{text}» — до {date}.",
        "Срок — до {date}. Задачу «{text}» записал.",
    ], "Записал, срок — до {date}."),
    "created_task_nodate": ([
        "Записал задачу без срока: «{text}».",
        "Готово: «{text}», без срока.",
        "Задачу «{text}» сохранил, без срока.",
    ], "Записал, без срока."),
    "created_reminder": ([
        "Записал напоминание на {when}: «{text}».",
        "Записал: {when} — «{text}».",
        "Напоминание на {when} сохранил: «{text}».",
    ], "Напоминание — {when}."),
    "created_meeting": ([
        "Встреча записана: «{text}», {when}.",
        "Готово: {when} — «{text}».",
        "Добавил встречу «{text}» на {when}.",
    ], "Встреча — {when}."),
    "list_some": ([
        "{Period} — {count:дело|дела|дел}:",
        "{Period} запланировано {count:дело|дела|дел}:",
        "Вот ваши планы {period}: {count:дело|дела|дел}.",
    ], "{Period} — {count:дело|дела|дел}."),
    "list_type_yes": ([
        "Да, {count:<forms>}:",
        "Есть, {count:<forms>}:",
        "Да, у вас {count:<forms>}:",
    ], "Да, {count:<forms>}."),
    "list_empty_nearest": ([
        "{Period} планов нет. Ближайшее — {when}: «{text}».",
        "{Period} ничего не запланировано. Следующее — «{text}», {when}.",
        "{Period} свободно. Ближайшее дело — {when}: «{text}».",
    ], "{Period} планов нет. Ближайшее — {when}."),
    "list_empty_none": ([
        "{Period} планов нет, и дальше пока пусто.",
        "{Period} пусто, ближайших планов тоже нет.",
        "Расписание свободно. Скажите, что записать.",
    ], None),
    "list_type_empty": ([
        "{Period} {types_gen} нет. Ближайшее — {when}: «{text}».",
        "{Period} {types_gen} не запланировано. Следующее — «{text}», {when}.",
        "{Period} у вас нет {types_gen}. Ближайшее — {when}: «{text}».",
    ], "{Period} {types_gen} нет."),
    # Без nearest вторая фраза list_type_empty не нужна (раздел 9)
    "list_type_empty_alone": ([
        "{Period} {types_gen} нет.",
        "{Period} {types_gen} не запланировано.",
        "{Period} у вас нет {types_gen}.",
    ], "{Period} {types_gen} нет."),
    "found_some": ([
        "Нашёл {count:запись|записи|записей}:",
        "Вот что нашлось — {count:запись|записи|записей}:",
        "Нашлось {count:совпадение|совпадения|совпадений}:",
    ], "Нашёл {count:запись|записи|записей}."),
    "found_one": ([
        "Нашёл одну запись:",
        "Есть одна: «{text}», {when}.",
        "Нашлась одна запись: «{text}».",
    ], "Нашёл одну запись."),
    "found_none": ([
        "Ничего не нашёл. Попробуйте другое слово или дату.",
        "Боюсь, ничего нет. Уточните название или период.",
        "Совпадений нет. Попробуйте искать иначе.",
    ], None),
    "found_when_last": ([
        "В последний раз — {when}: «{text}».",
        "Последний раз — {when}.",
        "Последняя запись — {when}: «{text}».",
    ], "В последний раз — {when}."),
    "found_when_next": ([
        "Ближайший раз — {when}: «{text}».",
        "В следующий раз — {when}.",
        "Ближайшая запись — {when}: «{text}».",
    ], "В следующий раз — {when}."),
    "clarify_meeting_time": ([
        "Во сколько встреча?",
        "Позвольте уточнить: в какое время?",
        "Укажите, пожалуйста, время встречи.",
    ], None),
    "clarify_reminder_time": ([
        "Во сколько напомнить?",
        "В какое время напомнить?",
        "Укажите время напоминания.",
    ], None),
    "clarify_reminder_when": ([
        "Когда напомнить: день и время?",
        "Позвольте уточнить: когда напомнить?",
        "Назовите день и время напоминания.",
    ], None),
    "clarify_day": ([
        "На какой день?",
        "Какого числа?",
        "Уточните, пожалуйста, день.",
    ], None),
    "clarify_meeting_person": ([
        "С кем встреча?",
        "С кем или о чём будет встреча?",
        "Уточните, пожалуйста: с кем встреча?",
    ], None),
    "clarify_date_past": ([
        "Это уже в прошлом. На когда записать?",
        "{When} уже позади. На когда записать?",
        "Боюсь, это время уже прошло. Выберите другое.",
    ], None),
    "clarify_generic": ([
        "Не хватает деталей: что и на когда?",
        "Позвольте уточнить: что именно и когда?",
        "Чуть больше подробностей — и запишу.",
    ], None),
    "confirm": ([
        "Правильно понимаю: {type} «{text}», {when}?",
        "{Type} «{text}», {when} — верно?",
        "Проверим: {type} «{text}», {when}. Всё так?",
    ], "{Type}, {when} — верно?"),
    "confirm_no": ([
        "Хорошо. Что поправить?",
        "Понял. Что изменить: дату, время или текст?",
        "Давайте исправим. Что не так?",
    ], None),
    "conflict_one": ([
        "На {time} уже есть встреча: «{text}». Что сделать?",
        "Это время занято: «{text}». Как поступим?",
    ], "Это время занято. Что сделать?"),
    "conflict_many": ([
        "На {time} уже {count:встреча|встречи|встреч}. Что сделать?",
        "Это время занято: {count:встреча|встречи|встреч}. Как поступим?",
        "{When} уже {count:встреча|встречи|встреч}. Что выберете?",
    ], "Это время занято. Что сделать?"),
    "conflict_new_time": ([
        "На какое время поставить новую встречу?",
        "Во сколько будет новая встреча?",
        "Назовите время для новой встречи.",
    ], None),
    "conflict_move_existing": ([
        "На какое время перенести «{text}»?",
        "Во сколько теперь «{text}»?",
        "Назовите новое время для «{text}».",
    ], None),
    "conflict_keep_both": ([
        "Сохранил обе встречи.",
        "Готово: обе встречи в календаре.",
        "Оставил обе — в одно время.",
    ], None),
    "cancelled": ([
        "Отменил.",
        "Хорошо, ничего не сохраняю.",
        "Отменено.",
    ], None),
    "not_understood": ([
        "Боюсь, не понял. Можно, например, так:",
        "Не уловил. Попробуйте так:",
        "Не понял запрос. Вот примеры:",
    ], None),
    "off_topic": ([
        "Это не по моей части. Я веду задачи, встречи и напоминания.",
        "С этим не помогу, зато слежу за вашим расписанием.",
        "Здесь я не советчик. А вот ваше время — моя забота.",
    ], "Это не по моей части."),
    "help": ([
        "Я Stevens. Записываю задачи, встречи и напоминания, нахожу их и подсказываю, что впереди.",
        "Я Stevens, слежу за вашим временем. Скажите, например: «Напомни завтра в 10 позвонить Ивану».",
        "Stevens, к вашим услугам. Запишу, найду и расскажу о планах — говорите или пишите.",
    ], "Я Стивенс: задачи, встречи, напоминания."),
    "thanks": ([
        "Рад помочь.",
        "Пожалуйста.",
        "К вашим услугам.",
    ], None),
    "error_backend": ([
        "Извините, у меня сбой. Попробуйте ещё раз.",
        "Прошу прощения, на моей стороне что-то пошло не так. Повторите, пожалуйста.",
        "Извините, не получилось. Попробуйте через минуту.",
    ], "Извините, сбой. Повторите, пожалуйста."),
    # ── Допы, 15.6 ──
    "completed": ([
        "Отметил как выполненное: «{text}».",
        "Готово: «{text}» — сделано.",
        "Записал, что «{text}» сделано.",
    ], "Отметил."),
    "completed_meeting_no": ([
        "Встречи не отмечаются выполненными. Если она больше не нужна — её можно удалить.",
        "Встречу отметить нельзя. Удалить её?",
        "Отмечаются только задачи и напоминания. Встречу можно удалить.",
    ], None),
    "deleted": ([
        "Удалил: «{text}», {when}.",
        "Готово, убрал из планов: «{text}».",
        "Удалил «{text}». Если зря — верну.",
    ], "Удалил."),
    "undo_done": ([
        "Отменил: «{text}» не сохранил.",
        "Хорошо, «{text}» убрал.",
        "Отменено.",
    ], None),
    "restored": ([
        "Вернул: «{text}», {when}.",
        "Готово, «{text}» снова в планах.",
        "Восстановил: «{text}».",
    ], "Вернул."),
    "which_one": ([
        "Какую именно?",
        "Нашёл несколько. Какую из них?",
        "Уточните, о какой записи речь.",
    ], None),
}

COUNT_RE = re.compile(r"\{count:([^}]+)\}")
VAR_RE = re.compile(r"\{(\w+)\}")


def _fill(template: str, values: dict, count_forms: tuple[str, str, str] | None) -> str:
    def count(match: re.Match) -> str:
        spec = match.group(1)
        # <forms> или «дело|дела|дел» в list_some — подставляются формы типа
        forms = count_forms if count_forms and spec in ("<forms>", "дело|дела|дел") else tuple(spec.split("|"))
        return plural(int(values.get("count", 0)), *forms)

    def var(match: re.Match) -> str:
        name = match.group(1)
        value = values.get(name.lower())
        if value is None:
            return match.group(0)
        return capitalize(str(value)) if name[0].isupper() else str(value)

    return VAR_RE.sub(var, COUNT_RE.sub(count, template))


def render(
    template_id: str,
    values: dict | None = None,
    speech_values: dict | None = None,
    count_forms: tuple[str, str, str] | None = None,
    last: dict[str, int] | None = None,
) -> tuple[str, str | None]:
    """→ (text, speech). last — какие варианты уже были в этом диалоге, чтобы не повторять подряд."""
    variants, speech = TEMPLATES[template_id]
    values = values or {}
    choices = list(range(len(variants)))
    if last is not None and len(choices) > 1 and last.get(template_id) in choices:
        choices.remove(last[template_id])
    index = random.choice(choices)
    if last is not None:
        last[template_id] = index
    text = _fill(variants[index], values, count_forms)
    spoken = _fill(speech, {**values, **(speech_values or {})}, count_forms) if speech else None
    return text, spoken


def get_template(key: str, **kwargs) -> str:
    """Совместимость со старым кодом: только text."""
    return render(key, kwargs)[0]
