from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echolingua.providers.tts.base import TTSRequest
from echolingua.sentences.validator import Sentence
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


@dataclass(frozen=True)
class TelegramUserSettings:
    telegram_user_id: int
    selected_recipe: str
    selected_provider: str
    output_format: str
    voice_overrides_json: str
    extra_config_json: str

    def voice_overrides(self) -> dict[str, Any]:
        return json.loads(self.voice_overrides_json or "{}")

    def extra_config(self) -> dict[str, Any]:
        return json.loads(self.extra_config_json or "{}")


@dataclass(frozen=True)
class TelegramCsvImportRecord:
    telegram_user_id: int
    file_name: str
    file_path: str
    imported_rows: int
    imported_sentence_ids: list[str]
    created_at: str


@dataclass(frozen=True)
class TelegramUserRecipe:
    telegram_user_id: int
    recipe_key: str
    display_name: str
    recipe_kind: str
    template_key: str
    recipe_json: str
    created_at: str
    updated_at: str

    def recipe_data(self) -> dict[str, Any]:
        return json.loads(self.recipe_json or "{}")


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

    def upsert_telegram_user(
        self,
        telegram_user_id: int,
        chat_id: int,
        username: str = "",
        first_name: str = "",
        last_name: str = "",
        language_code: str = "",
    ) -> None:
        now = _utc_now()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO telegram_users(
                  telegram_user_id, username, first_name, last_name, language_code, chat_id, is_active, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                  username=excluded.username,
                  first_name=excluded.first_name,
                  last_name=excluded.last_name,
                  language_code=excluded.language_code,
                  chat_id=excluded.chat_id,
                  is_active=1,
                  updated_at=excluded.updated_at
                """,
                (telegram_user_id, username, first_name, last_name, language_code, chat_id, now, now),
            )
            conn.execute(
                """
                INSERT INTO telegram_user_settings(
                  telegram_user_id, selected_recipe, selected_provider, output_format,
                  voice_overrides_json, extra_config_json, created_at, updated_at
                )
                VALUES(?, 'persian_prompt_french_ladder', 'edge', 'wav', '{}', '{}', ?, ?)
                ON CONFLICT(telegram_user_id) DO NOTHING
                """,
                (telegram_user_id, now, now),
            )

    def get_telegram_user_settings(self, telegram_user_id: int) -> TelegramUserSettings:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT telegram_user_id, selected_recipe, selected_provider, output_format,
                       voice_overrides_json, extra_config_json
                FROM telegram_user_settings
                WHERE telegram_user_id=?
                """,
                (telegram_user_id,),
            ).fetchone()
        if row is None:
            raise KeyError(telegram_user_id)
        return TelegramUserSettings(
            telegram_user_id=int(row["telegram_user_id"]),
            selected_recipe=str(row["selected_recipe"]),
            selected_provider=str(row["selected_provider"]),
            output_format=str(row["output_format"]),
            voice_overrides_json=str(row["voice_overrides_json"]),
            extra_config_json=str(row["extra_config_json"]),
        )

    def update_telegram_user_settings(
        self,
        telegram_user_id: int,
        *,
        selected_recipe: str | None = None,
        selected_provider: str | None = None,
        output_format: str | None = None,
        voice_overrides: dict[str, Any] | None = None,
        extra_config: dict[str, Any] | None = None,
    ) -> None:
        current = self.get_telegram_user_settings(telegram_user_id)
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE telegram_user_settings
                SET selected_recipe=?,
                    selected_provider=?,
                    output_format=?,
                    voice_overrides_json=?,
                    extra_config_json=?,
                    updated_at=?
                WHERE telegram_user_id=?
                """,
                (
                    selected_recipe or current.selected_recipe,
                    selected_provider or current.selected_provider,
                    output_format or current.output_format,
                    json.dumps(voice_overrides if voice_overrides is not None else current.voice_overrides(), ensure_ascii=False),
                    json.dumps(extra_config if extra_config is not None else current.extra_config(), ensure_ascii=False),
                    _utc_now(),
                    telegram_user_id,
                ),
            )

    def add_user_sentences(self, telegram_user_id: int, sentence_ids: list[str], source_type: str = "csv_import") -> None:
        now = _utc_now()
        with self.db.connect() as conn:
            conn.executemany(
                """
                INSERT INTO telegram_user_sentences(telegram_user_id, sentence_id, source_type, added_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(telegram_user_id, sentence_id) DO UPDATE SET
                  source_type=excluded.source_type,
                  added_at=excluded.added_at
                """,
                [(telegram_user_id, sentence_id, source_type, now) for sentence_id in sentence_ids],
            )

    def replace_user_sentences(self, telegram_user_id: int, sentence_ids: list[str], source_type: str = "csv_import") -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM telegram_user_sentences WHERE telegram_user_id=?", (telegram_user_id,))
        self.add_user_sentences(telegram_user_id, sentence_ids, source_type=source_type)

    def remove_user_sentence(self, telegram_user_id: int, sentence_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "DELETE FROM telegram_user_sentences WHERE telegram_user_id=? AND sentence_id=?",
                (telegram_user_id, sentence_id),
            )
            conn.execute(
                "DELETE FROM telegram_sentence_library WHERE telegram_user_id=? AND sentence_id=?",
                (telegram_user_id, sentence_id),
            )

    def list_user_sentence_ids(self, telegram_user_id: int) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT sentence_id
                FROM telegram_user_sentences
                WHERE telegram_user_id=?
                ORDER BY
                  CASE
                    WHEN sentence_id GLOB '[0-9]*' THEN CAST(sentence_id AS INTEGER)
                    ELSE 2147483647
                  END,
                  sentence_id
                """,
                (telegram_user_id,),
            ).fetchall()
        return [str(row["sentence_id"]) for row in rows]

    def replace_telegram_sentence_library(
        self,
        telegram_user_id: int,
        sentences: list[Sentence],
        source_type: str = "csv_import",
    ) -> None:
        now = _utc_now()
        with self.db.connect() as conn:
            conn.execute("DELETE FROM telegram_sentence_library WHERE telegram_user_id=?", (telegram_user_id,))
            conn.executemany(
                """
                INSERT INTO telegram_sentence_library(
                  telegram_user_id, sentence_id, persian, english, french, level, category,
                  recommended_start, enabled, tags, notes, priority, difficulty, voice_hint,
                  pronunciation_note, source_type, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        telegram_user_id,
                        sentence.id,
                        sentence.persian,
                        sentence.english,
                        sentence.french,
                        sentence.level,
                        sentence.category,
                        sentence.recommended_start,
                        int(sentence.enabled),
                        ",".join(sentence.tags),
                        sentence.notes,
                        sentence.priority,
                        sentence.difficulty,
                        sentence.voice_hint,
                        sentence.pronunciation_note,
                        source_type,
                        now,
                    )
                    for sentence in sentences
                ],
            )

    def upsert_telegram_sentence(self, telegram_user_id: int, sentence: Sentence, source_type: str = "manual") -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO telegram_sentence_library(
                  telegram_user_id, sentence_id, persian, english, french, level, category,
                  recommended_start, enabled, tags, notes, priority, difficulty, voice_hint,
                  pronunciation_note, source_type, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id, sentence_id) DO UPDATE SET
                  persian=excluded.persian,
                  english=excluded.english,
                  french=excluded.french,
                  level=excluded.level,
                  category=excluded.category,
                  recommended_start=excluded.recommended_start,
                  enabled=excluded.enabled,
                  tags=excluded.tags,
                  notes=excluded.notes,
                  priority=excluded.priority,
                  difficulty=excluded.difficulty,
                  voice_hint=excluded.voice_hint,
                  pronunciation_note=excluded.pronunciation_note,
                  source_type=excluded.source_type,
                  updated_at=excluded.updated_at
                """,
                (
                    telegram_user_id,
                    sentence.id,
                    sentence.persian,
                    sentence.english,
                    sentence.french,
                    sentence.level,
                    sentence.category,
                    sentence.recommended_start,
                    int(sentence.enabled),
                    ",".join(sentence.tags),
                    sentence.notes,
                    sentence.priority,
                    sentence.difficulty,
                    sentence.voice_hint,
                    sentence.pronunciation_note,
                    source_type,
                    _utc_now(),
                ),
            )

    def get_telegram_sentence(self, telegram_user_id: int, sentence_id: str) -> Sentence | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT sentence_id, persian, english, french, level, category, recommended_start, enabled,
                       tags, notes, priority, difficulty, voice_hint, pronunciation_note
                FROM telegram_sentence_library
                WHERE telegram_user_id=? AND sentence_id=?
                """,
                (telegram_user_id, sentence_id),
            ).fetchone()
        if row is None:
            return None
        return Sentence(
            id=str(row["sentence_id"]),
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

    def list_telegram_sentences(self, telegram_user_id: int) -> list[Sentence]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT sentence_id, persian, english, french, level, category, recommended_start, enabled,
                       tags, notes, priority, difficulty, voice_hint, pronunciation_note
                FROM telegram_sentence_library
                WHERE telegram_user_id=?
                ORDER BY CAST(sentence_id AS INTEGER), sentence_id
                """,
                (telegram_user_id,),
            ).fetchall()
        return [
            Sentence(
                id=str(row["sentence_id"]),
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

    def find_telegram_sentence_by_text(self, telegram_user_id: int, target_language: str, text: str) -> Sentence | None:
        field = {
            "fr": "french",
            "en": "english",
            "fa": "persian",
        }.get(target_language, "french")
        normalized = text.strip().lower()
        with self.db.connect() as conn:
            row = conn.execute(
                f"""
                SELECT sentence_id, persian, english, french, level, category, recommended_start, enabled,
                       tags, notes, priority, difficulty, voice_hint, pronunciation_note
                FROM telegram_sentence_library
                WHERE telegram_user_id=? AND lower(trim({field}))=?
                LIMIT 1
                """,
                (telegram_user_id, normalized),
            ).fetchone()
        if row is None:
            return None
        return Sentence(
            id=str(row["sentence_id"]),
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

    def record_telegram_csv_import(
        self,
        telegram_user_id: int,
        file_name: str,
        file_path: Path,
        imported_sentence_ids: list[str],
    ) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO telegram_csv_imports(
                  telegram_user_id, file_name, file_path, imported_rows, imported_sentence_ids_json, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_user_id,
                    file_name,
                    str(file_path),
                    len(imported_sentence_ids),
                    json.dumps(imported_sentence_ids, ensure_ascii=False),
                    _utc_now(),
                ),
            )

    def latest_telegram_csv_import(self, telegram_user_id: int) -> TelegramCsvImportRecord | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT telegram_user_id, file_name, file_path, imported_rows, imported_sentence_ids_json, created_at
                FROM telegram_csv_imports
                WHERE telegram_user_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (telegram_user_id,),
            ).fetchone()
        if row is None:
            return None
        return TelegramCsvImportRecord(
            telegram_user_id=int(row["telegram_user_id"]),
            file_name=str(row["file_name"]),
            file_path=str(row["file_path"]),
            imported_rows=int(row["imported_rows"]),
            imported_sentence_ids=list(json.loads(str(row["imported_sentence_ids_json"]) or "[]")),
            created_at=str(row["created_at"]),
        )

    def upsert_telegram_user_recipe(
        self,
        telegram_user_id: int,
        recipe_key: str,
        display_name: str,
        recipe_kind: str,
        template_key: str,
        recipe_data: dict[str, Any],
    ) -> None:
        now = _utc_now()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO telegram_user_recipes(
                  telegram_user_id, recipe_key, display_name, recipe_kind, template_key,
                  recipe_json, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id, recipe_key) DO UPDATE SET
                  display_name=excluded.display_name,
                  recipe_kind=excluded.recipe_kind,
                  template_key=excluded.template_key,
                  recipe_json=excluded.recipe_json,
                  updated_at=excluded.updated_at
                """,
                (
                    telegram_user_id,
                    recipe_key,
                    display_name,
                    recipe_kind,
                    template_key,
                    json.dumps(recipe_data, ensure_ascii=False),
                    now,
                    now,
                ),
            )

    def list_telegram_user_recipes(self, telegram_user_id: int) -> list[TelegramUserRecipe]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT telegram_user_id, recipe_key, display_name, recipe_kind, template_key, recipe_json, created_at, updated_at
                FROM telegram_user_recipes
                WHERE telegram_user_id=?
                ORDER BY display_name, recipe_key
                """,
                (telegram_user_id,),
            ).fetchall()
        return [
            TelegramUserRecipe(
                telegram_user_id=int(row["telegram_user_id"]),
                recipe_key=str(row["recipe_key"]),
                display_name=str(row["display_name"]),
                recipe_kind=str(row["recipe_kind"]),
                template_key=str(row["template_key"]),
                recipe_json=str(row["recipe_json"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    def get_telegram_user_recipe(self, telegram_user_id: int, recipe_key: str) -> TelegramUserRecipe | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT telegram_user_id, recipe_key, display_name, recipe_kind, template_key, recipe_json, created_at, updated_at
                FROM telegram_user_recipes
                WHERE telegram_user_id=? AND recipe_key=?
                LIMIT 1
                """,
                (telegram_user_id, recipe_key),
            ).fetchone()
        if row is None:
            return None
        return TelegramUserRecipe(
            telegram_user_id=int(row["telegram_user_id"]),
            recipe_key=str(row["recipe_key"]),
            display_name=str(row["display_name"]),
            recipe_kind=str(row["recipe_kind"]),
            template_key=str(row["template_key"]),
            recipe_json=str(row["recipe_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def delete_telegram_user_recipe(self, telegram_user_id: int, recipe_key: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "DELETE FROM telegram_user_recipes WHERE telegram_user_id=? AND recipe_key=?",
                (telegram_user_id, recipe_key),
            )
