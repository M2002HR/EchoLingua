from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from echolingua.providers.tts.base import TTSRequest
from echolingua.storage.db import Database


class StorageRepositories:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create_job(self, job_id: str, recipe_name: str, status: str = "running") -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO jobs(id, recipe_name, status) VALUES(?, ?, ?)",
                (job_id, recipe_name, status),
            )

    def complete_job(self, job_id: str, status: str = "completed") -> None:
        with self.db.connect() as conn:
            conn.execute("UPDATE jobs SET status=?, completed_at=CURRENT_TIMESTAMP WHERE id=?", (status, job_id))

    def record_event(self, job_id: str, event: str, payload: dict[str, Any] | None = None) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO job_events(job_id, event, payload_json) VALUES(?, ?, ?)",
                (job_id, event, json.dumps(payload or {}, ensure_ascii=False)),
            )

    def record_provider_attempt(self, job_id: str, provider_name: str, provider_kind: str, status: str, error: str | None) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO provider_attempts(job_id, provider_name, provider_kind, status, error) VALUES(?, ?, ?, ?, ?)",
                (job_id, provider_name, provider_kind, status, error),
            )

    def record_audio_output(self, job_id: str, path: Path, manifest_path: Path, duration_ms: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO audio_outputs(job_id, path, manifest_path, duration_ms) VALUES(?, ?, ?, ?)",
                (job_id, str(path), str(manifest_path), duration_ms),
            )

    def upsert_tts_cache(self, cache_key: str, provider_name: str, request: TTSRequest, path: Path, duration_ms: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO tts_cache(cache_key, provider_name, text, voice, rate, pitch, volume, language, path, duration_ms)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET path=excluded.path, duration_ms=excluded.duration_ms
                """,
                (
                    cache_key,
                    provider_name,
                    request.text,
                    request.voice,
                    request.rate,
                    request.pitch,
                    request.volume,
                    request.language,
                    str(path),
                    duration_ms,
                ),
            )
