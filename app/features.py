"""Что сервер умеет сверх основного: список отдаёт GET /api/health.

`stt` (распознавание речи на сервере) — только когда есть ключ Yandex Cloud.
"""
import os


def stt_ready() -> bool:
    return bool(os.getenv("YANDEX_API_KEY") and os.getenv("YANDEX_FOLDER_ID"))


def enabled() -> list[str]:
    return ["stt"] if stt_ready() else []
