from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from echolingua.core.config import AppConfig
from echolingua.core.errors import ConfigError, ValidationError
from echolingua.core.logging import JsonlLogger
from echolingua.pipeline.runner import PipelineRunner
from echolingua.recipes.loader import get_recipe
from echolingua.recipes.models import Recipe, RecipeSegment
from echolingua.sentences.loader import load_sentences_with_report
from echolingua.sentences.repository import SentenceRepository
from echolingua.sentences.validator import Sentence
from echolingua.storage.db import Database
from echolingua.storage.repositories import (
    StorageRepositories,
    TelegramLibraryCategory,
    TelegramUserRecipe,
    TelegramUserSettings,
)

TARGET_LANGUAGES: dict[str, dict[str, str]] = {
    "fr": {"field": "french", "label": "Français", "emoji": "🇫🇷"},
    "en": {"field": "english", "label": "English", "emoji": "🇬🇧"},
    "fa": {"field": "persian", "label": "فارسی", "emoji": "🇮🇷"},
}

GUIDED_RECIPE_TEMPLATES: dict[str, dict[str, str]] = {
    "ladder": {"label": "Ladder", "description": "Prompt + normal + word-by-word + slow + final"},
    "listen_repeat": {"label": "Listen & Repeat", "description": "Prompt + normal + pause + repeat"},
}

ALL_SENTENCES_CATEGORY_KEY = "all"
DEFAULT_LIBRARY_CATEGORY_KEY = "general"
DEFAULT_LIBRARY_CATEGORY_NAME = "General"


@dataclass(frozen=True)
class TelegramUserProfile:
    telegram_user_id: int
    chat_id: int
    username: str
    first_name: str
    last_name: str
    language_code: str


@dataclass(frozen=True)
class RecipeDescriptor:
    key: str
    display_name: str
    origin: str
    recipe_name: str
    summary: str
    kind: str
    editable: bool


@dataclass(frozen=True)
class LibraryCategoryDescriptor:
    key: str
    display_name: str
    target_language: str
    description: str
    sentence_count: int
    is_virtual: bool = False


