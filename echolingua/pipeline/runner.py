from __future__ import annotations

import json
from pathlib import Path

from echolingua.audio.builder import AudioBuilder
from echolingua.core.config import AppConfig
from echolingua.core.errors import ProviderError, ValidationError
from echolingua.core.logging import JsonlLogger
from echolingua.core.progress import JobProgress, NullProgressReporter, ProgressReporter
from echolingua.pipeline.manifest import write_manifest
from echolingua.providers.registry import build_provider, build_registry, list_provider_configs
from echolingua.providers.selector import ProviderSelectionPolicy, ProviderSelector
from echolingua.recipes.loader import get_recipe
from echolingua.recipes.planner import AudioPlan, AudioPlanBuilder
from echolingua.sentences.loader import load_sentences_with_report
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
        progress_reporter: ProgressReporter | None = None,
    ) -> dict:
        self.repositories.create_job(job_id, recipe_name)
        reporter = progress_reporter or NullProgressReporter()
        completed_steps = 0
        total_steps = 7
        start = JobProgress(stage="created", message="Job created", completed_steps=0, total_steps=total_steps)
        reporter.start(start)

        def emit_progress(
            stage: str,
            message: str,
            *,
            advance: int = 1,
            status: str = "running",
            total_override: int | None = None,
        ) -> JobProgress:
            nonlocal completed_steps, total_steps
            if total_override is not None:
                total_steps = total_override
            completed_steps = min(total_steps, completed_steps + advance)
            progress = JobProgress(
                stage=stage,
                message=message,
                completed_steps=completed_steps,
                total_steps=total_steps,
                status=status,
            )
            self.repositories.update_job_progress(job_id, stage, message, completed_steps, total_steps, status=status)
            self.repositories.record_event(job_id, "job_progress", progress.to_dict())
            self.logger.event("job_progress", job_id, **progress.to_dict())
            reporter.update(progress)
            return progress

        try:
            emit_progress("loading_csv", f"Loading {csv_path.name}")
            sentences, report = load_sentences_with_report(csv_path)
            emit_progress("validating", f"Validated {report.total_rows} rows")
            if not report.is_valid:
                if report.issues:
                    raise ValidationError(report.issues[0].message)
                raise ValidationError("CSV validation failed.")
            filtered = self._filter_sentences(sentences, from_sentence_id, to_sentence_id)
            SentenceRepository(self.db).upsert_many(filtered)
            recipe = get_recipe(self.config.recipes, recipe_name)
            plan = AudioPlanBuilder().build(
                job_id,
                recipe,
                filtered,
                source_csv_path=str(csv_path),
                target_language="fr",
                target_column="french",
            )
            emit_progress("building_plan", f"Built plan with {len(plan.segments)} segments", total_override=len(plan.segments) + 7)
            self.repositories.record_event(
                job_id,
                "plan_built",
                {"segment_count": len(plan.segments), "recipe_name": recipe_name, "plan": json.dumps(plan.to_dict(), ensure_ascii=False)},
            )
            self.logger.event("plan_built", job_id, recipe_name=recipe_name, segment_count=len(plan.segments))
            selector = self._selector()
            output = output_path or (self.config.output_dir / f"{job_id}_{recipe_name}.{plan.output_format}")
            output_format = output.suffix.lstrip(".") or plan.output_format
            builder = AudioBuilder(
                selector=selector,
                cache_dir=self.config.tts_cache_dir,
                repositories=self.repositories,
                progress_callback=lambda stage, message: emit_progress(stage, message),
            )
            output_info = builder.build(plan, output, output_format=output_format)
            emit_progress("saving_manifest", f"Writing manifest for {output.name}")
            manifest_path = output.with_suffix(output.suffix + ".manifest.json")
            manifest = write_manifest(plan, output_info, manifest_path)
            emit_progress("saving_records", f"Recording output metadata for {output.name}")
            self.repositories.record_audio_output(job_id, output, manifest_path, output_info["duration_ms"])
            self.repositories.record_event(job_id, "audio_generated", {"output": str(output), "manifest": str(manifest_path)})
            finished = emit_progress("finished", "Generation complete", status="completed")
            self.repositories.complete_job(job_id, total_steps=finished.total_steps)
            self.logger.event("audio_generated", job_id, output=str(output), manifest=str(manifest_path))
            reporter.stop(finished)
            return {"plan": plan, "output": output_info, "manifest_path": manifest_path, "manifest": manifest}
        except Exception as exc:
            self.repositories.record_event(job_id, "job_failed", {"error": str(exc)})
            self.repositories.fail_job(job_id, str(exc))
            self.logger.event("job_failed", job_id, error=str(exc))
            reporter.stop(
                JobProgress(
                    stage="failed",
                    message=str(exc),
                    completed_steps=completed_steps,
                    total_steps=total_steps,
                    status="failed",
                )
            )
            raise

    def generate_sentence_files(
        self,
        job_id: str,
        csv_path: Path,
        recipe_name: str,
        output_dir: Path,
        output_format: str = "wav",
        from_sentence_id: str | None = None,
        to_sentence_id: str | None = None,
        progress_reporter: ProgressReporter | None = None,
    ) -> dict[str, object]:
        self.repositories.create_job(job_id, recipe_name)
        reporter = progress_reporter or NullProgressReporter()
        output_dir.mkdir(parents=True, exist_ok=True)
        completed_steps = 0
        total_steps = 1
        reporter.start(JobProgress(stage="created", message="Batch job created", completed_steps=0, total_steps=total_steps))

        def emit_progress(
            stage: str,
            message: str,
            *,
            advance: int = 1,
            status: str = "running",
            total_override: int | None = None,
        ) -> JobProgress:
            nonlocal completed_steps, total_steps
            if total_override is not None:
                total_steps = total_override
            completed_steps = min(total_steps, completed_steps + advance)
            progress = JobProgress(
                stage=stage,
                message=message,
                completed_steps=completed_steps,
                total_steps=total_steps,
                status=status,
            )
            self.repositories.update_job_progress(job_id, stage, message, completed_steps, total_steps, status=status)
            self.repositories.record_event(job_id, "job_progress", progress.to_dict())
            self.logger.event("job_progress", job_id, **progress.to_dict())
            reporter.update(progress)
            return progress

        try:
            emit_progress("loading_csv", f"Loading {csv_path.name}")
            sentences, report = load_sentences_with_report(csv_path)
            emit_progress("validating", f"Validated {report.total_rows} rows")
            if not report.is_valid:
                if report.issues:
                    raise ValidationError(report.issues[0].message)
                raise ValidationError("CSV validation failed.")
            filtered = self._filter_sentences(sentences, from_sentence_id, to_sentence_id)
            SentenceRepository(self.db).upsert_many(filtered)
            recipe = get_recipe(self.config.recipes, recipe_name)
            total_steps = 3 + len(filtered) * (len(recipe.segments) + 4)
            files: list[dict[str, object]] = []

            for index, sentence in enumerate(filtered, start=1):
                emit_progress("building_plan", f"Building sentence {index}/{len(filtered)} ({sentence.id})")
                plan = AudioPlanBuilder().build(
                    job_id,
                    recipe,
                    [sentence],
                    source_csv_path=str(csv_path),
                    target_language="fr",
                    target_column="french",
                )
                output_path = output_dir / f"{index:03d}_{self._safe_filename_part(sentence.id)}_{recipe_name}.{output_format}"
                builder = AudioBuilder(
                    selector=self._selector(),
                    cache_dir=self.config.tts_cache_dir,
                    repositories=self.repositories,
                    progress_callback=lambda stage, message: emit_progress(stage, message),
                )
                output_info = builder.build(plan, output_path, output_format=output_format)
                emit_progress("saving_manifest", f"Writing manifest for {output_path.name}")
                manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
                manifest = write_manifest(plan, output_info, manifest_path)
                emit_progress("saving_records", f"Recording output metadata for {output_path.name}")
                self.repositories.record_audio_output(job_id, output_path, manifest_path, int(output_info["duration_ms"]))
                files.append(
                    {
                        "sentence_id": sentence.id,
                        "output": str(output_path),
                        "manifest": str(manifest_path),
                        "duration_ms": int(output_info["duration_ms"]),
                        "recipe": recipe_name,
                        "manifest_data": manifest,
                    }
                )

            self.repositories.record_event(
                job_id,
                "folder_generated",
                {"output_dir": str(output_dir), "file_count": len(files), "output_format": output_format},
            )
            finished = emit_progress("finished", f"Generated {len(files)} sentence files", status="completed")
            self.repositories.complete_job(job_id, total_steps=finished.total_steps)
            self.logger.event(
                "folder_generated",
                job_id,
                output_dir=str(output_dir),
                file_count=len(files),
                output_format=output_format,
            )
            reporter.stop(finished)
            return {
                "job_id": job_id,
                "recipe_name": recipe_name,
                "output_dir": str(output_dir),
                "file_count": len(files),
                "files": files,
            }
        except Exception as exc:
            self.repositories.record_event(job_id, "job_failed", {"error": str(exc)})
            self.repositories.fail_job(job_id, str(exc))
            self.logger.event("job_failed", job_id, error=str(exc))
            reporter.stop(
                JobProgress(
                    stage="failed",
                    message=str(exc),
                    completed_steps=completed_steps,
                    total_steps=total_steps,
                    status="failed",
                )
            )
            raise

    def _load_filtered_sentences(
        self,
        csv_path: Path,
        from_sentence_id: str | None,
        to_sentence_id: str | None,
    ) -> list:
        sentences, report = load_sentences_with_report(csv_path)
        if not report.is_valid:
            if report.issues:
                raise ValidationError(report.issues[0].message)
            raise ValidationError("CSV validation failed.")
        return self._filter_sentences(sentences, from_sentence_id, to_sentence_id)

    def _filter_sentences(
        self,
        sentences: list,
        from_sentence_id: str | None,
        to_sentence_id: str | None,
    ) -> list:
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

    def _safe_filename_part(self, value: str) -> str:
        cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.strip())
        return cleaned.strip("_") or "sentence"
