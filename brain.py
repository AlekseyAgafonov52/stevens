"""Compatibility entry point for the validated v1.6 Yandex parser.

Transport, schema and conversion live in app.ai. This module never saves records.
"""
from datetime import datetime

from app.ai.provider import InvalidResponse, Unavailable, client, parse
from app.ai.schema import Input, Result

__all__ = ["parse_user_input", "Input", "Result", "InvalidResponse", "Unavailable", "client"]


def parse_user_input(text: str, *, context: Input | None = None) -> Result:
    request = context or Input(text=text, now=datetime.now().astimezone())
    if request.text != text:
        raise ValueError("Text does not match parsing context")
    return parse(request)