class TelegramBotService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db = Database(config.db_path)
        self.db.initialize()
        self.repositories = StorageRepositories(self.db)
        self.logger = JsonlLogger(config.log_dir)
        self.runner = PipelineRunner(config)
        self.sentence_repository = SentenceRepository(self.db)
        self.config.telegram_import_dir.mkdir(parents=True, exist_ok=True)
        self.config.telegram_export_dir.mkdir(parents=True, exist_ok=True)
        self.config.telegram_temp_audio_dir.mkdir(parents=True, exist_ok=True)
        self.config.telegram_import_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_default_category(self, telegram_user_id: int, target_language: str | None = None) -> None:
        language = target_language or self.get_target_language(telegram_user_id)
        self.repositories.ensure_telegram_library_category(
            telegram_user_id,
            DEFAULT_LIBRARY_CATEGORY_KEY,
            DEFAULT_LIBRARY_CATEGORY_NAME,
            target_language=language,
            description="Default user category.",
        )

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
        settings = self.repositories.get_telegram_user_settings(telegram_user_id)
        extra = settings.extra_config()
        changed = False
        if "target_language" not in extra:
            extra["target_language"] = "fr"
            changed = True
        if "page_size" not in extra:
            extra["page_size"] = 8
            changed = True
        if "selected_library_category" not in extra:
            extra["selected_library_category"] = ALL_SENTENCES_CATEGORY_KEY
            changed = True
        if changed:
            self.repositories.update_telegram_user_settings(telegram_user_id, extra_config=extra)
        self._ensure_default_category(telegram_user_id, str(extra.get("target_language", "fr")))
        return self.repositories.get_telegram_user_settings(telegram_user_id)

    def selected_library_category(self, telegram_user_id: int) -> str:
        settings = self.get_settings(telegram_user_id)
        category_key = str(settings.extra_config().get("selected_library_category", ALL_SENTENCES_CATEGORY_KEY) or ALL_SENTENCES_CATEGORY_KEY)
        if category_key != ALL_SENTENCES_CATEGORY_KEY and self.repositories.get_telegram_library_category(telegram_user_id, category_key) is None:
            return ALL_SENTENCES_CATEGORY_KEY
        return category_key

    def set_selected_library_category(self, telegram_user_id: int, category_key: str) -> TelegramUserSettings:
        if category_key != ALL_SENTENCES_CATEGORY_KEY:
            category = self.repositories.get_telegram_library_category(telegram_user_id, category_key)
            if category is None:
                raise ValidationError(f"Unknown library category: {category_key}")
        settings = self.get_settings(telegram_user_id)
        extra = settings.extra_config()
        extra["selected_library_category"] = category_key
        return self.update_settings(telegram_user_id, extra_config=extra)

    def create_library_category(
        self,
        telegram_user_id: int,
        name: str,
        *,
        target_language: str | None = None,
        description: str = "",
    ) -> LibraryCategoryDescriptor:
        display_name = name.strip()
        if not display_name:
            raise ValidationError("Category name is required.")
        category_key = self._slugify_category_key(display_name)
        if category_key == ALL_SENTENCES_CATEGORY_KEY:
            category_key = f"{category_key}_group"
        if self.repositories.get_telegram_library_category(telegram_user_id, category_key) is not None:
            raise ValidationError(f"Category already exists: {display_name}")
        self.repositories.ensure_telegram_library_category(
            telegram_user_id,
            category_key,
            display_name,
            target_language=target_language or self.get_target_language(telegram_user_id),
            description=description.strip(),
        )
        self.set_selected_library_category(telegram_user_id, category_key)
        return self.describe_library_category(telegram_user_id, category_key)

    def update_library_category(
        self,
        telegram_user_id: int,
        category_key: str,
        *,
        display_name: str | None = None,
        target_language: str | None = None,
        description: str | None = None,
    ) -> LibraryCategoryDescriptor:
        if category_key == ALL_SENTENCES_CATEGORY_KEY:
            raise ValidationError("The all sentences category cannot be edited.")
        current = self.repositories.get_telegram_library_category(telegram_user_id, category_key)
        if current is None:
            raise ValidationError(f"Unknown library category: {category_key}")
        if display_name is not None and not display_name.strip():
            raise ValidationError("Category name is required.")
        self.repositories.update_telegram_library_category(
            telegram_user_id,
            category_key,
            display_name=display_name.strip() if display_name is not None else None,
            target_language=target_language,
            description=description.strip() if description is not None else None,
        )
        return self.describe_library_category(telegram_user_id, category_key)

    def list_library_categories(self, telegram_user_id: int) -> list[LibraryCategoryDescriptor]:
        self._ensure_default_category(telegram_user_id)
        sentence_counts = self.repositories.category_sentence_counts(telegram_user_id)
        categories = [
            LibraryCategoryDescriptor(
                key=ALL_SENTENCES_CATEGORY_KEY,
                display_name="All Sentences",
                target_language=self.get_target_language(telegram_user_id),
                description="Virtual category containing the full user library.",
                sentence_count=len(self.list_user_sentences(telegram_user_id)),
                is_virtual=True,
            )
        ]
        for category in self.repositories.list_telegram_library_categories(telegram_user_id):
            categories.append(
                LibraryCategoryDescriptor(
                    key=category.category_key,
                    display_name=category.display_name,
                    target_language=category.target_language,
                    description=category.description,
                    sentence_count=sentence_counts.get(category.category_key, 0),
                    is_virtual=False,
                )
            )
        return categories

    def describe_library_category(self, telegram_user_id: int, category_key: str) -> LibraryCategoryDescriptor:
        if category_key == ALL_SENTENCES_CATEGORY_KEY:
            return LibraryCategoryDescriptor(
                key=ALL_SENTENCES_CATEGORY_KEY,
                display_name="All Sentences",
                target_language=self.get_target_language(telegram_user_id),
                description="Virtual category containing the full user library.",
                sentence_count=len(self.list_user_sentences(telegram_user_id)),
                is_virtual=True,
            )
        category = self.repositories.get_telegram_library_category(telegram_user_id, category_key)
        if category is None:
            raise ValidationError(f"Unknown library category: {category_key}")
        counts = self.repositories.category_sentence_counts(telegram_user_id)
        return LibraryCategoryDescriptor(
            key=category.category_key,
            display_name=category.display_name,
            target_language=category.target_language,
            description=category.description,
            sentence_count=counts.get(category.category_key, 0),
            is_virtual=False,
        )

    def get_settings(self, telegram_user_id: int) -> TelegramUserSettings:
        return self.repositories.get_telegram_user_settings(telegram_user_id)

    def update_settings(self, telegram_user_id: int, **kwargs: Any) -> TelegramUserSettings:
        self.repositories.update_telegram_user_settings(telegram_user_id, **kwargs)
        return self.repositories.get_telegram_user_settings(telegram_user_id)

    def import_csv_for_user(
        self,
        telegram_user_id: int,
        source_path: Path,
        file_name: str | None = None,
        *,
        library_category_key: str | None = None,
        new_category_name: str | None = None,
        replace_existing_category: bool = True,
    ) -> dict[str, Any]:
        job_id = f"telegram-import-{telegram_user_id}"
        with self.logger.trace(
            "telegram.import_csv_for_user",
            component="telegram.service",
            job_id=job_id,
            metadata={
                "telegram_user_id": telegram_user_id,
                "source_path": str(source_path),
                "file_name": file_name,
                "library_category_key": library_category_key,
                "new_category_name": new_category_name,
            },
        ) as trace:
            stored_path = self.config.telegram_import_dir / (file_name or source_path.name)
            with trace.span("telegram.copy_import_file", component="telegram.service", payload={"stored_path": str(stored_path)}) as span:
                stored_path.write_bytes(source_path.read_bytes())
                span.set_result(stored_path=str(stored_path), size_bytes=stored_path.stat().st_size)
            with trace.span("telegram.load_import_csv", component="telegram.service", payload={"stored_path": str(stored_path)}) as span:
                sentences, report = load_sentences_with_report(stored_path, include_disabled=True)
                span.set_result(total_rows=report.total_rows, enabled_rows=report.enabled_rows, valid=report.is_valid)
            if not report.is_valid:
                issue = report.issues[0].message if report.issues else "CSV validation failed."
                raise ValidationError(issue)
            with trace.span("telegram.persist_import_sentences", component="telegram.service", payload={"telegram_user_id": telegram_user_id}) as span:
                self._persist_sentences(sentences)
                enabled_sentences = [sentence for sentence in sentences if sentence.enabled]
                for sentence in enabled_sentences:
                    self.repositories.upsert_telegram_sentence(telegram_user_id, sentence, source_type="csv_import")
                self.repositories.add_user_sentences(
                    telegram_user_id,
                    [sentence.id for sentence in enabled_sentences],
                    source_type="csv_import",
                )
                resolved_category_key = self._resolve_import_category(
                    telegram_user_id,
                    library_category_key=library_category_key,
                    new_category_name=new_category_name,
                )
                if replace_existing_category:
                    self.repositories.replace_category_sentences(
                        telegram_user_id,
                        resolved_category_key,
                        [sentence.id for sentence in enabled_sentences],
                        source_type="csv_import",
                    )
                else:
                    self.repositories.add_sentences_to_category(
                        telegram_user_id,
                        resolved_category_key,
                        [sentence.id for sentence in enabled_sentences],
                        source_type="csv_import",
                    )
                self.repositories.record_telegram_csv_import(
                    telegram_user_id,
                    file_name or source_path.name,
                    stored_path,
                    [sentence.id for sentence in enabled_sentences],
                    library_category_key=resolved_category_key,
                )
                self.set_selected_library_category(telegram_user_id, resolved_category_key)
                span.set_result(imported_sentence_count=len(enabled_sentences), library_category_key=resolved_category_key)
            trace.set_summary(
                telegram_user_id=telegram_user_id,
                imported_sentence_count=len(enabled_sentences),
                file_name=file_name or source_path.name,
                stored_path=str(stored_path),
                library_category_key=resolved_category_key,
            )
            return {
                "path": stored_path,
                "report": report,
                "imported_sentence_ids": [sentence.id for sentence in enabled_sentences],
                "library_category_key": resolved_category_key,
            }

    def export_user_csv(self, telegram_user_id: int, category_key: str = ALL_SENTENCES_CATEGORY_KEY) -> Path:
        job_id = f"telegram-export-{telegram_user_id}"
        with self.logger.trace(
            "telegram.export_user_csv",
            component="telegram.service",
            job_id=job_id,
            metadata={"telegram_user_id": telegram_user_id, "category_key": category_key},
        ) as trace:
            descriptor = self.describe_library_category(telegram_user_id, category_key)
            sentences = self.list_user_sentences(telegram_user_id, category_key=category_key)
            export_path = self.config.telegram_export_dir / f"user_{telegram_user_id}_{descriptor.key}_sentences.csv"
            with trace.span("telegram.write_export_csv", component="telegram.service", payload={"export_path": str(export_path)}) as span:
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
                span.set_result(export_path=str(export_path), sentence_count=len(sentences), category_key=category_key)
            trace.set_summary(
                telegram_user_id=telegram_user_id,
                export_path=str(export_path),
                sentence_count=len(sentences),
                category_key=category_key,
            )
            return export_path

    def list_user_sentences(self, telegram_user_id: int, category_key: str = ALL_SENTENCES_CATEGORY_KEY) -> list[Sentence]:
        sentence_ids = (
            self.repositories.list_user_sentence_ids(telegram_user_id)
            if category_key == ALL_SENTENCES_CATEGORY_KEY
            else self.repositories.list_category_sentence_ids(telegram_user_id, category_key)
        )
        by_id = {sentence.id: sentence for sentence in self.repositories.list_telegram_sentences(telegram_user_id)}
        return [by_id[sentence_id] for sentence_id in sentence_ids if sentence_id in by_id]

    def add_sentence_to_user(self, telegram_user_id: int, sentence_id: str, category_key: str = DEFAULT_LIBRARY_CATEGORY_KEY) -> None:
        sentence = self._sentence_by_id(sentence_id)
        if sentence is None:
            raise ValidationError(f"Unknown sentence id: {sentence_id}")
        self.repositories.upsert_telegram_sentence(telegram_user_id, sentence, source_type="manual")
        self.repositories.add_user_sentences(telegram_user_id, [sentence_id], source_type="manual")
        self._ensure_default_category(telegram_user_id)
        self.repositories.add_sentences_to_category(telegram_user_id, category_key, [sentence_id], source_type="manual")

    def add_sentence_from_target_text(
        self,
        telegram_user_id: int,
        *,
        target_language: str,
        target_text: str,
        translation_text: str,
        english_text: str | None = None,
        level: str = "custom",
        category: str = "custom",
        library_category_key: str | None = None,
    ) -> Sentence:
        target_text = target_text.strip()
        translation_text = translation_text.strip()
        if not target_text:
            raise ValidationError("Target sentence text is required.")
        if not translation_text:
            raise ValidationError("Translation text is required.")
        existing = self.repositories.find_telegram_sentence_by_text(telegram_user_id, target_language, target_text)
        target_field = self.target_language_field(target_language)
        payload: dict[str, str] = {
            "persian": existing.persian if existing else "",
            "english": existing.english if existing else "",
            "french": existing.french if existing else "",
        }
        payload[target_field] = target_text
        if target_language == "fa":
            payload["english"] = translation_text
            if english_text:
                payload["french"] = english_text.strip()
        else:
            payload["persian"] = translation_text
            if target_language == "fr" and english_text:
                payload["english"] = english_text.strip()
        sentence = Sentence(
            id=existing.id if existing else self._next_sentence_id(),
            persian=payload["persian"] or (existing.persian if existing else ""),
            english=payload["english"] or (existing.english if existing else ""),
            french=payload["french"] or (existing.french if existing else ""),
            level=existing.level if existing else level,
            category=existing.category if existing else category,
            recommended_start=existing.recommended_start if existing else "telegram",
            enabled=True,
            tags=existing.tags if existing else ["telegram", "custom"],
            notes=existing.notes if existing else "Created from Telegram bot.",
            priority=existing.priority if existing else 0,
            difficulty=existing.difficulty if existing else 0,
            voice_hint=existing.voice_hint if existing else "",
            pronunciation_note=existing.pronunciation_note if existing else "",
        )
        self.repositories.upsert_telegram_sentence(telegram_user_id, sentence, source_type="manual_text")
        self.repositories.add_user_sentences(telegram_user_id, [sentence.id], source_type="manual_text")
        resolved_category_key = library_category_key or self.selected_library_category(telegram_user_id)
        if resolved_category_key == ALL_SENTENCES_CATEGORY_KEY:
            resolved_category_key = DEFAULT_LIBRARY_CATEGORY_KEY
        self._ensure_default_category(telegram_user_id, target_language)
        self.repositories.add_sentences_to_category(telegram_user_id, resolved_category_key, [sentence.id], source_type="manual_text")
        if existing is None:
            self._persist_sentences([sentence])
        return sentence

    def update_sentence_for_user(self, telegram_user_id: int, sentence_id: str, **fields: Any) -> Sentence:
        current = self.repositories.get_telegram_sentence(telegram_user_id, sentence_id)
        if current is None:
            raise ValidationError(f"Sentence {sentence_id} was not found in your library.")
        updated = Sentence(
            id=current.id,
            persian=str(fields.get("persian", current.persian)).strip(),
            english=str(fields.get("english", current.english)).strip(),
            french=str(fields.get("french", current.french)).strip(),
            level=str(fields.get("level", current.level)).strip(),
            category=str(fields.get("category", current.category)).strip(),
            recommended_start=str(fields.get("recommended_start", current.recommended_start)).strip(),
            enabled=bool(fields.get("enabled", current.enabled)),
            tags=list(fields.get("tags", current.tags)),
            notes=str(fields.get("notes", current.notes)),
            priority=int(fields.get("priority", current.priority)),
            difficulty=int(fields.get("difficulty", current.difficulty)),
            voice_hint=str(fields.get("voice_hint", current.voice_hint)),
            pronunciation_note=str(fields.get("pronunciation_note", current.pronunciation_note)),
        )
        self.repositories.upsert_telegram_sentence(telegram_user_id, updated, source_type="manual_edit")
        return updated

    def remove_sentence_from_user(
        self,
        telegram_user_id: int,
        sentence_id: str,
        category_key: str = ALL_SENTENCES_CATEGORY_KEY,
    ) -> None:
        if category_key == ALL_SENTENCES_CATEGORY_KEY:
            self.repositories.remove_user_sentence(telegram_user_id, sentence_id)
            for category in self.repositories.list_telegram_library_categories(telegram_user_id):
                self.repositories.remove_sentence_from_category(telegram_user_id, category.category_key, sentence_id)
            return
        self.repositories.remove_sentence_from_category(telegram_user_id, category_key, sentence_id)

    def generate_sentence_audio_for_user(
        self,
        telegram_user_id: int,
        sentence_id: str,
        *,
        library_category_key: str = ALL_SENTENCES_CATEGORY_KEY,
        recipe_name: str | None = None,
        provider_name: str | None = None,
        output_format: str | None = None,
    ) -> dict[str, Any]:
        job_id = f"tg-{telegram_user_id}-{sentence_id}"
        with self.logger.trace(
            "telegram.generate_sentence_audio_for_user",
            component="telegram.service",
            job_id=job_id,
            metadata={
                "telegram_user_id": telegram_user_id,
                "sentence_id": sentence_id,
                "library_category_key": library_category_key,
                "recipe_name": recipe_name,
                "provider_name": provider_name,
                "output_format": output_format,
            },
        ) as trace:
            settings = self.get_settings(telegram_user_id)
            sentence = next((item for item in self.list_user_sentences(telegram_user_id, category_key=library_category_key) if item.id == sentence_id), None)
            if sentence is None:
                raise ValidationError(f"Sentence {sentence_id} is not in the user's list.")
            output_dir = self.config.telegram_temp_audio_dir / str(telegram_user_id)
            output_dir.mkdir(parents=True, exist_ok=True)
            resolved_recipe_name = recipe_name or settings.selected_recipe
            resolved_provider_name = provider_name or settings.selected_provider
            resolved_output_format = output_format or settings.output_format
            with trace.span("telegram.resolve_recipe", component="telegram.service", payload={"recipe_name": resolved_recipe_name}) as span:
                recipe_payload = self.resolve_recipe_for_user(telegram_user_id, resolved_recipe_name)
                span.set_result(recipe_name=recipe_payload["recipe_name"], summary=recipe_payload["summary"])
            with trace.span("telegram.write_single_sentence_csv", component="telegram.service", payload={"sentence_id": sentence.id}) as span:
                sentence_csv = self._write_single_sentence_csv(sentence)
                span.set_result(csv_path=str(sentence_csv))
            result = self.runner.generate_sentence_files(
                job_id=job_id,
                csv_path=sentence_csv,
                recipe_name=recipe_payload["recipe_name"],
                output_dir=output_dir,
                output_format=resolved_output_format,
                provider_name=resolved_provider_name,
            )
            file_entry = result["files"][0]
            target_language = self.get_target_language(telegram_user_id)
            payload = {
                "audio_path": Path(str(file_entry["output"])),
                "manifest_path": Path(str(file_entry["manifest"])),
                "caption": self.build_caption(sentence, target_language=target_language),
                "sentence": sentence,
                "recipe_name": recipe_payload["recipe_name"],
                "recipe_summary": recipe_payload["summary"],
            }
            if library_category_key != ALL_SENTENCES_CATEGORY_KEY:
                self.repositories.record_category_activity(
                    telegram_user_id,
                    library_category_key,
                    recipe_name=payload["recipe_name"],
                    action="generate_sentence",
                    target_language=target_language,
                    sentence_id=sentence.id,
                )
            trace.set_summary(
                telegram_user_id=telegram_user_id,
                sentence_id=sentence_id,
                audio_path=str(payload["audio_path"]),
                manifest_path=str(payload["manifest_path"]),
                recipe_name=payload["recipe_name"],
                library_category_key=library_category_key,
            )
            return payload

    def build_caption(self, sentence: Sentence, target_language: str = "fr") -> str:
        target_label = self.target_language_label(target_language)
        target_text = self.target_text(sentence, target_language) or "-"
        lines = [
            f"{self.target_language_emoji(target_language)} {target_label}: {target_text}",
            f"🇮🇷 فارسی: {sentence.persian or '-'}",
        ]
        if target_language != "en":
            lines.append(f"🇬🇧 English: {sentence.english or '-'}")
        if target_language != "fr":
            lines.append(f"🇫🇷 Français: {sentence.french or '-'}")
        return "\n".join(lines)

    def available_recipes(self, telegram_user_id: int) -> list[RecipeDescriptor]:
        descriptors = [
            RecipeDescriptor(
                key=name,
                display_name=name,
                origin="shared",
                recipe_name=name,
                summary=str(recipe.get("description", "")),
                kind="shared",
                editable=False,
            )
            for name, recipe in sorted((self.config.recipes.get("recipes") or {}).items())
        ]
        descriptors.append(
            RecipeDescriptor(
                key="telegram_custom_ladder",
                display_name="telegram_custom_ladder",
                origin="shared",
                recipe_name="telegram_custom_ladder",
                summary=self.describe_custom_recipe(telegram_user_id)["summary"],
                kind="custom_shared",
                editable=True,
            )
        )
        for user_recipe in self.repositories.list_telegram_user_recipes(telegram_user_id):
            payload = user_recipe.recipe_data()
            descriptors.append(
                RecipeDescriptor(
                    key=user_recipe.recipe_key,
                    display_name=user_recipe.display_name,
                    origin="user",
                    recipe_name=user_recipe.recipe_key,
                    summary=self._guided_recipe_summary(payload, self.target_language_label(self.get_target_language(telegram_user_id))),
                    kind=user_recipe.template_key,
                    editable=True,
                )
            )
        return descriptors

    def available_recipe_templates(self) -> list[dict[str, str]]:
        return [{"key": key, **value} for key, value in GUIDED_RECIPE_TEMPLATES.items()]

    def list_user_recipe_descriptors(self, telegram_user_id: int) -> list[RecipeDescriptor]:
        return [recipe for recipe in self.available_recipes(telegram_user_id) if recipe.origin == "user"]

    def available_tts_providers(self) -> list[dict[str, Any]]:
        return self.runner.list_providers("tts")

    def available_output_formats(self) -> list[str]:
        return ["wav", "mp3"]

    def available_target_languages(self) -> list[dict[str, str]]:
        return [{"code": code, **payload} for code, payload in TARGET_LANGUAGES.items()]

    def get_target_language(self, telegram_user_id: int) -> str:
        settings = self.get_settings(telegram_user_id)
        code = str(settings.extra_config().get("target_language", "fr"))
        return code if code in TARGET_LANGUAGES else "fr"

    def set_target_language(self, telegram_user_id: int, target_language: str) -> TelegramUserSettings:
        if target_language not in TARGET_LANGUAGES:
            raise ValidationError(f"Unsupported target language: {target_language}")
        settings = self.get_settings(telegram_user_id)
        extra = settings.extra_config()
        extra["target_language"] = target_language
        return self.update_settings(telegram_user_id, extra_config=extra)

    def latest_import_summary(self, telegram_user_id: int) -> dict[str, Any] | None:
        record = self.repositories.latest_telegram_csv_import(telegram_user_id)
        if record is None:
            return None
        return {
            "file_name": record.file_name,
            "file_path": record.file_path,
            "imported_rows": record.imported_rows,
            "imported_sentence_ids": record.imported_sentence_ids,
            "library_category_key": record.library_category_key,
            "created_at": record.created_at,
        }

    def paginated_user_sentences(
        self,
        telegram_user_id: int,
        page: int,
        page_size: int | None = None,
        *,
        category_key: str = ALL_SENTENCES_CATEGORY_KEY,
    ) -> dict[str, Any]:
        settings = self.get_settings(telegram_user_id)
        configured_page_size = int(settings.extra_config().get("page_size", page_size or 8))
        page_size_value = max(1, min(20, configured_page_size))
        sentences = self.list_user_sentences(telegram_user_id, category_key=category_key)
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
            "category_key": category_key,
        }

    def sentence_summary(self, telegram_user_id: int, category_key: str = ALL_SENTENCES_CATEGORY_KEY) -> dict[str, Any]:
        sentences = self.list_user_sentences(telegram_user_id, category_key=category_key)
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

    def library_category_summary(self, telegram_user_id: int, category_key: str) -> dict[str, Any]:
        descriptor = self.describe_library_category(telegram_user_id, category_key)
        sentences = self.list_user_sentences(telegram_user_id, category_key=category_key)
        levels = Counter(sentence.level for sentence in sentences)
        content_categories = Counter(sentence.category for sentence in sentences)
        recipe_usage = (
            {}
            if category_key == ALL_SENTENCES_CATEGORY_KEY
            else self.repositories.list_category_activity_counts(telegram_user_id, category_key, group_by="recipe_name")
        )
        language_counts = {
            "persian_non_empty": sum(1 for sentence in sentences if sentence.persian.strip()),
            "english_non_empty": sum(1 for sentence in sentences if sentence.english.strip()),
            "french_non_empty": sum(1 for sentence in sentences if sentence.french.strip()),
        }
        return {
            "key": descriptor.key,
            "display_name": descriptor.display_name,
            "target_language": descriptor.target_language,
            "description": descriptor.description,
            "sentence_count": descriptor.sentence_count,
            "is_virtual": descriptor.is_virtual,
            "levels": dict(sorted(levels.items())),
            "content_categories": dict(sorted(content_categories.items())),
            "recipe_usage": dict(sorted(recipe_usage.items())),
            "language_counts": language_counts,
            "difficulty_counts": self._counter_dict(Counter(str(sentence.difficulty) for sentence in sentences)),
            "priority_counts": self._counter_dict(Counter(str(sentence.priority) for sentence in sentences)),
        }

    def export_category_csv(self, telegram_user_id: int, category_key: str) -> Path:
        return self.export_user_csv(telegram_user_id, category_key)

    def generate_all_sentence_audio_for_category(
        self,
        telegram_user_id: int,
        category_key: str,
    ) -> list[dict[str, Any]]:
        sentences = self.list_user_sentences(telegram_user_id, category_key=category_key)
        if not sentences:
            return []
        target_language = self.get_target_language(telegram_user_id)
        payloads: list[dict[str, Any]] = []
        for sentence in sentences:
            payload = self.generate_sentence_audio_for_user(
                telegram_user_id,
                sentence.id,
                library_category_key=category_key,
            )
            payloads.append(payload)
        if category_key != ALL_SENTENCES_CATEGORY_KEY and payloads:
            self.repositories.record_category_activity(
                telegram_user_id,
                category_key,
                recipe_name=payloads[0]["recipe_name"],
                action="generate_all",
                target_language=target_language,
            )
        return payloads

    def guided_recipe_defaults(self, telegram_user_id: int, template_key: str = "ladder") -> dict[str, Any]:
        target_language = self.get_target_language(telegram_user_id)
        voices = self._edge_voice_defaults()
        target_voice = {
            "fr": voices["fr_male"],
            "en": voices["en_male"],
            "fa": voices["fa_male"],
        }.get(target_language, voices["fr_male"])
        payload = {
            "name": "",
            "template_key": template_key,
            "provider": "edge",
            "output_format": "wav",
            "prompt_field": "persian",
            "prompt_voice": voices["fa_female"],
            "target_voice": target_voice,
            "slow_rate": "-12%",
            "normal_rate": "+0%",
            "final_rate": "+0%",
            "pause_between_ms": 1200,
            "word_pause_ms": 250,
            "include_word_by_word": True,
            "include_slow_pass": True,
            "closing_repeat": True,
        }
        if template_key == "listen_repeat":
            payload["include_word_by_word"] = False
            payload["include_slow_pass"] = False
            payload["pause_between_ms"] = 900
        return payload

    def normalize_guided_recipe_payload(self, telegram_user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        defaults = self.guided_recipe_defaults(telegram_user_id, str(payload.get("template_key") or "ladder"))
        merged = dict(defaults)
        merged.update(payload)
        merged["name"] = str(merged.get("name") or "").strip()
        if not merged["name"]:
            raise ValidationError("Recipe name is required.")
        merged["template_key"] = str(merged.get("template_key") or "ladder")
        if merged["template_key"] not in GUIDED_RECIPE_TEMPLATES:
            raise ValidationError(f"Unsupported template: {merged['template_key']}")
        merged["provider"] = "edge"
        merged["output_format"] = str(merged.get("output_format") or "wav").lower()
        merged["prompt_field"] = str(merged.get("prompt_field") or "persian")
        if merged["prompt_field"] not in {"persian", "english", "none"}:
            raise ValidationError("Prompt field must be persian, english, or none.")
        merged["prompt_voice"] = str(merged.get("prompt_voice") or defaults["prompt_voice"])
        merged["target_voice"] = str(merged.get("target_voice") or defaults["target_voice"])
        merged["slow_rate"] = str(merged.get("slow_rate") or defaults["slow_rate"])
        merged["normal_rate"] = str(merged.get("normal_rate") or defaults["normal_rate"])
        merged["final_rate"] = str(merged.get("final_rate") or defaults["final_rate"])
        merged["pause_between_ms"] = max(150, int(merged.get("pause_between_ms") or defaults["pause_between_ms"]))
        merged["word_pause_ms"] = max(100, int(merged.get("word_pause_ms") or defaults["word_pause_ms"]))
        merged["include_word_by_word"] = bool(merged.get("include_word_by_word", defaults["include_word_by_word"]))
        merged["include_slow_pass"] = bool(merged.get("include_slow_pass", defaults["include_slow_pass"]))
        merged["closing_repeat"] = bool(merged.get("closing_repeat", defaults["closing_repeat"]))
        return merged

    def create_user_recipe(self, telegram_user_id: int, payload: dict[str, Any]) -> TelegramUserRecipe:
        normalized = self.normalize_guided_recipe_payload(telegram_user_id, payload)
        recipe_key = self._slugify_recipe_key(normalized["name"])
        if recipe_key == "telegram_custom_ladder":
            recipe_key = f"{recipe_key}_user"
        self.repositories.upsert_telegram_user_recipe(
            telegram_user_id=telegram_user_id,
            recipe_key=recipe_key,
            display_name=str(normalized["name"]),
            recipe_kind="guided",
            template_key=str(normalized["template_key"]),
            recipe_data=normalized,
        )
        self.update_settings(telegram_user_id, selected_recipe=recipe_key)
        record = self.repositories.get_telegram_user_recipe(telegram_user_id, recipe_key)
        if record is None:
            raise ValidationError("Recipe could not be saved.")
        return record

    def update_user_recipe(self, telegram_user_id: int, recipe_key: str, updates: dict[str, Any]) -> TelegramUserRecipe:
        record = self.repositories.get_telegram_user_recipe(telegram_user_id, recipe_key)
        if record is None:
            raise ValidationError(f"Unknown user recipe: {recipe_key}")
        payload = record.recipe_data()
        payload.update(updates)
        normalized = self.normalize_guided_recipe_payload(telegram_user_id, payload)
        self.repositories.upsert_telegram_user_recipe(
            telegram_user_id=telegram_user_id,
            recipe_key=recipe_key,
            display_name=str(normalized["name"]),
            recipe_kind=record.recipe_kind,
            template_key=str(normalized["template_key"]),
            recipe_data=normalized,
        )
        updated = self.repositories.get_telegram_user_recipe(telegram_user_id, recipe_key)
        if updated is None:
            raise ValidationError(f"Unknown user recipe: {recipe_key}")
        return updated

    def delete_user_recipe(self, telegram_user_id: int, recipe_key: str) -> None:
        self.repositories.delete_telegram_user_recipe(telegram_user_id, recipe_key)
        settings = self.get_settings(telegram_user_id)
        if settings.selected_recipe == recipe_key:
            self.update_settings(telegram_user_id, selected_recipe="telegram_custom_ladder")

    def get_user_recipe(self, telegram_user_id: int, recipe_key: str) -> TelegramUserRecipe | None:
        return self.repositories.get_telegram_user_recipe(telegram_user_id, recipe_key)

    def describe_user_recipe(self, telegram_user_id: int, recipe_key: str) -> dict[str, Any]:
        record = self.get_user_recipe(telegram_user_id, recipe_key)
        if record is None:
            raise ValidationError(f"Unknown user recipe: {recipe_key}")
        payload = self.normalize_guided_recipe_payload(telegram_user_id, record.recipe_data())
        return {
            "recipe_key": record.recipe_key,
            "display_name": record.display_name,
            "template_key": record.template_key,
            "payload": payload,
            "summary": self._guided_recipe_summary(payload, self.target_language_label(self.get_target_language(telegram_user_id))),
        }

    def guided_recipe_summary(self, telegram_user_id: int, payload: dict[str, Any]) -> str:
        normalized = self.normalize_guided_recipe_payload(telegram_user_id, payload)
        return self._guided_recipe_summary(normalized, self.target_language_label(self.get_target_language(telegram_user_id)))

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

    def create_or_update_recipe_override(self, telegram_user_id: int, recipe_name: str, updates: dict[str, Any]) -> dict[str, Any]:
        settings = self.get_settings(telegram_user_id)
        extra = settings.extra_config()
        overrides = dict(extra.get("recipe_overrides", {}))
        current = dict(overrides.get(recipe_name, {}))
        current.update(updates)
        current["silence_scale"] = max(0.15, min(1.0, float(current.get("silence_scale", 0.6))))
        overrides[recipe_name] = current
        extra["recipe_overrides"] = overrides
        self.update_settings(telegram_user_id, extra_config=extra)
        return current

    def describe_recipe_override(self, telegram_user_id: int, recipe_name: str) -> dict[str, Any]:
        settings = self.get_settings(telegram_user_id)
        overrides = settings.extra_config().get("recipe_overrides", {})
        current = dict(overrides.get(recipe_name, {}))
        current["silence_scale"] = max(0.15, min(1.0, float(current.get("silence_scale", 0.6))))
        return current

    def describe_custom_recipe(self, telegram_user_id: int) -> dict[str, Any]:
        settings = self.get_settings(telegram_user_id)
        custom = self._normalized_custom_recipe_config(settings.extra_config().get("custom_recipe", {}))
        target_label = self.target_language_label(self.get_target_language(telegram_user_id))
        return {
            **custom,
            "summary": self._custom_recipe_summary(custom, target_label),
        }

    def resolve_recipe_for_user(self, telegram_user_id: int, recipe_name: str) -> dict[str, Any]:
        target_language = self.get_target_language(telegram_user_id)
        user_recipe = self.get_user_recipe(telegram_user_id, recipe_name)
        if user_recipe is not None:
            payload = self.normalize_guided_recipe_payload(telegram_user_id, user_recipe.recipe_data())
            recipe = self._build_guided_user_recipe(payload, target_language=target_language)
            runtime_name = f"{recipe_name}_{target_language}_user"
            self._register_runtime_recipe(runtime_name, recipe)
            return {
                "recipe_name": runtime_name,
                "recipe": recipe,
                "summary": self._guided_recipe_summary(payload, self.target_language_label(target_language)),
            }
        if recipe_name == "telegram_custom_ladder":
            custom = self.describe_custom_recipe(telegram_user_id)
            recipe = self._build_custom_recipe(custom, target_language=target_language)
            runtime_name = f"telegram_custom_ladder_{target_language}"
            self._register_runtime_recipe(runtime_name, recipe)
            return {"recipe_name": runtime_name, "recipe": recipe, "summary": custom["summary"]}
        recipe = get_recipe(self.config.recipes, recipe_name)
        adapted_recipe = self._build_runtime_recipe_for_target(recipe_name, recipe, telegram_user_id, target_language)
        runtime_name = f"{recipe_name}_{target_language}_tg"
        self._register_runtime_recipe(runtime_name, adapted_recipe)
        return {"recipe_name": runtime_name, "recipe": adapted_recipe, "summary": adapted_recipe.description}

    def recipe_prompt_presets(self) -> list[dict[str, str]]:
        return [
            {"key": "persian", "label": "🇮🇷 فارسی", "value": "persian"},
            {"key": "english", "label": "🇬🇧 انگلیسی", "value": "english"},
            {"key": "none", "label": "🚫 بدون مقدمه", "value": "none"},
        ]

    def target_language_field(self, target_language: str) -> str:
        return TARGET_LANGUAGES.get(target_language, TARGET_LANGUAGES["fr"])["field"]

    def target_language_label(self, target_language: str) -> str:
        return TARGET_LANGUAGES.get(target_language, TARGET_LANGUAGES["fr"])["label"]

    def target_language_emoji(self, target_language: str) -> str:
        return TARGET_LANGUAGES.get(target_language, TARGET_LANGUAGES["fr"])["emoji"]

    def target_text(self, sentence: Sentence, target_language: str) -> str:
        return str(getattr(sentence, self.target_language_field(target_language), "") or "").strip()

    def _persist_sentences(self, sentences: list[Sentence]) -> None:
        self.sentence_repository.upsert_many(sentences)

    def _load_all_sentences(self) -> list[Sentence]:
        return self.sentence_repository.list_all()

    def _sentence_by_id(self, sentence_id: str) -> Sentence | None:
        return next((sentence for sentence in self._load_all_sentences() if sentence.id == sentence_id), None)

    def _next_sentence_id(self) -> str:
        numeric_ids = []
        for sentence in self._load_all_sentences():
            if sentence.id.isdigit():
                numeric_ids.append(int(sentence.id))
        return str((max(numeric_ids) if numeric_ids else 0) + 1)

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

    def _build_runtime_recipe_for_target(
        self,
        recipe_name: str,
        recipe: Recipe,
        telegram_user_id: int,
        target_language: str,
    ) -> Recipe:
        silence_scale = self.describe_recipe_override(telegram_user_id, recipe_name)["silence_scale"]
        target_field = self.target_language_field(target_language)
        target_voice = self._default_voice_for_language(target_language)
        segments: list[RecipeSegment] = []
        for segment in recipe.segments:
            if segment.kind == "silence":
                segments.append(
                    RecipeSegment(
                        kind="silence",
                        duration_ms=max(150, int((segment.duration_ms or 0) * silence_scale)),
                    )
                )
                continue
            text_field = segment.text_field
            language = segment.language
            voice = segment.voice
            if text_field in {"french", "target"}:
                text_field = target_field
                language = target_language
                if segment.voice:
                    voice = target_voice
            segments.append(
                RecipeSegment(
                    kind="tts",
                    text_field=text_field,
                    language=language,
                    voice=voice,
                    provider=segment.provider,
                    duration_ms=segment.duration_ms,
                    pause_after_ms=max(120, int(segment.pause_after_ms * silence_scale)) if segment.pause_after_ms else None,
                    repeat=segment.repeat,
                    split_words=segment.split_words,
                    word_pause_ms=max(120, int(segment.word_pause_ms * silence_scale)) if segment.word_pause_ms else None,
                    delimiter_pattern=segment.delimiter_pattern,
                    rate=segment.rate,
                    pitch=segment.pitch,
                    volume=segment.volume,
                )
            )
        return Recipe(
            name=recipe.name,
            description=f"{recipe.description} Target language: {self.target_language_label(target_language)}.",
            output_format=recipe.output_format,
            provider_policy=recipe.provider_policy,
            segments=segments,
        )

    def _build_custom_recipe(self, custom: dict[str, Any], *, target_language: str) -> Recipe:
        provider_policy = {
            "tts": {
                "strategy": "explicit",
                "explicit_provider": str(custom["provider"]),
                "default_provider": str(custom["provider"]),
                "allow_fallback_on_error": False,
            }
        }
        target_field = self.target_language_field(target_language)
        target_label = self.target_language_label(target_language)
        prompt_field = str(custom["prompt_field"])
        pause_between = int(custom["pause_between_ms"])
        segments: list[dict[str, Any]] = []
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
                    "text_field": target_field,
                    "language": target_language,
                    "voice": self._default_voice_for_language(target_language, preferred_voice=str(custom["normal_voice"])),
                    "rate": str(custom["normal_rate"]),
                },
                {"kind": "silence", "duration_ms": pause_between},
                {
                    "kind": "tts",
                    "text_field": target_field,
                    "language": target_language,
                    "voice": self._default_voice_for_language(
                        target_language,
                        preferred_voice=str(custom["word_by_word_voice"]),
                    ),
                    "split_words": True,
                    "word_pause_ms": int(custom["word_pause_ms"]),
                },
                {"kind": "silence", "duration_ms": pause_between},
                {
                    "kind": "tts",
                    "text_field": target_field,
                    "language": target_language,
                    "voice": self._default_voice_for_language(target_language, preferred_voice=str(custom["slow_voice"])),
                    "rate": str(custom["slow_rate"]),
                },
                {"kind": "silence", "duration_ms": pause_between},
                {
                    "kind": "tts",
                    "text_field": target_field,
                    "language": target_language,
                    "voice": self._default_voice_for_language(target_language, preferred_voice=str(custom["final_voice"])),
                    "rate": str(custom["final_rate"]),
                },
            ]
        )
        recipe_data = {
            "description": self._custom_recipe_summary(custom, target_label),
            "output_format": str(custom["output_format"]),
            "provider_policy": provider_policy,
            "segments": segments,
        }
        return get_recipe({"recipes": {"telegram_custom_ladder": recipe_data}}, "telegram_custom_ladder")

    def _build_guided_user_recipe(self, payload: dict[str, Any], *, target_language: str) -> Recipe:
        provider_policy = {
            "tts": {
                "strategy": "explicit",
                "explicit_provider": str(payload["provider"]),
                "default_provider": str(payload["provider"]),
                "allow_fallback_on_error": False,
            }
        }
        target_field = self.target_language_field(target_language)
        target_label = self.target_language_label(target_language)
        pause_between = int(payload["pause_between_ms"])
        segments: list[dict[str, Any]] = []
        prompt_field = str(payload["prompt_field"])
        if prompt_field != "none":
            segments.append(
                {
                    "kind": "tts",
                    "text_field": prompt_field,
                    "language": "fa" if prompt_field == "persian" else "en",
                    "voice": str(payload["prompt_voice"]),
                    "rate": str(payload["normal_rate"]),
                }
            )
            segments.append({"kind": "silence", "duration_ms": pause_between})
        segments.append(
            {
                "kind": "tts",
                "text_field": target_field,
                "language": target_language,
                "voice": str(payload["target_voice"]),
                "rate": str(payload["normal_rate"]),
            }
        )
        if bool(payload["include_word_by_word"]):
            segments.append({"kind": "silence", "duration_ms": pause_between})
            segments.append(
                {
                    "kind": "tts",
                    "text_field": target_field,
                    "language": target_language,
                    "voice": str(payload["target_voice"]),
                    "split_words": True,
                    "word_pause_ms": int(payload["word_pause_ms"]),
                }
            )
        if bool(payload["include_slow_pass"]):
            segments.append({"kind": "silence", "duration_ms": pause_between})
            segments.append(
                {
                    "kind": "tts",
                    "text_field": target_field,
                    "language": target_language,
                    "voice": str(payload["target_voice"]),
                    "rate": str(payload["slow_rate"]),
                }
            )
        if bool(payload["closing_repeat"]):
            segments.append({"kind": "silence", "duration_ms": pause_between})
            segments.append(
                {
                    "kind": "tts",
                    "text_field": target_field,
                    "language": target_language,
                    "voice": str(payload["target_voice"]),
                    "rate": str(payload["final_rate"]),
                }
            )
        recipe_data = {
            "description": self._guided_recipe_summary(payload, target_label),
            "output_format": str(payload["output_format"]),
            "provider_policy": provider_policy,
            "segments": segments,
        }
        recipe_name = self._slugify_recipe_key(str(payload["name"]) or "guided_recipe")
        return get_recipe({"recipes": {recipe_name: recipe_data}}, recipe_name)

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
            "pause_between_ms": int(value.get("pause_between_ms") or 1500),
            "word_pause_ms": int(value.get("word_pause_ms") or 350),
            "normal_rate": str(value.get("normal_rate") or "+0%"),
            "slow_rate": str(value.get("slow_rate") or "-15%"),
            "final_rate": str(value.get("final_rate") or "+0%"),
        }

    def _custom_recipe_summary(self, custom: dict[str, Any], target_label: str) -> str:
        prompt = {
            "persian": "Persian prompt",
            "english": "English prompt",
            "none": "No prompt",
        }.get(str(custom["prompt_field"]), "Custom prompt")
        return (
            f"{prompt}, {target_label} normal, word-by-word, slow, final replay. "
            f"Pause {custom['pause_between_ms']}ms, word pause {custom['word_pause_ms']}ms."
        )

    def _guided_recipe_summary(self, payload: dict[str, Any], target_label: str) -> str:
        stages: list[str] = []
        prompt_field = str(payload["prompt_field"])
        if prompt_field != "none":
            stages.append("prompt")
        stages.append(f"{target_label} normal")
        if bool(payload.get("include_word_by_word", False)):
            stages.append("word-by-word")
        if bool(payload.get("include_slow_pass", False)):
            stages.append("slow pass")
        if bool(payload.get("closing_repeat", False)):
            stages.append("final replay")
        return (
            f"{str(payload['name'])}: " + " -> ".join(stages) +
            f". Pause {payload['pause_between_ms']}ms, word pause {payload['word_pause_ms']}ms."
        )

    def _resolve_import_category(
        self,
        telegram_user_id: int,
        *,
        library_category_key: str | None,
        new_category_name: str | None,
    ) -> str:
        if new_category_name and new_category_name.strip():
            return self.create_library_category(
                telegram_user_id,
                new_category_name,
                target_language=self.get_target_language(telegram_user_id),
            ).key
        if library_category_key:
            if library_category_key == ALL_SENTENCES_CATEGORY_KEY:
                return DEFAULT_LIBRARY_CATEGORY_KEY
            category = self.repositories.get_telegram_library_category(telegram_user_id, library_category_key)
            if category is None:
                raise ValidationError(f"Unknown library category: {library_category_key}")
            return library_category_key
        self._ensure_default_category(telegram_user_id)
        return DEFAULT_LIBRARY_CATEGORY_KEY

    def _slugify_category_key(self, value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        return cleaned or "category"

    def _counter_dict(self, counter: Counter[str]) -> dict[str, int]:
        return dict(sorted((key, int(value)) for key, value in counter.items() if key))

    def _slugify_recipe_key(self, value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        return cleaned or "user_recipe"

    def _default_voice_for_language(self, language: str, preferred_voice: str | None = None) -> str:
        if preferred_voice and preferred_voice.strip():
            return preferred_voice
        edge = (self.config.providers.get("tts") or {}).get("edge", {})
        voices = edge.get("voices", {})
        candidates = [language, f"{language}_male", f"{language}_female"]
        for candidate in candidates:
            if candidate in voices:
                return str(voices[candidate])
        return str(edge.get("default_voice", "fr-FR-DeniseNeural"))

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
