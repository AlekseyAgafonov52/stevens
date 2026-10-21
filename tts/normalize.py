"""Текст для Silero: модель не читает цифры и латиницу, поэтому всё переводим в русские слова.

Что встречается в speech у Stevens: «завтра в 15:00», «до 24 октября», «24 октября 2027 года»,
«3 дела», «15 минут», «Нашёл 12 записей». Плюс тексты самих записей — там может быть что угодно.
"""
import re

ONES_M = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
ONES_F = ["ноль", "одна", "две"] + ONES_M[3:]
ONES_N = ["ноль", "одно", "два"] + ONES_M[3:]
TEENS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
         "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]

# Порядковые в родительном падеже: «24 октября» → «двадцать четвёртого октября»
ORD_ONES = ["", "первого", "второго", "третьего", "четвёртого", "пятого", "шестого", "седьмого", "восьмого", "девятого"]
ORD_TEENS = ["десятого", "одиннадцатого", "двенадцатого", "тринадцатого", "четырнадцатого", "пятнадцатого",
             "шестнадцатого", "семнадцатого", "восемнадцатого", "девятнадцатого"]
ORD_TENS = ["", "", "двадцатого", "тридцатого", "сорокового", "пятидесятого", "шестидесятого", "семидесятого",
            "восьмидесятого", "девяностого"]
ORD_HUNDREDS = ["", "сотого", "двухсотого", "трёхсотого", "четырёхсотого", "пятисотого", "шестисотого",
                "семисотого", "восьмисотого", "девятисотого"]

MONTHS = "января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря"
FEMININE = ("запис", "минут", "встреч", "задач", "секунд", "недел")
NEUTER = ("дел", "напоминан")


def _below_thousand(n: int, ones: list[str]) -> list[str]:
    words = []
    if n >= 100:
        words.append(HUNDREDS[n // 100])
        n %= 100
    if 10 <= n < 20:
        words.append(TEENS[n - 10])
    else:
        if n >= 20:
            words.append(TENS[n // 10])
            n %= 10
        if n:
            words.append(ones[n])
    return words


def cardinal(n: int, gender: str = "m") -> str:
    if n == 0:
        return "ноль"
    ones = {"f": ONES_F, "n": ONES_N}.get(gender, ONES_M)
    words = []
    if n >= 1_000_000:
        return " ".join(ONES_M[int(d)] for d in str(n))  # большие числа — по цифрам
    if n >= 1000:
        th = n // 1000
        words += _below_thousand(th, ONES_F)
        last = th % 100
        if 11 <= last <= 14 or last % 10 == 0 or last % 10 >= 5:
            words.append("тысяч")
        elif last % 10 == 1:
            words.append("тысяча")
        else:
            words.append("тысячи")
        n %= 1000
    if n:
        words += _below_thousand(n, ones)
    return " ".join(words)


def ordinal_gen(n: int) -> str:
    """Порядковое числительное в родительном падеже мужского/среднего рода (1–2999)."""
    words = []
    if n >= 1000:
        th = n // 1000
        rest = n % 1000
        if rest == 0:
            return ("" if th == 1 else cardinal(th, "f") + " ") + "тысячного"
        words.append("тысяча" if th == 1 else cardinal(th, "f") + (" тысячи" if th < 5 else " тысяч"))
        n = rest
    if n >= 100:
        if n % 100 == 0:
            words.append(ORD_HUNDREDS[n // 100])
            return " ".join(words)
        words.append(HUNDREDS[n // 100])
        n %= 100
    if 10 <= n < 20:
        words.append(ORD_TEENS[n - 10])
    elif n % 10 == 0:
        words.append(ORD_TENS[n // 10])
    else:
        if n >= 20:
            words.append(TENS[n // 10])
        words.append(ORD_ONES[n % 10])
    return " ".join(words)


def _time(m: re.Match) -> str:
    h, mm = int(m.group(1)), int(m.group(2))
    if mm == 0:
        tail = "ноль-ноль"
    elif mm < 10:
        tail = "ноль " + cardinal(mm, "f")
    else:
        tail = cardinal(mm, "f")
    return f"{cardinal(h)} {tail}"


def _gender_for(word: str) -> str:
    w = word.lower()
    if w.startswith(FEMININE):
        return "f"
    if w.startswith(NEUTER):
        return "n"
    return "m"


LATIN = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "дж",
    "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т",
    "u": "у", "v": "в", "w": "в", "x": "кс", "y": "й", "z": "з",
}
LETTER_NAMES = {
    "A": "эй", "B": "би", "C": "си", "D": "ди", "E": "и", "F": "эф", "G": "джи", "H": "эйч", "I": "ай",
    "J": "джей", "K": "кей", "L": "эл", "M": "эм", "N": "эн", "O": "оу", "P": "пи", "Q": "кью", "R": "ар",
    "S": "эс", "T": "ти", "U": "ю", "V": "ви", "W": "дабл ю", "X": "экс", "Y": "уай", "Z": "зед",
}


def _latin(m: re.Match) -> str:
    word = m.group(0)
    if word.isupper() and len(word) <= 5:  # аббревиатура: CRM → си ар эм
        return " ".join(LETTER_NAMES[c] for c in word)
    return "".join(LATIN.get(c, c) for c in word.lower())


def normalize(text: str) -> str:
    t = text.replace("—", ",").replace("«", "").replace("»", "").replace(" ", " ")
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b", _time, t)
    t = re.sub(rf"\b(\d{{1,2}})\s+({MONTHS})\b", lambda m: f"{ordinal_gen(int(m.group(1)))} {m.group(2)}", t)
    t = re.sub(r"\b(\d{4})\s+(года|году)\b", lambda m: f"{ordinal_gen(int(m.group(1)))} {m.group(2)}", t)
    t = re.sub(r"\b(\d+)\s+([А-Яа-яЁё]+)", lambda m: f"{cardinal(int(m.group(1)), _gender_for(m.group(2)))} {m.group(2)}", t)
    t = re.sub(r"\d+", lambda m: cardinal(int(m.group(0))), t)
    t = re.sub(r"[A-Za-z]+", _latin, t)
    t = re.sub(r"[^А-Яа-яЁё ,.!?:;\-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()
