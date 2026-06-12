from __future__ import annotations

from echolingua.sentences.validator import Sentence
from echolingua.storage.db import Database


class SentenceRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_many(self, sentences: list[Sentence]) -> None:
        with self.db.connect() as conn:
            conn.executemany(
                """
                INSERT INTO sentences(id, persian, french, level, category, recommended_start, enabled)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  persian=excluded.persian, french=excluded.french, level=excluded.level,
                  category=excluded.category, recommended_start=excluded.recommended_start,
                  enabled=excluded.enabled
                """,
                [(s.id, s.persian, s.french, s.level, s.category, s.recommended_start, int(s.enabled)) for s in sentences],
            )
