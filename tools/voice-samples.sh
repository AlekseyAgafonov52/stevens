#!/usr/bin/env bash
# Образцы голосов Silero (Айдар, Евгений и три женских) на фразах Stevens → папка voice-samples/.
# Запуск из корня репозитория: bash tools/voice-samples.sh   (нужен только Docker; первый раз ~3–5 минут)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p voice-samples
docker run --rm -v "$PWD/tools:/tools:ro" -v "$PWD/voice-samples:/out" python:3.11-slim bash -c "
  pip install -q --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu &&
  pip install -q --no-cache-dir numpy &&
  python /tools/silero_samples.py"
echo
echo "Готово. Файлы в папке voice-samples/ — слева в проводнике, правый клик по файлу → Download."
