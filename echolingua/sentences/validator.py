from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from echolingua.core.errors import ValidationError

REQUIRED_COLUMNS = ["id", "persian", "french", "level", "category", "recommended_start"]
OPTIONAL_COLUMNS = [
    "english",
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
    english: str
    french: str
    level: str
    category: str
    recommended_start: str
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
            english=str(row.get("english", "") or "").strip(),
            french=str(row["french"]).strip(),
            level=str(row["level"]).strip(),
            category=str(row["category"]).strip(),
            recommended_start=str(row["recommended_start"]).strip(),
            enabled=_as_bool(row.get("enabled", True)),
            tags=_as_tags(row.get("tags", "")),
            notes=str(row.get("notes", "") or ""),
            priority=int(row.get("priority") or 0),
            difficulty=int(row.get("difficulty") or 0),
            voice_hint=str(row.get("voice_hint", "") or ""),
            pronunciation_note=str(row.get("pronunciation_note", "") or ""),
        )

    @classmethod
    def missing_required_fields(cls, row: dict[str, Any]) -> list[str]:
        return [column for column in REQUIRED_COLUMNS if not str(row.get(column, "")).strip()]


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


@dataclass(frozen=True)
class SentenceValidationIssue:
    row_number: int
    row_id: str
    message: str
    missing_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SentenceValidationReport:
    total_rows: int
    enabled_rows: int
    disabled_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_ids: list[str] = field(default_factory=list)
    missing_required_fields: dict[str, int] = field(default_factory=dict)
    levels_summary: dict[str, int] = field(default_factory=dict)
    categories_summary: dict[str, int] = field(default_factory=dict)
    issues: list[SentenceValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.invalid_rows == 0 and not self.duplicate_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "enabled_rows": self.enabled_rows,
            "disabled_rows": self.disabled_rows,
            "valid_rows": self.valid_rows,
            "invalid_rows": self.invalid_rows,
            "duplicate_ids": self.duplicate_ids,
            "missing_required_fields": self.missing_required_fields,
            "levels_summary": self.levels_summary,
            "categories_summary": self.categories_summary,
            "issues": [
                {
                    "row_number": issue.row_number,
                    "row_id": issue.row_id,
                    "message": issue.message,
                    "missing_fields": issue.missing_fields,
                }
                for issue in self.issues
            ],
        }


def build_validation_report(rows: list[dict[str, Any]]) -> tuple[list[Sentence], SentenceValidationReport]:
    seen_ids: set[str] = set()
    duplicate_ids: list[str] = []
    valid_sentences: list[Sentence] = []
    issues: list[SentenceValidationIssue] = []
    missing_fields_counter: Counter[str] = Counter()
    levels_counter: Counter[str] = Counter()
    categories_counter: Counter[str] = Counter()
    enabled_rows = 0
    disabled_rows = 0

    for index, row in enumerate(rows, start=2):
        row_id = str(row.get("id", "")).strip()
        missing_fields = Sentence.missing_required_fields(row)
        if missing_fields:
            missing_fields_counter.update(missing_fields)
            issues.append(
                SentenceValidationIssue(
                    row_number=index,
                    row_id=row_id,
                    message=f"Missing required sentence fields: {', '.join(missing_fields)}",
                    missing_fields=missing_fields,
                )
            )
            continue
        if row_id in seen_ids:
            duplicate_ids.append(row_id)
            issues.append(
                SentenceValidationIssue(
                    row_number=index,
                    row_id=row_id,
                    message=f"Duplicate sentence id: {row_id}",
                )
            )
            continue
        try:
            sentence = Sentence.from_row(row)
        except (TypeError, ValueError, ValidationError) as exc:
            issues.append(
                SentenceValidationIssue(
                    row_number=index,
                    row_id=row_id,
                    message=str(exc),
                )
            )
            continue
        seen_ids.add(row_id)
        valid_sentences.append(sentence)
        levels_counter[sentence.level] += 1
        categories_counter[sentence.category] += 1
        if sentence.enabled:
            enabled_rows += 1
        else:
            disabled_rows += 1

    report = SentenceValidationReport(
        total_rows=len(rows),
        enabled_rows=enabled_rows,
        disabled_rows=disabled_rows,
        valid_rows=len(valid_sentences),
        invalid_rows=len(issues),
        duplicate_ids=duplicate_ids,
        missing_required_fields=dict(sorted(missing_fields_counter.items())),
        levels_summary=dict(sorted(levels_counter.items())),
        categories_summary=dict(sorted(categories_counter.items())),
        issues=issues,
    )
    return valid_sentences, report
