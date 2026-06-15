from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RecipeSegment:
    kind: str
    text_field: str | None = None
    language: str | None = None
    voice: str | None = None
    provider: str | None = None
    duration_ms: int | None = None
    pause_after_ms: int | None = None
    repeat: int = 1
    split_words: bool = False
    word_pause_ms: int | None = None
    delimiter_pattern: str | None = None
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecipeSegment":
        return cls(
            kind=str(data["kind"]),
            text_field=data.get("text_field"),
            language=data.get("language"),
            voice=data.get("voice"),
            provider=data.get("provider"),
            duration_ms=data.get("duration_ms"),
            pause_after_ms=data.get("pause_after_ms"),
            repeat=int(data.get("repeat", 1)),
            split_words=bool(data.get("split_words", False)),
            word_pause_ms=data.get("word_pause_ms"),
            delimiter_pattern=data.get("delimiter_pattern"),
            rate=str(data.get("rate", "+0%")),
            pitch=str(data.get("pitch", "+0Hz")),
            volume=str(data.get("volume", "+0%")),
        )


@dataclass(frozen=True)
class Recipe:
    name: str
    description: str
    output_format: str
    provider_policy: dict[str, Any] = field(default_factory=dict)
    segments: list[RecipeSegment] = field(default_factory=list)
