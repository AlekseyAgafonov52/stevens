# Голосовой ассистент «Стивенс»

Stevens помогает вести задачи, встречи и напоминания через текст и голос.

## Запуск

Нужен Docker Desktop с Linux-контейнерами. В корне репозитория выполните:

```sh
docker compose up --build -d
```

Откройте http://localhost:8081 — порт 8080 показывает тот же сайт. Документация API: http://localhost:8000/docs. Для регистрации используются логин 3–32 символа и пароль 5–128 символов.

Ключи Yandex необязательны для запуска и разбора фраз правилами. Для распознавания аудио и резервного разбора через LLM скопируйте `.env.example` в `.env` и заполните параметры провайдера. Ключи остаются на сервере.

## Состав проекта

- `app/` — FastAPI, обработка диалогов, логика записей, хранение и голос.
- `app/ai/` — контрактная схема ИИ, транспорт Yandex и адаптер к логике диалогов.
- `app/ai/understanding.py` — единая точка разбора правил/LLM по v1.6; `app/ai/search.py` — поиск без доступа к базе.
- `brain.py` — точка входа резервного разбора для непонятных фраз и явно неполных результатов правил.
- `frontend-contract/` — активный React/TypeScript-фронтенд, используемый в Docker Compose.
- `tests/`, `tools/` — серверные регрессии и проверки браузера/аудио.

Подробные команды: [ЗАПУСК.md](ЗАПУСК.md). Результаты общей проверки и ограничения: [СТАБИЛЬНАЯ_ВЕРСИЯ.md](СТАБИЛЬНАЯ_ВЕРСИЯ.md). Предыдущие исправления: [ИСПРАВЛЕНИЯ_НАДЕЖНОСТИ_И_БЕЗОПАСНОСТИ.md](ИСПРАВЛЕНИЯ_НАДЕЖНОСТИ_И_БЕЗОПАСНОСТИ.md).

## Проверки

Переработка резервного ИИ-разбора и её границы описаны в [ПЕРЕРАБОТКА_BRAIN.md](ПЕРЕРАБОТКА_BRAIN.md). Проверка без провайдера: `python tests/test_ai_parser.py`. Реальные вызовы Yandex запускаются только явно: `python test_brain.py --live`.

Для локальных Python-проверок нужен Python 3.13:

```sh
python -m pip install -r requirements-dev.txt
npx --yes pyright@1.1.414
python tests/test_chat_safety.py
python tests/test_project_safety.py
```

Полный серверный прогон требует отдельной тестовой PostgreSQL; команды приведены в `ЗАПУСК.md`. В каждом фронтенде выполняются `pnpm run lint`, `pnpm run typecheck`, `pnpm test`, `pnpm run build`. Эти проверки также встроены в его Dockerfile.

Репозиторий: [AlekseyAgafonov52/stevens](https://github.com/AlekseyAgafonov52/stevens).

## Контракт v1.6 и резервные копии

Текущее соответствие, исправления и непроверенные условия сдачи: [аудит v1.6](АУДИТ_КОНТРАКТА_v1.6_2026-10-26.md).
`POST /api/chat` требует UUID диалога, `text`, `source`, `client_time` с часовым поясом и `timezone`.
Защищённые адреса требуют `Authorization: Bearer ...` или `X-Client-Id`. Старый заголовок дополнений необязателен.

Docker Compose запускает сервис `backup`: первая копия сразу после запуска базы, затем каждые 24 часа.
Копии PostgreSQL в формате `pg_dump --format=custom` хранятся в отдельном volume `voice_assistant_backups`.
Незавершённые копии имеют суффикс `.tmp` и не считаются готовыми. Приложение и его база при копировании работают.
Копии остаются на том же сервере: для защиты от потери сервера их нужно сохранять также во внешнем хранилище.

Проверка и копирование готовой копии на компьютер:

```sh
docker compose exec backup sh -c 'ls -lh /backups/*.dump'
docker compose cp backup:/backups/stevens-YYYYMMDDTHHMMSSZ.dump ./stevens-backup.dump
docker compose exec backup pg_restore --list /backups/stevens-YYYYMMDDTHHMMSSZ.dump
```

Восстановление сначала проверяют в отдельной пустой PostgreSQL, не в рабочей базе:
`pg_restore --exit-on-error --no-owner --dbname=<отдельная_база> stevens-backup.dump`.
Для контрактных тестов используйте только отдельную тестовую базу:

```powershell
$env:AUDIT_DATABASE_URL = 'postgresql+asyncpg://postgres:<пароль>@127.0.0.1:<тестовый_порт>/<тестовая_база>'
$env:AUDIT_OUT_DIR = 'audit-results/v16-final'
python audit_run_tests.py
```
