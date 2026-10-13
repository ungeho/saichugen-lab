import json
import sqlite3
from contextlib import closing
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

    def update(self, identifier: str, payload: dict) -> None:
        """新規ジョブ自身の保存レコードだけを更新する。旧実験は移行しない。"""
        with sqlite3.connect(self.path) as connection:
            changed = connection.execute("UPDATE experiments SET payload=? WHERE id=?", (json.dumps(payload), identifier))
            if changed.rowcount != 1:
                raise KeyError(identifier)

    def iter_experiments(self):
        # 呼び出し側が履歴を集計・再読込している間、読取ロックを保持しない。
        # 同じDBへ進捗を保存するワーカーとのロック待ち循環を避ける。
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute("SELECT id, payload FROM experiments ORDER BY rowid").fetchall()
        for identifier, payload in rows:
            yield identifier, json.loads(payload)
