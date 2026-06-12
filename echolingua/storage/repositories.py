from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echolingua.providers.tts.base import TTSRequest
from echolingua.storage.db import Database


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class StatsSummary:
    total_jobs: int
    successful_jobs: int
    failed_jobs: int
    total_provider_attempts: int
    provider_attempts_by_provider: dict[str, int]
    cache_hits: int
    cache_misses: int
    generated_audio_outputs: int
    total_output_duration_ms: int
    latest_job: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_jobs": self.total_jobs,
            "successful_jobs": self.successful_jobs,
            "failed_jobs": self.failed_jobs,
            "total_provider_attempts": self.total_provider_attempts,
            "provider_attempts_by_provider": self.provider_attempts_by_provider,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "generated_audio_outputs": self.generated_audio_outputs,
            "total_output_duration_ms": self.total_output_duration_ms,
            "latest_job": self.latest_job,
        }


@dataclass(frozen=True)
class CacheStatsSummary:
    entry_count: int
    entries_by_provider: dict[str, int]
    approx_size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_count": self.entry_count,
            "entries_by_provider": self.entries_by_provider,
            "approx_size_bytes": self.approx_size_bytes,
        }


class StorageRepositories:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create_job(self, job_id: str, recipe_name: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs(
                  job_id, recipe_name, status, created_at, completed_at, error_message,
                  total_steps, completed_steps, current_stage, current_message
                )
                VALUES(?, ?, 'running', ?, NULL, NULL, 0, 0, 'created', 'Job created')
                ON CONFLICT(job_id) DO UPDATE SET recipe_name=excluded.recipe_name, status='running',
                  created_at=excluded.created_at, completed_at=NULL, error_message=NULL,
                  total_steps=0, completed_steps=0, current_stage='created', current_message='Job created'
                """,
                (job_id, recipe_name, _utc_now()),
            )

    def complete_job(self, job_id: str, total_steps: int | None = None) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status='completed', completed_at=?, error_message=NULL,
                    current_stage='finished', current_message='Generation complete',
                    total_steps=COALESCE(?, total_steps),
                    completed_steps=COALESCE(?, completed_steps)
                WHERE job_id=?
                """,
                (_utc_now(), total_steps, total_steps, job_id),
            )

    def fail_job(self, job_id: str, error_message: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status='failed', completed_at=?, error_message=?,
                    current_stage='failed', current_message=?
                WHERE job_id=?
                """,
                (_utc_now(), error_message, error_message, job_id),
            )

    def update_job_progress(
        self,
        job_id: str,
        stage: str,
        message: str,
        completed_steps: int,
        total_steps: int,
        status: str = "running",
    ) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status=?, current_stage=?, current_message=?, completed_steps=?, total_steps=?
                WHERE job_id=?
                """,
                (status, stage, message, completed_steps, total_steps, job_id),
            )

    def record_event(self, job_id: str, event_name: str, payload: dict[str, Any]) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO job_events(job_id, event_name, payload_json, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (job_id, event_name, json.dumps(payload, ensure_ascii=False), _utc_now()),
            )

    def record_provider_attempt(
        self,
        job_id: str,
        provider_name: str,
        provider_kind: str,
        status: str,
        error_message: str | None,
    ) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_attempts(job_id, provider_name, provider_kind, status, error_message, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (job_id, provider_name, provider_kind, status, error_message, _utc_now()),
            )

    def record_audio_output(self, job_id: str, output: Path, manifest_path: Path, duration_ms: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO audio_outputs(job_id, output_path, manifest_path, duration_ms, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (job_id, str(output), str(manifest_path), duration_ms, _utc_now()),
            )

    def upsert_tts_cache(self, cache_key: str, provider_name: str, request: TTSRequest, path: Path, duration_ms: int) -> None:
        timestamp = _utc_now()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO tts_cache(
                  cache_key, provider_name, request_text, request_voice, request_language,
                  request_rate, request_pitch, request_volume, path, duration_ms, hit_count, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                  provider_name=excluded.provider_name,
                  request_text=excluded.request_text,
                  request_voice=excluded.request_voice,
                  request_language=excluded.request_language,
                  request_rate=excluded.request_rate,
                  request_pitch=excluded.request_pitch,
                  request_volume=excluded.request_volume,
                  path=excluded.path,
                  duration_ms=excluded.duration_ms,
                  hit_count=tts_cache.hit_count + 1,
                  updated_at=excluded.updated_at
                """,
                (
                    cache_key,
                    provider_name,
                    request.text,
                    request.voice,
                    request.language,
                    request.rate,
                    request.pitch,
                    request.volume,
                    str(path),
                    duration_ms,
                    timestamp,
                    timestamp,
                ),
            )

    def stats_summary(self) -> StatsSummary:
        with self.db.connect() as conn:
            total_jobs = int(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
            successful_jobs = int(conn.execute("SELECT COUNT(*) FROM jobs WHERE status='completed'").fetchone()[0])
            failed_jobs = int(conn.execute("SELECT COUNT(*) FROM jobs WHERE status='failed'").fetchone()[0])
            total_provider_attempts = int(conn.execute("SELECT COUNT(*) FROM provider_attempts").fetchone()[0])
            provider_rows = conn.execute(
                """
                SELECT provider_name, COUNT(*) AS count
                FROM provider_attempts
                GROUP BY provider_name
                ORDER BY provider_name
                """
            ).fetchall()
            cache_hits = int(conn.execute("SELECT COUNT(*) FROM provider_attempts WHERE status='cache_hit'").fetchone()[0])
            cache_misses = int(conn.execute("SELECT COUNT(*) FROM provider_attempts WHERE status='success'").fetchone()[0])
            generated_audio_outputs = int(conn.execute("SELECT COUNT(*) FROM audio_outputs").fetchone()[0])
            total_output_duration_ms = int(
                conn.execute("SELECT COALESCE(SUM(duration_ms), 0) FROM audio_outputs").fetchone()[0]
            )
            latest_job_row = conn.execute(
                """
                SELECT job_id, recipe_name, status, current_stage, completed_steps, total_steps
                FROM jobs
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        return StatsSummary(
            total_jobs=total_jobs,
            successful_jobs=successful_jobs,
            failed_jobs=failed_jobs,
            total_provider_attempts=total_provider_attempts,
            provider_attempts_by_provider={str(row["provider_name"]): int(row["count"]) for row in provider_rows},
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            generated_audio_outputs=generated_audio_outputs,
            total_output_duration_ms=total_output_duration_ms,
            latest_job=(
                {
                    "job_id": str(latest_job_row["job_id"]),
                    "recipe_name": str(latest_job_row["recipe_name"]),
                    "status": str(latest_job_row["status"]),
                    "current_stage": latest_job_row["current_stage"],
                    "completed_steps": int(latest_job_row["completed_steps"] or 0),
                    "total_steps": int(latest_job_row["total_steps"] or 0),
                }
                if latest_job_row is not None
                else None
            ),
        )

    def cache_stats_summary(self) -> CacheStatsSummary:
        with self.db.connect() as conn:
            entry_count = int(conn.execute("SELECT COUNT(*) FROM tts_cache").fetchone()[0])
            provider_rows = conn.execute(
                """
                SELECT provider_name, COUNT(*) AS count
                FROM tts_cache
                GROUP BY provider_name
                ORDER BY provider_name
                """
            ).fetchall()
            cache_paths = [Path(str(row["path"])) for row in conn.execute("SELECT path FROM tts_cache").fetchall()]
        approx_size_bytes = sum(path.stat().st_size for path in cache_paths if path.exists())
        return CacheStatsSummary(
            entry_count=entry_count,
            entries_by_provider={str(row["provider_name"]): int(row["count"]) for row in provider_rows},
            approx_size_bytes=approx_size_bytes,
        )
