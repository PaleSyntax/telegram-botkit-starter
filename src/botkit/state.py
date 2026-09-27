"""Persist polling cursor after successful replies, without retaining messages."""

from contextlib import closing
from pathlib import Path
import sqlite3


class CursorStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS cursor (id INTEGER PRIMARY KEY CHECK(id=1), offset INTEGER NOT NULL)")

    def load(self) -> int | None:
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT offset FROM cursor WHERE id=1").fetchone()
            return row[0] if row else None

    def save(self, offset: int):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO cursor VALUES (1,?) ON CONFLICT(id) DO UPDATE SET offset=excluded.offset", (offset,))
