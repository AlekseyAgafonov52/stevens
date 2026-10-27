"""Lightweight contract checks for five-message context."""
from collections import deque
from datetime import datetime
from app.ai.schema import Input

def test_five_message_window():
    history = deque(maxlen=5)
    for i in range(7):
        history.append({'role': 'user', 'text': f'сообщение {i}'})
    request = Input(text='продолжай', now=datetime(2026, 10, 27), history=list(history))
    assert len(request.history) == 5
    assert request.history[0]['text'] == 'сообщение 2'
    assert request.history[-1]['text'] == 'сообщение 6'
