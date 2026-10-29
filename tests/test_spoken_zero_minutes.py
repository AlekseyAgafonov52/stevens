"""Spoken leading-zero minutes must be part of the clock, not the title."""
from datetime import datetime
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost/unused")

from app import nlu
from app.routers import chat

NOW = datetime(2026, 10, 29, 10)


class SpokenZeroMinutesTests(unittest.TestCase):
    def test_general_word_clocks_and_mixed_digits(self):
        cases = [("девять пятнадцать", "09:15"), ("двадцать один тридцать", "21:30"),
                 ("двадцать три пятьдесят девять", "23:59"), ("девять тридцать пять", "09:35"),
                 ("девять часов три минуты", "09:03"), ("9 часов 3 минуты", "09:03"),
                 ("девять 15", "09:15"), ("21 тридцать", "21:30"),
                 ("двадцать один ноль три", "21:03"), ("девять часов", "09:00"),
                 ("семь тридцать утра", "07:30"), ("семь тридцать вечера", "19:30"),
                 ("ноль ноль", "00:00"), ("девять часов одна минута", "09:01"),
                 ("девять часов две минуты", "09:02")]
        for clock, expected in cases:
            with self.subTest(clock=clock):
                parsed = nlu.parse(f"напомни завтра в {clock} съесть кашу", NOW)
                self.assertEqual((parsed.time, parsed.text), (expected, "Съесть кашу"))

    def test_word_clock_can_be_a_short_clarification_reply(self):
        draft = {"type": "reminder", "text": "Съесть кашу", "date": "2026-10-30", "time": None, "date_kind": "exact"}
        merged = chat.merge_reply(chat.Pending("draft", draft), "девять пятнадцать", NOW)
        assert merged is not None
        self.assertEqual((merged["time"], merged["text"]), ("09:15", "Съесть кашу"))

    def test_quantity_words_are_preserved_in_titles(self):
        for title in ["купить двадцать яблок", "прочитать тридцать пять страниц", "девять книг купить"]:
            with self.subTest(title=title):
                parsed = nlu.parse(f"напомни завтра в 09:03 {title}", NOW)
                self.assertEqual(parsed.time, "09:03")
                self.assertEqual((parsed.text or "").lower(), title)

    def test_reminder_consumes_all_spoken_clock_words(self):
        for clock, expected in [("9 ноль три", "09:03"), ("девять ноль три", "09:03"),
                                ("09 ноль 3", "09:03"), ("9 нуль пять", "09:05"),
                                ("9 ноль ноль", "09:00"), ("9 часов ноль три минуты", "09:03"),
                                ("9 ноль три вечера", "21:03")]:
            with self.subTest(clock=clock):
                result = nlu.parse(f"поставь напоминание на завтра в {clock} съесть кашу", NOW)
                self.assertEqual(result.intent, "create")
                self.assertEqual(result.type, "reminder")
                self.assertEqual(result.time, expected)
                self.assertEqual(result.text, "Съесть кашу")
                self.assertEqual(result.date.isoformat() if result.date else None, "2026-10-30")

    def test_clarification_and_move_use_the_same_clock(self):
        draft = {"type": "reminder", "text": "Съесть кашу", "date": "2026-10-30", "time": None, "date_kind": "exact"}
        merged = chat.merge_reply(chat.Pending("draft", draft), "в 9 ноль три", NOW)
        assert merged is not None
        self.assertEqual(merged["time"], "09:03")
        self.assertEqual(merged["text"], "Съесть кашу")
        moved = nlu.parse("перенеси её на завтра в 9 ноль три", NOW)
        self.assertEqual((moved.intent, moved.time, moved.keywords), ("move", "09:03", []))

    def test_zero_in_content_is_not_taken_as_minutes(self):
        result = nlu.parse("напомни завтра в 9 проверить ноль три в отчёте", NOW)
        self.assertEqual(result.time, "09:00")
        self.assertIn("ноль три", (result.text or "").lower())

    def test_existing_clock_forms_and_relative_minutes_are_unchanged(self):
        for text, expected in [("в 09:03", "09:03"), ("в полдень", "12:00"),
                               ("в половине девятого утра", "08:30"), ("без пятнадцати три", "14:45")]:
            with self.subTest(text=text):
                self.assertEqual(nlu.parse_when(text, NOW)[0], expected)
        self.assertEqual(nlu.parse_when("через три минуты", NOW)[0], "10:03")


if __name__ == "__main__":
    unittest.main()
