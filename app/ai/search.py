"""Pure keyword ranking in the AI layer; the caller supplies owner-filtered records."""
from app import nlu


def rank(records, keywords: list[str], required: list[str]):
    def words(record):
        return [w.strip(".,:;!?«»\"()") for w in record.text.replace("-", " ").split()]

    candidates = [r for r in records if all(nlu.record_has(words(r), key) for key in required)]
    scored = [(sum(nlu.record_has(words(r), key) for key in keywords), r) for r in candidates]
    exact = [r for score, r in scored if score == len(keywords)]
    return exact or [r for score, r in scored if score > 0]
