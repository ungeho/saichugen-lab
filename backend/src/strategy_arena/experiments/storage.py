import json
import sqlite3
from pathlib import Path
from uuid import uuid4


class ExperimentStore:
    def __init__(self, path: str | Path):
        self.path = path
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS experiments (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def save(self, payload: dict) -> str:
        identifier = str(uuid4())
        with sqlite3.connect(self.path) as connection:
            connection.execute("INSERT INTO experiments VALUES (?, ?)", (identifier, json.dumps(payload)))
        return identifier

    def get(self, identifier: str) -> dict | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT payload FROM experiments WHERE id = ?", (identifier,)).fetchone()
        return json.loads(row[0]) if row else None

    def iter_experiments(self):
        with sqlite3.connect(self.path) as connection:
            for identifier, payload in connection.execute("SELECT id, payload FROM experiments ORDER BY rowid"):
                yield identifier, json.loads(payload)
