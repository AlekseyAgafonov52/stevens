#!/usr/bin/env bash
# Ждём, пока поднимется Docker внутри Codespace, и запускаем проект в фоне.
# Лог сборки: .devcontainer/start.log
cd "$(dirname "$0")/.."
for i in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
nohup docker compose up --build -d > .devcontainer/start.log 2>&1 &
echo "Stevens собирается (3–5 минут). Лог: .devcontainer/start.log. Потом откройте порт 8080 во вкладке Ports."
