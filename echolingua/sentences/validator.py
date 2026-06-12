from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from echolingua.core.errors import ValidationError

REQUIRED_COLUMNS = ["id", "persian", "french", "level", "category", "recommended_start"]
OPTIONAL_COLUMNS = [
    "enabled",
    "tags",
    "notes",
    "priority",
    "difficulty",
    "voice_hint",
    "pronunciation_note",
]


@dataclass(frozen=True)
class Sentence:
    id: str
    persian: str
    french: str
    level: str
    category: str
    recommended_start: int
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    priority: int = 0
    difficulty: int = 0
    voice_hint: str = ""
    pronunciation_note: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Sentence":
        missing = [column for column in REQUIRED_COLUMNS if not str(row.get(column, "")).strip()]
        if missing:
            raise ValidationError(f"Missing required sentence fields: {', '.join(missing)}")
        return cls(
            id=str(row["id"]).strip(),
            persian=str(row["persian"]).strip(),
            french=str(row["french"]).strip(),
            level=str(row["level"]).strip(),
            category=str(row["category"]).strip(),
            recommended_start=int(row["recommended_start"]),
            enabled=_as_bool(row.get("enabled", True)),
            tags=_as_tags(row.get("tags", "")),
            notes=str(row.get("notes", "") or ""),
            priority=int(row.get("priority") or 0),
            difficulty=int(row.get("difficulty") or 0),
            voice_hint=str(row.get("voice_hint", "") or ""),
            pronunciation_note=str(row.get("pronunciation_note", "") or ""),
        )


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"false", "0", "no", "n", "off"}


def _as_tags(value: Any) -> list[str]:
    return [tag.strip() for tag in str(value or "").split(",") if tag.strip()]


def validate_columns(columns: list[str]) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in columns]
    if missing:
        raise ValidationError(f"CSV missing required columns: {', '.join(missing)}")
