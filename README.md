▶️ Запуск и проверка БД

# поднять базу в фоне
docker compose up -d

# проверить, что контейнер здоров
docker compose ps

# посмотреть логи, если что-то не так
docker compose logs -f db

▶️ Запуск бэка

# запустить приложение через uvicorn
uvicorn app.main:app --reload

# ручки можно дергать через
http://127.0.0.1:8000/docs