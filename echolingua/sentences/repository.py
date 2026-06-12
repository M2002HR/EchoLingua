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
                INSERT INTO sentences(
                  id, persian, english, french, level, category, recommended_start, enabled,
                  tags, notes, priority, difficulty, voice_hint, pronunciation_note
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  persian=excluded.persian, english=excluded.english, french=excluded.french, level=excluded.level,
                  category=excluded.category, recommended_start=excluded.recommended_start,
                  enabled=excluded.enabled, tags=excluded.tags, notes=excluded.notes,
                  priority=excluded.priority, difficulty=excluded.difficulty,
                  voice_hint=excluded.voice_hint, pronunciation_note=excluded.pronunciation_note
                """,
                [
                    (
                        s.id,
                        s.persian,
                        s.english,
                        s.french,
                        s.level,
                        s.category,
                        s.recommended_start,
                        int(s.enabled),
                        ",".join(s.tags),
                        s.notes,
                        s.priority,
                        s.difficulty,
                        s.voice_hint,
                        s.pronunciation_note,
                    )
                    for s in sentences
                ],
            )
