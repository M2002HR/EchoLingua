from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from echolingua.core.config import AppConfig
from echolingua.core.errors import ConfigError, ValidationError
from echolingua.pipeline.runner import PipelineRunner
from echolingua.recipes.loader import get_recipe
from echolingua.recipes.models import Recipe
from echolingua.sentences.loader import load_sentences_with_report
from echolingua.sentences.repository import SentenceRepository
from echolingua.sentences.validator import Sentence
from echolingua.storage.db import Database
from echolingua.storage.repositories import StorageRepositories, TelegramUserSettings


@dataclass(frozen=True)
class TelegramUserProfile:
    telegram_user_id: int
    chat_id: int
    username: str
    first_name: str
    last_name: str
    language_code: str


class TelegramBotService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db = Database(config.db_path)
        self.db.initialize()
        self.repositories = StorageRepositories(self.db)
        self.runner = PipelineRunner(config)
        self.sentence_repository = SentenceRepository(self.db)
        self.config.telegram_import_dir.mkdir(parents=True, exist_ok=True)
        self.config.telegram_export_dir.mkdir(parents=True, exist_ok=True)
        self.config.telegram_temp_audio_dir.mkdir(parents=True, exist_ok=True)

    def ensure_user(
        self,
        *,
        telegram_user_id: int,
        chat_id: int,
        username: str = "",
        first_name: str = "",
        last_name: str = "",
        language_code: str = "",
    ) -> TelegramUserSettings:
        self.repositories.upsert_telegram_user(
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
        )
        return self.repositories.get_telegram_user_settings(telegram_user_id)

    def get_settings(self, telegram_user_id: int) -> TelegramUserSettings:
        return self.repositories.get_telegram_user_settings(telegram_user_id)

    def update_settings(self, telegram_user_id: int, **kwargs: Any) -> TelegramUserSettings:
        self.repositories.update_telegram_user_settings(telegram_user_id, **kwargs)
        return self.repositories.get_telegram_user_settings(telegram_user_id)

    def import_csv_for_user(self, telegram_user_id: int, source_path: Path, file_name: str | None = None) -> dict[str, Any]:
        stored_path = self.config.telegram_import_dir / (file_name or source_path.name)
        stored_path.write_bytes(source_path.read_bytes())
        sentences, report = load_sentences_with_report(stored_path, include_disabled=True)
        if not report.is_valid:
            issue = report.issues[0].message if report.issues else "CSV validation failed."
            raise ValidationError(issue)
        self._persist_sentences(sentences)
        enabled_sentences = [sentence for sentence in sentences if sentence.enabled]
        self.repositories.replace_telegram_sentence_library(telegram_user_id, enabled_sentences, source_type="csv_import")
        self.repositories.replace_user_sentences(
            telegram_user_id,
            [sentence.id for sentence in enabled_sentences],
            source_type="csv_import",
        )
        self.repositories.record_telegram_csv_import(
            telegram_user_id,
            file_name or source_path.name,
            stored_path,
            [sentence.id for sentence in enabled_sentences],
        )
        return {
            "path": stored_path,
            "report": report,
            "imported_sentence_ids": [sentence.id for sentence in enabled_sentences],
        }

    def export_user_csv(self, telegram_user_id: int) -> Path:
        sentences = self.list_user_sentences(telegram_user_id)
        export_path = self.config.telegram_export_dir / f"user_{telegram_user_id}_sentences.csv"
        with export_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "id",
                    "persian",
                    "english",
                    "french",
                    "level",
                    "category",
                    "recommended_start",
                    "enabled",
                    "tags",
                    "notes",
                    "priority",
                    "difficulty",
                    "voice_hint",
                    "pronunciation_note",
                ]
            )
            for sentence in sentences:
                writer.writerow(
                    [
                        sentence.id,
                        sentence.persian,
                        sentence.english,
                        sentence.french,
                        sentence.level,
                        sentence.category,
                        sentence.recommended_start,
                        "true" if sentence.enabled else "false",
                        ",".join(sentence.tags),
                        sentence.notes,
                        sentence.priority,
                        sentence.difficulty,
                        sentence.voice_hint,
                        sentence.pronunciation_note,
                    ]
                )
        return export_path

    def list_user_sentences(self, telegram_user_id: int) -> list[Sentence]:
        sentence_ids = self.repositories.list_user_sentence_ids(telegram_user_id)
        by_id = {sentence.id: sentence for sentence in self.repositories.list_telegram_sentences(telegram_user_id)}
        return [by_id[sentence_id] for sentence_id in sentence_ids if sentence_id in by_id]

    def add_sentence_to_user(self, telegram_user_id: int, sentence_id: str) -> None:
        sentence = self._sentence_by_id(sentence_id)
        if sentence is None:
            raise ValidationError(f"Unknown sentence id: {sentence_id}")
        self.repositories.upsert_telegram_sentence(telegram_user_id, sentence, source_type="manual")
        self.repositories.add_user_sentences(telegram_user_id, [sentence_id], source_type="manual")

    def remove_sentence_from_user(self, telegram_user_id: int, sentence_id: str) -> None:
        self.repositories.remove_user_sentence(telegram_user_id, sentence_id)

    def generate_sentence_audio_for_user(
        self,
        telegram_user_id: int,
        sentence_id: str,
        *,
        recipe_name: str | None = None,
        provider_name: str | None = None,
        output_format: str | None = None,
    ) -> dict[str, Any]:
        settings = self.get_settings(telegram_user_id)
        sentence = next((item for item in self.list_user_sentences(telegram_user_id) if item.id == sentence_id), None)
        if sentence is None:
            raise ValidationError(f"Sentence {sentence_id} is not in the user's list.")
        output_dir = self.config.telegram_temp_audio_dir / str(telegram_user_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        resolved_recipe_name = recipe_name or settings.selected_recipe
        resolved_provider_name = provider_name or settings.selected_provider
        resolved_output_format = output_format or settings.output_format
        recipe_payload = self.resolve_recipe_for_user(telegram_user_id, resolved_recipe_name)
        result = self.runner.generate_sentence_files(
            job_id=f"tg-{telegram_user_id}-{sentence_id}",
            csv_path=self._write_single_sentence_csv(sentence),
            recipe_name=recipe_payload["recipe_name"],
            output_dir=output_dir,
            output_format=resolved_output_format,
            provider_name=resolved_provider_name,
        )
        file_entry = result["files"][0]
        return {
            "audio_path": Path(str(file_entry["output"])),
            "manifest_path": Path(str(file_entry["manifest"])),
            "caption": self.build_caption(sentence),
            "sentence": sentence,
            "recipe_name": recipe_payload["recipe_name"],
            "recipe_summary": recipe_payload["summary"],
        }

    def generate_all_sentence_audio_for_user(self, telegram_user_id: int) -> list[dict[str, Any]]:
        return [
            self.generate_sentence_audio_for_user(telegram_user_id, sentence.id)
            for sentence in self.list_user_sentences(telegram_user_id)
        ]

    def build_caption(self, sentence: Sentence) -> str:
        english = sentence.english or "-"
        return "\n".join(
            [
                f"🇮🇷 فارسی: {sentence.persian}",
                f"🇬🇧 English: {english}",
                f"🇫🇷 Français: {sentence.french}",
            ]
        )

    def available_recipes(self) -> list[str]:
        recipes = sorted((self.config.recipes.get("recipes") or {}).keys())
        if "telegram_custom_ladder" not in recipes:
            recipes.append("telegram_custom_ladder")
        return recipes

    def available_tts_providers(self) -> list[dict[str, Any]]:
        return self.runner.list_providers("tts")

    def available_output_formats(self) -> list[str]:
        return ["wav", "mp3"]

    def latest_import_summary(self, telegram_user_id: int) -> dict[str, Any] | None:
        record = self.repositories.latest_telegram_csv_import(telegram_user_id)
        if record is None:
            return None
        return {
            "file_name": record.file_name,
            "file_path": record.file_path,
            "imported_rows": record.imported_rows,
            "imported_sentence_ids": record.imported_sentence_ids,
            "created_at": record.created_at,
        }

    def paginated_user_sentences(self, telegram_user_id: int, page: int, page_size: int | None = None) -> dict[str, Any]:
        settings = self.get_settings(telegram_user_id)
        configured_page_size = int(settings.extra_config().get("page_size", page_size or 8))
        page_size_value = max(1, min(20, configured_page_size))
        sentences = self.list_user_sentences(telegram_user_id)
        total_items = len(sentences)
        total_pages = max(1, (total_items + page_size_value - 1) // page_size_value) if total_items else 1
        normalized_page = max(0, min(page, total_pages - 1))
        start = normalized_page * page_size_value
        end = start + page_size_value
        return {
            "items": sentences[start:end],
            "page": normalized_page,
            "page_size": page_size_value,
            "total_items": total_items,
            "total_pages": total_pages,
        }

    def sentence_summary(self, telegram_user_id: int) -> dict[str, Any]:
        sentences = self.list_user_sentences(telegram_user_id)
        levels: dict[str, int] = {}
        categories: dict[str, int] = {}
        for sentence in sentences:
            levels[sentence.level] = levels.get(sentence.level, 0) + 1
            categories[sentence.category] = categories.get(sentence.category, 0) + 1
        return {
            "count": len(sentences),
            "levels": dict(sorted(levels.items())),
            "categories": dict(sorted(categories.items())),
        }

    def create_or_update_custom_recipe(self, telegram_user_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        settings = self.get_settings(telegram_user_id)
        extra = settings.extra_config()
        custom = dict(extra.get("custom_recipe", {}))
        custom.update(updates)
        custom = self._normalized_custom_recipe_config(custom)
        extra["custom_recipe"] = custom
        self.update_settings(
            telegram_user_id,
            selected_recipe="telegram_custom_ladder",
            extra_config=extra,
        )
        return custom

    def describe_custom_recipe(self, telegram_user_id: int) -> dict[str, Any]:
        settings = self.get_settings(telegram_user_id)
        custom = self._normalized_custom_recipe_config(settings.extra_config().get("custom_recipe", {}))
        return {
            **custom,
            "summary": self._custom_recipe_summary(custom),
        }

    def resolve_recipe_for_user(self, telegram_user_id: int, recipe_name: str) -> dict[str, Any]:
        if recipe_name != "telegram_custom_ladder":
            recipe = get_recipe(self.config.recipes, recipe_name)
            return {"recipe_name": recipe_name, "recipe": recipe, "summary": recipe.description}
        custom = self.describe_custom_recipe(telegram_user_id)
        recipe = self._build_custom_recipe(custom)
        self._register_runtime_recipe("telegram_custom_ladder", recipe)
        return {"recipe_name": "telegram_custom_ladder", "recipe": recipe, "summary": custom["summary"]}

    def recipe_prompt_presets(self) -> list[dict[str, str]]:
        return [
            {"key": "persian", "label": "🇮🇷 فارسی", "value": "persian"},
            {"key": "english", "label": "🇬🇧 انگلیسی", "value": "english"},
            {"key": "none", "label": "🚫 بدون مقدمه", "value": "none"},
        ]

    def _persist_sentences(self, sentences: list[Sentence]) -> None:
        self.sentence_repository.upsert_many(sentences)

    def _load_all_sentences(self) -> list[Sentence]:
        return self.sentence_repository.list_all()

    def _sentence_by_id(self, sentence_id: str) -> Sentence | None:
        return next((sentence for sentence in self._load_all_sentences() if sentence.id == sentence_id), None)

    def _write_single_sentence_csv(self, sentence: Sentence) -> Path:
        path = self.config.telegram_temp_audio_dir / f"sentence_{sentence.id}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "id",
                    "persian",
                    "english",
                    "french",
                    "level",
                    "category",
                    "recommended_start",
                    "enabled",
                    "tags",
                    "notes",
                    "priority",
                    "difficulty",
                    "voice_hint",
                    "pronunciation_note",
                ]
            )
            writer.writerow(
                [
                    sentence.id,
                    sentence.persian,
                    sentence.english,
                    sentence.french,
                    sentence.level,
                    sentence.category,
                    sentence.recommended_start,
                    "true" if sentence.enabled else "false",
                    ",".join(sentence.tags),
                    sentence.notes,
                    sentence.priority,
                    sentence.difficulty,
                    sentence.voice_hint,
                    sentence.pronunciation_note,
                ]
            )
        return path

    def _register_runtime_recipe(self, name: str, recipe: Recipe) -> None:
        recipes = dict(self.config.recipes.get("recipes") or {})
        recipes[name] = {
            "description": recipe.description,
            "output_format": recipe.output_format,
            "provider_policy": recipe.provider_policy,
            "segments": [
                {
                    "kind": segment.kind,
                    "text_field": segment.text_field,
                    "language": segment.language,
                    "voice": segment.voice,
                    "provider": segment.provider,
                    "duration_ms": segment.duration_ms,
                    "pause_after_ms": segment.pause_after_ms,
                    "repeat": segment.repeat,
                    "split_words": segment.split_words,
                    "word_pause_ms": segment.word_pause_ms,
                    "delimiter_pattern": segment.delimiter_pattern,
                    "rate": segment.rate,
                    "pitch": segment.pitch,
                    "volume": segment.volume,
                }
                for segment in recipe.segments
            ],
        }
        self.config.recipes["recipes"] = recipes

    def _build_custom_recipe(self, custom: dict[str, Any]) -> Recipe:
        provider_policy = {
            "tts": {
                "strategy": "explicit",
                "explicit_provider": str(custom["provider"]),
                "default_provider": str(custom["provider"]),
                "allow_fallback_on_error": False,
            }
        }
        segments: list[dict[str, Any]] = []
        prompt_field = str(custom["prompt_field"])
        pause_between = int(custom["pause_between_ms"])
        if prompt_field != "none":
            segments.append(
                {
                    "kind": "tts",
                    "text_field": prompt_field,
                    "language": "fa" if prompt_field == "persian" else "en",
                    "voice": str(custom["prompt_voice"]),
                }
            )
            segments.append({"kind": "silence", "duration_ms": pause_between})
        segments.extend(
            [
                {
                    "kind": "tts",
                    "text_field": "french",
                    "language": "fr",
                    "voice": str(custom["normal_voice"]),
                    "rate": str(custom["normal_rate"]),
                },
                {"kind": "silence", "duration_ms": pause_between},
                {
                    "kind": "tts",
                    "text_field": "french",
                    "language": "fr",
                    "voice": str(custom["word_by_word_voice"]),
                    "split_words": True,
                    "word_pause_ms": int(custom["word_pause_ms"]),
                },
                {"kind": "silence", "duration_ms": pause_between},
                {
                    "kind": "tts",
                    "text_field": "french",
                    "language": "fr",
                    "voice": str(custom["slow_voice"]),
                    "rate": str(custom["slow_rate"]),
                },
                {"kind": "silence", "duration_ms": pause_between},
                {
                    "kind": "tts",
                    "text_field": "french",
                    "language": "fr",
                    "voice": str(custom["final_voice"]),
                    "rate": str(custom["final_rate"]),
                },
            ]
        )
        recipe_data = {
            "description": self._custom_recipe_summary(custom),
            "output_format": str(custom["output_format"]),
            "provider_policy": provider_policy,
            "segments": segments,
        }
        return get_recipe({"recipes": {"telegram_custom_ladder": recipe_data}}, "telegram_custom_ladder")

    def _normalized_custom_recipe_config(self, value: dict[str, Any]) -> dict[str, Any]:
        voices = self._edge_voice_defaults()
        provider = str(value.get("provider") or "edge")
        if provider != "edge":
            raise ConfigError("The current Telegram custom recipe only supports the edge provider.")
        return {
            "provider": provider,
            "output_format": str(value.get("output_format") or "wav"),
            "prompt_field": str(value.get("prompt_field") or "persian"),
            "prompt_voice": str(value.get("prompt_voice") or voices["fa_female"]),
            "normal_voice": str(value.get("normal_voice") or voices["fr_male"]),
            "word_by_word_voice": str(value.get("word_by_word_voice") or voices["fr_male"]),
            "slow_voice": str(value.get("slow_voice") or voices["fr_male"]),
            "final_voice": str(value.get("final_voice") or voices["fr_male"]),
            "pause_between_ms": int(value.get("pause_between_ms") or 3000),
            "word_pause_ms": int(value.get("word_pause_ms") or 900),
            "normal_rate": str(value.get("normal_rate") or "+0%"),
            "slow_rate": str(value.get("slow_rate") or "-20%"),
            "final_rate": str(value.get("final_rate") or "+0%"),
        }

    def _custom_recipe_summary(self, custom: dict[str, Any]) -> str:
        prompt = {
            "persian": "Persian prompt",
            "english": "English prompt",
            "none": "No prompt",
        }.get(str(custom["prompt_field"]), "Custom prompt")
        return (
            f"{prompt}, French normal, word-by-word, slow, final replay. "
            f"Pause {custom['pause_between_ms']}ms, word pause {custom['word_pause_ms']}ms."
        )

    def _edge_voice_defaults(self) -> dict[str, str]:
        edge = (self.config.providers.get("tts") or {}).get("edge", {})
        voices = edge.get("voices", {})
        return {
            "fa_male": str(voices.get("fa_male", "fa-IR-FaridNeural")),
            "fa_female": str(voices.get("fa_female", voices.get("fa", "fa-IR-DilaraNeural"))),
            "fr_male": str(voices.get("fr_male", "fr-FR-HenriNeural")),
            "fr_female": str(voices.get("fr_female", voices.get("fr", "fr-FR-DeniseNeural"))),
            "en_male": str(voices.get("en_male", "en-US-ChristopherNeural")),
            "en_female": str(voices.get("en_female", voices.get("en", "en-US-JennyNeural"))),
        }
