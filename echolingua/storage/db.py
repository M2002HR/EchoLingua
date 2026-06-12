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
