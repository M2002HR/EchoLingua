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

    def list_all(self) -> list[Sentence]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, persian, english, french, level, category, recommended_start, enabled,
                       tags, notes, priority, difficulty, voice_hint, pronunciation_note
                FROM sentences
                ORDER BY id
                """
            ).fetchall()
        return [
            Sentence(
                id=str(row["id"]),
                persian=str(row["persian"]),
                english=str(row["english"]),
                french=str(row["french"]),
                level=str(row["level"]),
                category=str(row["category"]),
                recommended_start=str(row["recommended_start"]),
                enabled=bool(row["enabled"]),
                tags=[tag.strip() for tag in str(row["tags"]).split(",") if tag.strip()],
                notes=str(row["notes"]),
                priority=int(row["priority"] or 0),
                difficulty=int(row["difficulty"] or 0),
                voice_hint=str(row["voice_hint"]),
                pronunciation_note=str(row["pronunciation_note"]),
            )
            for row in rows
        ]
