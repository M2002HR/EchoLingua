from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioOutputRecord:
    job_id: str
    path: Path
    manifest_path: Path
    duration_ms: int
