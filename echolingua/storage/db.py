from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS sentences (
      id TEXT PRIMARY KEY,
      persian TEXT NOT NULL,
      english TEXT NOT NULL DEFAULT '',
      french TEXT NOT NULL,
      level TEXT NOT NULL,
      category TEXT NOT NULL,
      recommended_start TEXT NOT NULL,
      enabled INTEGER NOT NULL,
      tags TEXT NOT NULL DEFAULT '',
      notes TEXT NOT NULL DEFAULT '',
      priority INTEGER NOT NULL DEFAULT 0,
      difficulty INTEGER NOT NULL DEFAULT 0,
      voice_hint TEXT NOT NULL DEFAULT '',
      pronunciation_note TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jobs (
      job_id TEXT PRIMARY KEY,
      recipe_name TEXT NOT NULL,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL,
      completed_at TEXT,
      error_message TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS job_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id TEXT NOT NULL,
      event_name TEXT NOT NULL,
      event_status TEXT NOT NULL DEFAULT 'ok',
      component TEXT NOT NULL DEFAULT 'echolingua',
      operation TEXT,
      duration_ms INTEGER,
      level TEXT NOT NULL DEFAULT 'INFO',
      trace_id TEXT,
      span_id TEXT,
      parent_span_id TEXT,
      error_json TEXT,
      payload_json TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_attempts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id TEXT NOT NULL,
      provider_name TEXT NOT NULL,
      provider_kind TEXT NOT NULL,
      status TEXT NOT NULL,
      error_message TEXT,
      duration_ms INTEGER,
      cache_key TEXT,
      request_summary_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audio_outputs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id TEXT NOT NULL,
      output_path TEXT NOT NULL,
      manifest_path TEXT NOT NULL,
      duration_ms INTEGER NOT NULL,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tts_cache (
      cache_key TEXT PRIMARY KEY,
      provider_name TEXT NOT NULL,
      request_text TEXT NOT NULL,
      request_voice TEXT NOT NULL,
      request_language TEXT NOT NULL,
      request_rate TEXT NOT NULL,
      request_pitch TEXT NOT NULL,
      request_volume TEXT NOT NULL,
      path TEXT NOT NULL,
      duration_ms INTEGER NOT NULL,
      hit_count INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS telegram_users (
      telegram_user_id INTEGER PRIMARY KEY,
      username TEXT NOT NULL DEFAULT '',
      first_name TEXT NOT NULL DEFAULT '',
      last_name TEXT NOT NULL DEFAULT '',
      language_code TEXT NOT NULL DEFAULT '',
      chat_id INTEGER NOT NULL,
      is_active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS telegram_user_sentences (
      telegram_user_id INTEGER NOT NULL,
      sentence_id TEXT NOT NULL,
      source_type TEXT NOT NULL DEFAULT 'csv_import',
      added_at TEXT NOT NULL,
      PRIMARY KEY (telegram_user_id, sentence_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS telegram_sentence_library (
      telegram_user_id INTEGER NOT NULL,
      sentence_id TEXT NOT NULL,
      persian TEXT NOT NULL,
      english TEXT NOT NULL DEFAULT '',
      french TEXT NOT NULL,
      level TEXT NOT NULL,
      category TEXT NOT NULL,
      recommended_start TEXT NOT NULL,
      enabled INTEGER NOT NULL,
      tags TEXT NOT NULL DEFAULT '',
      notes TEXT NOT NULL DEFAULT '',
      priority INTEGER NOT NULL DEFAULT 0,
      difficulty INTEGER NOT NULL DEFAULT 0,
      voice_hint TEXT NOT NULL DEFAULT '',
      pronunciation_note TEXT NOT NULL DEFAULT '',
      source_type TEXT NOT NULL DEFAULT 'csv_import',
      updated_at TEXT NOT NULL,
      PRIMARY KEY (telegram_user_id, sentence_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS telegram_user_settings (
      telegram_user_id INTEGER PRIMARY KEY,
      selected_recipe TEXT NOT NULL DEFAULT 'persian_prompt_french_ladder',
      selected_provider TEXT NOT NULL DEFAULT 'edge',
      output_format TEXT NOT NULL DEFAULT 'wav',
      voice_overrides_json TEXT NOT NULL DEFAULT '{}',
      extra_config_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS telegram_csv_imports (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      telegram_user_id INTEGER NOT NULL,
      file_name TEXT NOT NULL,
      file_path TEXT NOT NULL,
      imported_rows INTEGER NOT NULL DEFAULT 0,
      imported_sentence_ids_json TEXT NOT NULL DEFAULT '[]',
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS telegram_user_recipes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      telegram_user_id INTEGER NOT NULL,
      recipe_key TEXT NOT NULL,
      display_name TEXT NOT NULL,
      recipe_kind TEXT NOT NULL DEFAULT 'guided',
      template_key TEXT NOT NULL DEFAULT 'ladder',
      recipe_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(telegram_user_id, recipe_key)
    )
    """,
)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.exists()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as conn:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            self._ensure_job_columns(conn)
            self._ensure_job_event_columns(conn)
            self._ensure_provider_attempt_columns(conn)

    def _ensure_job_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        additions = {
            "total_steps": "INTEGER NOT NULL DEFAULT 0",
            "completed_steps": "INTEGER NOT NULL DEFAULT 0",
            "current_stage": "TEXT",
            "current_message": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")

    def _ensure_job_event_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(job_events)").fetchall()}
        additions = {
            "event_status": "TEXT NOT NULL DEFAULT 'ok'",
            "component": "TEXT NOT NULL DEFAULT 'echolingua'",
            "operation": "TEXT",
            "duration_ms": "INTEGER",
            "level": "TEXT NOT NULL DEFAULT 'INFO'",
            "trace_id": "TEXT",
            "span_id": "TEXT",
            "parent_span_id": "TEXT",
            "error_json": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE job_events ADD COLUMN {name} {definition}")

    def _ensure_provider_attempt_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(provider_attempts)").fetchall()}
        additions = {
            "duration_ms": "INTEGER",
            "cache_key": "TEXT",
            "request_summary_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE provider_attempts ADD COLUMN {name} {definition}")
