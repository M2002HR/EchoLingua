from __future__ import annotations

import json
from pathlib import Path

from echolingua.audio.builder import AudioBuilder
from echolingua.core.config import AppConfig
from echolingua.core.errors import ProviderError, ValidationError
from echolingua.core.logging import JsonlLogger
from echolingua.pipeline.manifest import write_manifest
from echolingua.providers.registry import build_provider, build_registry, list_provider_configs
from echolingua.providers.selector import ProviderSelectionPolicy, ProviderSelector
from echolingua.recipes.loader import get_recipe
from echolingua.recipes.planner import AudioPlan, AudioPlanBuilder
from echolingua.sentences.loader import load_sentences, load_sentences_with_report
from echolingua.sentences.repository import SentenceRepository
from echolingua.sentences.validator import SentenceValidationReport
from echolingua.storage.db import Database
from echolingua.storage.repositories import CacheStatsSummary, StatsSummary, StorageRepositories


class PipelineRunner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db = Database(config.db_path)
        self.db_preexisting = self.db.exists()
        self.db.initialize()
        self.repositories = StorageRepositories(self.db)
        self.logger = JsonlLogger(config.log_dir)

    def validate_csv(self, csv_path: Path) -> SentenceValidationReport:
        _sentences, report = load_sentences_with_report(csv_path)
        return report

    def build_plan(
        self,
        job_id: str,
        csv_path: Path,
        recipe_name: str,
        from_sentence_id: str | None = None,
        to_sentence_id: str | None = None,
    ) -> AudioPlan:
        sentences = self._load_filtered_sentences(csv_path, from_sentence_id, to_sentence_id)
        SentenceRepository(self.db).upsert_many(sentences)
        recipe = get_recipe(self.config.recipes, recipe_name)
        return AudioPlanBuilder().build(
            job_id,
            recipe,
            sentences,
            source_csv_path=str(csv_path),
            target_language="fr",
            target_column="french",
        )

    def build_plan_summary(
        self,
        job_id: str,
        csv_path: Path,
        recipe_name: str,
        from_sentence_id: str | None = None,
        to_sentence_id: str | None = None,
    ) -> dict[str, object]:
        plan = self.build_plan(job_id, csv_path, recipe_name, from_sentence_id, to_sentence_id)
        policy = self._provider_policy()
        providers = [provider.metadata.name for provider in self._selector().ordered()]
        tts_segments = sum(1 for segment in plan.segments if segment.kind == "tts")
        silence_segments = sum(1 for segment in plan.segments if segment.kind == "silence")
        sentence_ids = list({segment.sentence_id for segment in plan.segments})
        return {
            "job_id": plan.job_id,
            "recipe": plan.recipe_name,
            "target_language": plan.target_language,
            "target_column": plan.target_column,
            "sentence_count": len(sentence_ids),
            "segment_count": len(plan.segments),
            "tts_segment_count": tts_segments,
            "silence_segment_count": silence_segments,
            "provider_policy": {
                "strategy": policy.strategy,
                "explicit_provider": policy.explicit_provider,
                "allow_fallback_on_error": policy.allow_fallback_on_error,
            },
            "selected_providers": providers,
            "estimated_calls": tts_segments,
            "fields_used": sorted({segment.text_field for segment in plan.segments if segment.text_field}),
            "output_format": plan.output_format,
        }

    def list_providers(self, kind: str = "tts") -> list[dict[str, object]]:
        return list_provider_configs(self.config.providers, kind)

    def test_provider(self, name: str, text: str = "Bonjour") -> dict[str, object]:
        try:
            provider = build_provider(self.config.providers, "tts", name)
        except KeyError as exc:
            raise ProviderError(f"Provider is not configured: {name}") from exc
        output = self.config.output_dir / "provider_tests" / f"{name}.wav"
        voice = str(provider.metadata.config.get("default_voice", "fake-neutral")) if provider.metadata.config else "fake-neutral"
        from echolingua.providers.tts.base import TTSRequest

        result = provider.synthesize(TTSRequest(text=text, voice=voice, language="fr"), output)
        return {"provider": name, "path": str(result.path), "duration_ms": result.duration_ms}

    def stats(self) -> StatsSummary:
        return self.repositories.stats_summary()

    def cache_stats(self) -> CacheStatsSummary:
        return self.repositories.cache_stats_summary()

    def tail_logs(self, lines: int = 50) -> list[str]:
        log_path = self.config.log_dir / "events.jsonl"
        if not log_path.exists():
            return []
        with log_path.open("r", encoding="utf-8") as handle:
            entries = handle.readlines()
        return [line.rstrip("\n") for line in entries[-lines:]]

    def generate(
        self,
        job_id: str,
        csv_path: Path,
        recipe_name: str,
        output_path: Path | None = None,
        from_sentence_id: str | None = None,
        to_sentence_id: str | None = None,
    ) -> dict:
        plan = self.build_plan(job_id, csv_path, recipe_name, from_sentence_id, to_sentence_id)
        self.repositories.create_job(job_id, recipe_name)
        self.repositories.record_event(
            job_id,
            "plan_built",
            {"segment_count": len(plan.segments), "recipe_name": recipe_name, "plan": json.dumps(plan.to_dict(), ensure_ascii=False)},
        )
        self.logger.event("plan_built", job_id, recipe_name=recipe_name, segment_count=len(plan.segments))
        selector = self._selector()
        output = output_path or (self.config.output_dir / f"{job_id}_{recipe_name}.{plan.output_format}")
        output_format = output.suffix.lstrip(".") or plan.output_format
        builder = AudioBuilder(selector=selector, cache_dir=self.config.tts_cache_dir, repositories=self.repositories)
        try:
            output_info = builder.build(plan, output, output_format=output_format)
            manifest_path = output.with_suffix(output.suffix + ".manifest.json")
            manifest = write_manifest(plan, output_info, manifest_path)
            self.repositories.record_audio_output(job_id, output, manifest_path, output_info["duration_ms"])
            self.repositories.record_event(job_id, "audio_generated", {"output": str(output), "manifest": str(manifest_path)})
            self.repositories.complete_job(job_id)
            self.logger.event("audio_generated", job_id, output=str(output), manifest=str(manifest_path))
            return {"plan": plan, "output": output_info, "manifest_path": manifest_path, "manifest": manifest}
        except Exception as exc:
            self.repositories.record_event(job_id, "job_failed", {"error": str(exc)})
            self.repositories.fail_job(job_id, str(exc))
            self.logger.event("job_failed", job_id, error=str(exc))
            raise

    def _load_filtered_sentences(
        self,
        csv_path: Path,
        from_sentence_id: str | None,
        to_sentence_id: str | None,
    ) -> list:
        sentences = load_sentences(csv_path)
        if from_sentence_id is None and to_sentence_id is None:
            return sentences
        sentence_ids = [sentence.id for sentence in sentences]
        if from_sentence_id is not None and from_sentence_id not in sentence_ids:
            raise ValidationError(f"Unknown start sentence id: {from_sentence_id}")
        if to_sentence_id is not None and to_sentence_id not in sentence_ids:
            raise ValidationError(f"Unknown end sentence id: {to_sentence_id}")
        start_index = sentence_ids.index(from_sentence_id) if from_sentence_id is not None else 0
        end_index = sentence_ids.index(to_sentence_id) if to_sentence_id is not None else len(sentences) - 1
        if start_index > end_index:
            raise ValidationError("The --from sentence id must come before or match the --to sentence id.")
        filtered = sentences[start_index : end_index + 1]
        if not filtered:
            raise ValidationError("No enabled sentences matched the requested --from/--to range.")
        return filtered

    def _provider_policy(self) -> ProviderSelectionPolicy:
        return ProviderSelectionPolicy.from_config(self.config.default.get("provider_policy", {}).get("tts", {}))

    def _selector(self) -> ProviderSelector:
        registry = build_registry(self.config.providers)
        return ProviderSelector(registry.list("tts"), self._provider_policy())
