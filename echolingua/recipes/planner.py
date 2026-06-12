from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from echolingua.core.errors import ConfigError
from echolingua.recipes.models import Recipe
from echolingua.sentences.validator import Sentence


@dataclass(frozen=True)
class AudioPlanSegment:
    kind: str
    sentence_id: str
    text: str | None = None
    text_field: str | None = None
    language: str | None = None
    voice: str | None = None
    provider: str | None = None
    duration_ms: int | None = None
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"
    sequence: int = 0

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class AudioPlan:
    job_id: str
    recipe_name: str
    output_format: str
    target_language: str = "fr"
    target_column: str = "french"
    source_csv_path: str = ""
    selected_sentence_ids: list[str] = field(default_factory=list)
    segments: list[AudioPlanSegment] = field(default_factory=list)

    def estimate_segment_count(self) -> int:
        return len(self.segments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "recipe_name": self.recipe_name,
            "output_format": self.output_format,
            "target_language": self.target_language,
            "target_column": self.target_column,
            "source_csv_path": self.source_csv_path,
            "selected_sentence_ids": self.selected_sentence_ids,
            "segment_count": len(self.segments),
            "segments": [segment.to_dict() for segment in self.segments],
        }


class AudioPlanBuilder:
    def build(
        self,
        job_id: str,
        recipe: Recipe,
        sentences: list[Sentence],
        source_csv_path: str = "",
        target_language: str = "fr",
        target_column: str = "french",
    ) -> AudioPlan:
        planned: list[AudioPlanSegment] = []
        sequence = 0
        for sentence in sentences:
            for recipe_segment in recipe.segments:
                sequence += 1
                text = self._resolve_text(sentence, recipe_segment.text_field, target_column)
                planned.append(
                    AudioPlanSegment(
                        kind=recipe_segment.kind,
                        sentence_id=sentence.id,
                        text=text,
                        text_field=recipe_segment.text_field,
                        language=recipe_segment.language,
                        voice=sentence.voice_hint or recipe_segment.voice,
                        provider=recipe_segment.provider,
                        duration_ms=recipe_segment.duration_ms,
                        rate=recipe_segment.rate,
                        pitch=recipe_segment.pitch,
                        volume=recipe_segment.volume,
                        sequence=sequence,
                    )
                )
        return AudioPlan(
            job_id=job_id,
            recipe_name=recipe.name,
            output_format=recipe.output_format,
            target_language=target_language,
            target_column=target_column,
            source_csv_path=source_csv_path,
            selected_sentence_ids=[sentence.id for sentence in sentences],
            segments=planned,
        )

    def _resolve_text(self, sentence: Sentence, text_field: str | None, target_column: str) -> str | None:
        if text_field is None:
            return None
        resolved_field = target_column if text_field == "target" else text_field
        if not hasattr(sentence, resolved_field):
            raise ConfigError(f"Recipe references missing sentence field: {text_field}")
        value = getattr(sentence, resolved_field)
        return str(value) if value is not None else None
