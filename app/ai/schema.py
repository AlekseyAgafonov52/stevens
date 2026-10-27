"""Input and output of the AI layer: contract v1.6, section 5."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PrivateAttr, model_validator

RecordType = Literal["task", "reminder", "meeting", "note", "busy"]
Intent = Literal["create", "note", "list", "search", "person", "notes", "undated", "repeats",
                 "free", "complete", "delete", "move", "edit", "fix", "undo", "reply", "cancel",
                 "help", "greeting", "thanks", "off_topic", "unknown"]


def real_date(value: str) -> str:
    date.fromisoformat(value)
    return value


ISODate = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"), AfterValidator(real_date)]
ClockTime = Annotated[str, Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Repeat(Model):
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(min_length=1, max_length=7)
    until: ISODate | None = None


class Item(Model):
    type: RecordType
    text: str = Field(min_length=1, max_length=300)
    date: ISODate | None = None
    date_kind: Literal["exact", "deadline", "none"] = "exact"
    time: ClockTime | None = None
    end_time: ClockTime | None = None
    time_guess: Literal["day_part", "ambiguous"] | None = None
    remind_before: Annotated[int, Field(ge=0, le=1440)] | None = None
    repeat: Repeat | None = None

    @model_validator(mode="after")
    def invariants(self):
        if not self.text.strip():
            raise ValueError("Empty item text")
        if self.type == "note" and any((self.date, self.time, self.end_time, self.repeat)):
            raise ValueError("Notes cannot have a schedule")
        if self.remind_before is not None and self.type != "meeting":
            raise ValueError("Reminder interval belongs to a meeting")
        return self


class Period(Model):
    start: ISODate
    end: ISODate
    label: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("Reversed period")
        return self


class Query(Model):
    keywords: list[str] = Field(default_factory=list, max_length=100)
    person: str | None = None
    ask: Literal["when", "exists"] | None = None
    tense: Literal["past", "future"] | None = None
    type: RecordType | None = None
    date: ISODate | None = None


class Target(Model):
    ref: Literal["focus", "last", "shown", "query"]
    query: Query | None = None
    date: ISODate | None = None
    time: ClockTime | None = None
    all: bool = False
    count: Annotated[int, Field(ge=1)] | None = None
    index: Annotated[int, Field(ge=-1)] | None = None
    series: Literal["one", "all"] | None = None


class Replacement(Model):
    # Contract uses the Python keyword "from".
    from_: str = Field(alias="from", min_length=1, max_length=300)
    to: str = Field(min_length=1, max_length=300)


class Change(Model):
    date: ISODate | None = None
    time: ClockTime | None = None
    shift_minutes: int | None = None
    text: str | None = Field(default=None, min_length=1, max_length=300)
    type: RecordType | None = None
    replace: Replacement | None = None
    remind_before: Annotated[int, Field(ge=0, le=1440)] | None = None
    restore: bool | None = None


class Free(Model):
    mode: Literal["slots", "at", "longest", "day", "week"]
    date: ISODate | None = None
    period: Period | None = None
    time: ClockTime | None = None
    duration_min: int = Field(default=60, gt=0, le=1440)
    weekends: bool = True


class Reply(Model):
    kind: Literal["yes", "no", "choice", "time", "day", "day_time", "text", "other"]
    index: Annotated[int, Field(ge=-1)] | None = None
    date: ISODate | None = None
    time: ClockTime | None = None
    text: str | None = None


class Doubt(Model):
    why: Literal["typo", "or", "fix", "vague", "hedge", "unclear", "llm"]
    word: str | None = None
    right: str | None = None
    time: ClockTime | None = None

    @model_validator(mode="after")
    def explanation_fields(self):
        if self.why in ("typo", "vague") and not self.word:
            raise ValueError("Doubt requires the original word")
        if self.why == "typo" and not self.right:
            raise ValueError("Typo requires a correction")
        return self


class Result(Model):
    # Compatibility data belongs to the adapter, never to the public JSON.
    _rule_parses: list = PrivateAttr(default_factory=list)
    intent: Intent
    items: list[Item] = Field(default_factory=list, max_length=100)
    period: Period | None = None
    filter_type: Literal["task", "reminder", "meeting", "busy"] | None = None
    query_mode: Literal["list", "count", "workload", "summary"] | None = None
    query: Query | None = None
    target: Target | None = None
    change: Change | None = None
    free: Free | None = None
    reply: Reply | None = None
    confidence: float = Field(ge=0, le=1)
    doubts: list[Doubt] = Field(default_factory=list, max_length=100)
    layer: Literal["rules", "llm"]

    @model_validator(mode="after")
    def intent_fields(self):
        if self.intent == "create" and not self.items:
            raise ValueError("Create requires items")
        if self.intent == "note" and any(item.type != "note" for item in self.items):
            raise ValueError("Note requires note items")
        required = {"list": self.period, "search": self.query, "person": self.query,
                    "free": self.free, "complete": self.target, "delete": self.target,
                    "move": self.target, "edit": self.target, "reply": self.reply}
        if self.intent in required and required[self.intent] is None:
            raise ValueError("Missing intent fields")
        if self.intent in ("move", "edit", "fix") and self.change is None:
            raise ValueError("Missing change")
        if self.intent == "fix" and (self.change is None or self.change.replace is None):
            raise ValueError("Missing replacement")
        return self


class Awaiting(Model):
    question: Literal["time", "day", "day_time", "person", "yes_no", "choice", "text", "series"]
    about: dict | None = None
    options: list[str] | None = None


class Input(Model):
    text: str = Field(max_length=300)
    now: datetime
    timezone: str | None = None
    source: Literal["voice", "text", "button"] = "text"
    awaiting: Awaiting | None = None
    focus: dict | None = None
    last_query: dict | None = None
    history: list[dict[str, str]] = Field(default_factory=list, max_length=5)
