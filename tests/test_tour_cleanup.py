"""Tour cleanup deletes only the addressed sandbox, without reseeding it."""
from datetime import date
import unittest
from typing import cast

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from app import series
from app.database import Base
from app.main import sandbox_clear
from app.models import Account, DateKind, Record, Sandbox, Series, TaskType
from app.owner import Owner
from app.routers import chat
from tests.test_bulk_delete_calendar import AsyncSessionBridge


class TourCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.db = cast(AsyncSession, AsyncSessionBridge(self.session))
        self.session.add_all([Sandbox(client_id="tour-sandbox"), Sandbox(client_id="other-sandbox"),
                              Account(id=7, login="owner", login_lower="owner", password_hash="unused")])
        self.session.flush()
        self.owner = Owner(sandbox_id="tour-sandbox")

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    async def test_clear_removes_demo_created_records_and_repeats_only_for_tour(self):
        rule = Series(sandbox_id="tour-sandbox", type=TaskType.task, text="Учебный повтор",
                      weekdays="2", filled_until="2026-10-28", ended=False)
        self.session.add(rule)
        self.session.flush()
        self.session.add_all([
            Record(sandbox_id="tour-sandbox", type=TaskType.task, text="Демо", demo=True, date_kind=DateKind.none),
            Record(sandbox_id="tour-sandbox", type=TaskType.task, text="Создано в обучении", demo=False,
                   series_id=rule.id, date_kind=DateKind.exact, date="2026-10-28"),
            Record(account_id=7, type=TaskType.task, text="Личная", date_kind=DateKind.none),
            Record(sandbox_id="other-sandbox", type=TaskType.task, text="Чужая", date_kind=DateKind.none),
        ])
        self.session.commit()
        conv = chat.conversation(self.owner, "tour-dialog")
        conv.pending = chat.Pending("draft", {"text": "Учебный черновик"})
        result = await sandbox_clear(x_client_id="tour-sandbox", db=self.db)
        self.assertEqual(result.status_code, 204)
        self.assertIsNone(chat.conversation(self.owner, "tour-dialog").pending)
        self.session.expire_all()
        self.assertEqual({r.text for r in self.session.query(Record).all()}, {"Личная", "Чужая"})
        self.assertEqual(self.session.query(Series).count(), 0)
        self.assertIsNotNone(self.session.get(Sandbox, "tour-sandbox"))
        await series.extend(self.db, self.owner, date(2027, 10, 26))
        self.assertEqual(self.session.query(Record).filter(Record.sandbox_id == "tour-sandbox").count(), 0)
        self.assertEqual((await sandbox_clear(x_client_id="tour-sandbox", db=self.db)).status_code, 204)

    async def test_missing_or_invalid_sandbox_id_cannot_clear_anything(self):
        self.session.add(Record(account_id=7, type=TaskType.task, text="Личная", date_kind=DateKind.none))
        self.session.commit()
        for value in [None, "", "x", "../tour-sandbox"]:
            result = await sandbox_clear(x_client_id=value, db=self.db)
            self.assertEqual(result.status_code, 422)
        self.assertEqual(self.session.query(Record).count(), 1)


if __name__ == "__main__":
    unittest.main()
