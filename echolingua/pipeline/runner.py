from __future__ import annotations

import json
from pathlib import Path
import traceback
from typing import Any

from echolingua.audio.builder import AudioBuilder
from echolingua.core.config import AppConfig
from echolingua.core.config_validation import resolve_tts_provider_policy, resolve_voice
from echolingua.core.errors import ProviderError, ValidationError
from echolingua.core.logging import JsonlLogger, TraceSession
from echolingua.core.progress import JobProgress, NullProgressReporter, ProgressReporter
from echolingua.pipeline.manifest import write_manifest
from echolingua.providers.registry import build_provider, build_registry, list_provider_configs, provider_config
from echolingua.providers.selector import ProviderSelectionPolicy, ProviderSelector
from echolingua.recipes.loader import get_recipe
from echolingua.recipes.planner import AudioPlan, AudioPlanBuilder, AudioPlanSegment
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
        provider_name: str | None = None,
    ) -> AudioPlan:
        sentences = self._load_filtered_sentences(csv_path, from_sentence_id, to_sentence_id)
        SentenceRepository(self.db).upsert_many(sentences)
        recipe = get_recipe(self.config.recipes, recipe_name)
        return self._apply_provider_defaults(
            AudioPlanBuilder().build(
                job_id,
                recipe,
                sentences,
                source_csv_path=str(csv_path),
                target_language="fr",
                target_column="french",
            ),
            recipe_name,
            provider_name=provider_name,
        )

    def build_plan_summary(
        self,
        job_id: str,
        csv_path: Path,
        recipe_name: str,
        from_sentence_id: str | None = None,
        to_sentence_id: str | None = None,
        provider_name: str | None = None,
    ) -> dict[str, object]:
        plan = self.build_plan(job_id, csv_path, recipe_name, from_sentence_id, to_sentence_id, provider_name=provider_name)
        policy = self._provider_policy(recipe_name, provider_name=provider_name)
        providers = [provider.metadata.name for provider in self._selector(recipe_name, provider_name=provider_name).ordered()]
        tts_segments = sum(1 for segment in plan.segments if segment.kind == "tts")
        silence_segments = sum(1 for segment in plan.segments if segment.kind == "silence")
        sentence_ids = list(dict.fromkeys(segment.sentence_id for segment in plan.segments))
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
                "default_provider": policy.default_provider,
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

    def latest_job_summary(self, job_id: str) -> dict[str, Any] | None:
        safe_job_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in job_id) or "job"
        summary_path = self.config.log_dir / "jobs" / safe_job_id / "latest-summary.json"
        if not summary_path.exists():
            return None
        with summary_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def generate(
        self,
        job_id: str,
        csv_path: Path,
        recipe_name: str,
        output_path: Path | None = None,
        from_sentence_id: str | None = None,
        to_sentence_id: str | None = None,
        provider_name: str | None = None,
        progress_reporter: ProgressReporter | None = None,
    ) -> dict:
        reporter = progress_reporter or NullProgressReporter()
        completed_steps = 0
        total_steps = 7
        start = JobProgress(stage="created", message="Job created", completed_steps=0, total_steps=total_steps)
        with self.logger.trace(
            "pipeline.generate",
            component="pipeline.runner",
            job_id=job_id,
            metadata={
                "csv_path": str(csv_path),
                "recipe_name": recipe_name,
                "provider_name": provider_name,
                "output_path": str(output_path) if output_path else None,
                "from_sentence_id": from_sentence_id,
                "to_sentence_id": to_sentence_id,
            },
        ) as trace:
            self.repositories.create_job(job_id, recipe_name)
            reporter.start(start)
            self._record_job_event(
                job_id,
                "job_started",
                {
                    "recipe_name": recipe_name,
                    "csv_path": str(csv_path),
                    "provider_name": provider_name,
                    "output_path": str(output_path) if output_path else None,
                },
                trace_session=trace,
                status="started",
                component="pipeline.runner",
                operation="pipeline.generate",
            )

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
                self._record_job_event(
                    job_id,
                    "job_progress",
                    progress.to_dict(),
                    trace_session=trace,
                    status=status,
                    component="pipeline.progress",
                    operation=f"progress.{stage}",
                )
                reporter.update(progress)
                return progress

            try:
                with trace.span("pipeline.load_csv", component="pipeline.runner", payload={"csv_path": str(csv_path)}) as span:
                    emit_progress("loading_csv", f"Loading {csv_path.name}")
                    sentences, report = load_sentences_with_report(csv_path)
                    span.set_result(
                        total_rows=report.total_rows,
                        enabled_rows=report.enabled_rows,
                        invalid_rows=report.invalid_rows,
                    )
                with trace.span("pipeline.validate_csv", component="pipeline.runner", payload={"csv_path": str(csv_path)}) as span:
                    emit_progress("validating", f"Validated {report.total_rows} rows")
                    if not report.is_valid:
                        if report.issues:
                            raise ValidationError(report.issues[0].message)
                        raise ValidationError("CSV validation failed.")
                    span.set_result(issue_count=len(report.issues), valid_rows=report.valid_rows)
                with trace.span(
                    "pipeline.filter_sentences",
                    component="pipeline.runner",
                    payload={"from_sentence_id": from_sentence_id, "to_sentence_id": to_sentence_id},
                ) as span:
                    filtered = self._filter_sentences(sentences, from_sentence_id, to_sentence_id)
                    SentenceRepository(self.db).upsert_many(filtered)
                    span.set_result(sentence_count=len(filtered), sentence_ids=[sentence.id for sentence in filtered[:20]])
                with trace.span("pipeline.build_plan", component="pipeline.runner", payload={"recipe_name": recipe_name}) as span:
                    recipe = get_recipe(self.config.recipes, recipe_name)
                    plan = self._apply_provider_defaults(
                        AudioPlanBuilder().build(
                            job_id,
                            recipe,
                            filtered,
                            source_csv_path=str(csv_path),
                            target_language="fr",
                            target_column="french",
                        ),
                        recipe_name,
                        provider_name=provider_name,
                    )
                    span.set_result(segment_count=len(plan.segments), output_format=plan.output_format)
                emit_progress("building_plan", f"Built plan with {len(plan.segments)} segments", total_override=len(plan.segments) + 7)
                plan_payload = {
                    "segment_count": len(plan.segments),
                    "recipe_name": recipe_name,
                    "selected_sentence_ids": plan.selected_sentence_ids,
                    "output_format": plan.output_format,
                    "plan": json.dumps(plan.to_dict(), ensure_ascii=False),
                }
                self._record_job_event(
                    job_id,
                    "plan_built",
                    plan_payload,
                    trace_session=trace,
                    component="pipeline.runner",
                    operation="pipeline.build_plan",
                )
                selector = self._selector(recipe_name, provider_name=provider_name)
                output = output_path or (self.config.output_dir / f"{job_id}_{recipe_name}.{plan.output_format}")
                output_format = output.suffix.lstrip(".") or plan.output_format
                trace.set_artifact("planned_output_path", str(output))
                builder = AudioBuilder(
                    selector=selector,
                    cache_dir=self.config.tts_cache_dir,
                    repositories=self.repositories,
                    progress_callback=lambda stage, message: emit_progress(stage, message),
                    trace_session=trace,
                )
                with trace.span(
                    "pipeline.render_audio",
                    component="pipeline.runner",
                    payload={"output_path": str(output), "output_format": output_format},
                ) as span:
                    output_info = builder.build(plan, output, output_format=output_format)
                    span.set_result(path=output_info["path"], duration_ms=output_info["duration_ms"])
                emit_progress("saving_manifest", f"Writing manifest for {output.name}")
                with trace.span("pipeline.write_manifest", component="pipeline.runner", payload={"output_path": str(output)}) as span:
                    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
                    manifest = write_manifest(plan, output_info, manifest_path)
                    span.set_result(manifest_path=str(manifest_path))
                emit_progress("saving_records", f"Recording output metadata for {output.name}")
                with trace.span("pipeline.record_output", component="pipeline.runner", payload={"output_path": str(output)}) as span:
                    self.repositories.record_audio_output(job_id, output, manifest_path, output_info["duration_ms"])
                    span.set_result(output_path=str(output), duration_ms=output_info["duration_ms"])
                self._record_job_event(
                    job_id,
                    "audio_generated",
                    {
                        "output": str(output),
                        "manifest": str(manifest_path),
                        "duration_ms": output_info["duration_ms"],
                        "segment_count": len(output_info["segments"]),
                    },
                    trace_session=trace,
                    component="pipeline.runner",
                    operation="pipeline.generate",
                )
                finished = emit_progress("finished", "Generation complete", status="completed")
                self.repositories.complete_job(job_id, total_steps=finished.total_steps)
                trace.set_artifact("output_path", str(output))
                trace.set_artifact("manifest_path", str(manifest_path))
                trace.set_summary(
                    recipe_name=recipe_name,
                    output_path=str(output),
                    manifest_path=str(manifest_path),
                    output_duration_ms=output_info["duration_ms"],
                    segment_count=len(plan.segments),
                    rendered_segment_count=len(output_info["segments"]),
                    selected_sentence_count=len(plan.selected_sentence_ids),
                )
                reporter.stop(finished)
                return {"plan": plan, "output": output_info, "manifest_path": manifest_path, "manifest": manifest}
            except Exception as exc:
                error_payload = self._serialize_error(exc)
                self._record_job_event(
                    job_id,
                    "job_failed",
                    {"error": str(exc), "error_type": exc.__class__.__name__},
                    trace_session=trace,
                    status="failed",
                    component="pipeline.runner",
                    operation="pipeline.generate",
                    level="ERROR",
                    error=error_payload,
                )
                self.repositories.fail_job(job_id, str(exc))
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
        provider_name: str | None = None,
        progress_reporter: ProgressReporter | None = None,
    ) -> dict[str, object]:
        reporter = progress_reporter or NullProgressReporter()
        completed_steps = 0
        total_steps = 1
        with self.logger.trace(
            "pipeline.generate_sentence_files",
            component="pipeline.runner",
            job_id=job_id,
            metadata={
                "csv_path": str(csv_path),
                "recipe_name": recipe_name,
                "provider_name": provider_name,
                "output_dir": str(output_dir),
                "output_format": output_format,
                "from_sentence_id": from_sentence_id,
                "to_sentence_id": to_sentence_id,
            },
        ) as trace:
            self.repositories.create_job(job_id, recipe_name)
            output_dir.mkdir(parents=True, exist_ok=True)
            reporter.start(JobProgress(stage="created", message="Batch job created", completed_steps=0, total_steps=total_steps))
            self._record_job_event(
                job_id,
                "job_started",
                {"recipe_name": recipe_name, "csv_path": str(csv_path), "output_dir": str(output_dir)},
                trace_session=trace,
                status="started",
                component="pipeline.runner",
                operation="pipeline.generate_sentence_files",
            )

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
                self._record_job_event(
                    job_id,
                    "job_progress",
                    progress.to_dict(),
                    trace_session=trace,
                    status=status,
                    component="pipeline.progress",
                    operation=f"progress.{stage}",
                )
                reporter.update(progress)
                return progress

            try:
                with trace.span("pipeline.load_csv", component="pipeline.runner", payload={"csv_path": str(csv_path)}) as span:
                    emit_progress("loading_csv", f"Loading {csv_path.name}")
                    sentences, report = load_sentences_with_report(csv_path)
                    span.set_result(total_rows=report.total_rows, enabled_rows=report.enabled_rows)
                with trace.span("pipeline.validate_csv", component="pipeline.runner", payload={"csv_path": str(csv_path)}) as span:
                    emit_progress("validating", f"Validated {report.total_rows} rows")
                    if not report.is_valid:
                        if report.issues:
                            raise ValidationError(report.issues[0].message)
                        raise ValidationError("CSV validation failed.")
                    span.set_result(valid_rows=report.valid_rows)
                with trace.span(
                    "pipeline.filter_sentences",
                    component="pipeline.runner",
                    payload={"from_sentence_id": from_sentence_id, "to_sentence_id": to_sentence_id},
                ) as span:
                    filtered = self._filter_sentences(sentences, from_sentence_id, to_sentence_id)
                    SentenceRepository(self.db).upsert_many(filtered)
                    span.set_result(sentence_count=len(filtered))
                recipe = get_recipe(self.config.recipes, recipe_name)
                total_steps = 3 + len(filtered) * (len(recipe.segments) + 4)
                files: list[dict[str, object]] = []

                for index, sentence in enumerate(filtered, start=1):
                    with trace.span(
                        "pipeline.generate_sentence_file",
                        component="pipeline.runner",
                        payload={"index": index, "sentence_id": sentence.id},
                    ) as sentence_span:
                        emit_progress("building_plan", f"Building sentence {index}/{len(filtered)} ({sentence.id})")
                        plan = AudioPlanBuilder().build(
                            job_id,
                            recipe,
                            [sentence],
                            source_csv_path=str(csv_path),
                            target_language="fr",
                            target_column="french",
                        )
                        plan = self._apply_provider_defaults(plan, recipe_name, provider_name=provider_name)
                        output_path = output_dir / f"{index:03d}_{self._safe_filename_part(sentence.id)}_{recipe_name}.{output_format}"
                        builder = AudioBuilder(
                            selector=self._selector(recipe_name, provider_name=provider_name),
                            cache_dir=self.config.tts_cache_dir,
                            repositories=self.repositories,
                            progress_callback=lambda stage, message: emit_progress(stage, message),
                            trace_session=trace,
                        )
                        output_info = builder.build(plan, output_path, output_format=output_format)
                        emit_progress("saving_manifest", f"Writing manifest for {output_path.name}")
                        manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
                        manifest = write_manifest(plan, output_info, manifest_path)
                        emit_progress("saving_records", f"Recording output metadata for {output_path.name}")
                        self.repositories.record_audio_output(job_id, output_path, manifest_path, int(output_info["duration_ms"]))
                        file_payload = {
                            "sentence_id": sentence.id,
                            "output": str(output_path),
                            "manifest": str(manifest_path),
                            "duration_ms": int(output_info["duration_ms"]),
                            "recipe": recipe_name,
                            "manifest_data": manifest,
                        }
                        files.append(file_payload)
                        sentence_span.set_result(output=str(output_path), manifest=str(manifest_path), duration_ms=int(output_info["duration_ms"]))

                self._record_job_event(
                    job_id,
                    "folder_generated",
                    {"output_dir": str(output_dir), "file_count": len(files), "output_format": output_format},
                    trace_session=trace,
                    component="pipeline.runner",
                    operation="pipeline.generate_sentence_files",
                )
                finished = emit_progress("finished", f"Generated {len(files)} sentence files", status="completed")
                self.repositories.complete_job(job_id, total_steps=finished.total_steps)
                trace.set_artifact("output_dir", str(output_dir))
                trace.set_summary(
                    recipe_name=recipe_name,
                    output_dir=str(output_dir),
                    file_count=len(files),
                    output_format=output_format,
                    selected_sentence_count=len(filtered),
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
                error_payload = self._serialize_error(exc)
                self._record_job_event(
                    job_id,
                    "job_failed",
                    {"error": str(exc), "error_type": exc.__class__.__name__},
                    trace_session=trace,
                    status="failed",
                    component="pipeline.runner",
                    operation="pipeline.generate_sentence_files",
                    level="ERROR",
                    error=error_payload,
                )
                self.repositories.fail_job(job_id, str(exc))
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

    def _provider_policy(self, recipe_name: str | None = None, provider_name: str | None = None) -> ProviderSelectionPolicy:
        recipe_policy: dict[str, object] | None = None
        if recipe_name is not None:
            recipe = get_recipe(self.config.recipes, recipe_name)
            recipe_policy = recipe.provider_policy
        merged = resolve_tts_provider_policy(self.config.default, recipe_policy)
        if provider_name:
            merged["strategy"] = "explicit"
            merged["explicit_provider"] = provider_name
            merged["default_provider"] = provider_name
        return ProviderSelectionPolicy.from_config(merged)

    def _selector(self, recipe_name: str | None = None, provider_name: str | None = None) -> ProviderSelector:
        if provider_name is not None:
            provider = build_provider(self.config.providers, "tts", provider_name)
            return ProviderSelector(
                [provider],
                self._provider_policy(recipe_name, provider_name=provider_name),
                include_disabled=True,
            )
        registry = build_registry(self.config.providers)
        return ProviderSelector(registry.list("tts"), self._provider_policy(recipe_name, provider_name=provider_name))

    def _apply_provider_defaults(self, plan: AudioPlan, recipe_name: str, provider_name: str | None = None) -> AudioPlan:
        selector = self._selector(recipe_name, provider_name=provider_name)
        default_provider_name = selector.ordered()[0].metadata.name
        updated_segments: list[AudioPlanSegment] = []
        for segment in plan.segments:
            if segment.kind != "tts":
                updated_segments.append(segment)
                continue
            provider_name = segment.provider or default_provider_name
            provider_settings = provider_config(self.config.providers, "tts", provider_name)
            updated_segments.append(
                AudioPlanSegment(
                    kind=segment.kind,
                    sentence_id=segment.sentence_id,
                    text=segment.text,
                    text_field=segment.text_field,
                    language=segment.language,
                    voice=resolve_voice(provider_settings, segment.language, segment.voice),
                    provider=provider_name,
                    duration_ms=segment.duration_ms,
                    rate=segment.rate,
                    pitch=segment.pitch,
                    volume=segment.volume,
                    sequence=segment.sequence,
                )
            )
        return AudioPlan(
            job_id=plan.job_id,
            recipe_name=plan.recipe_name,
            output_format=plan.output_format,
            target_language=plan.target_language,
            target_column=plan.target_column,
            source_csv_path=plan.source_csv_path,
            selected_sentence_ids=plan.selected_sentence_ids,
            segments=updated_segments,
        )

    def _safe_filename_part(self, value: str) -> str:
        cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.strip())
        return cleaned.strip("_") or "sentence"

    def _record_job_event(
        self,
        job_id: str,
        event_name: str,
        payload: dict[str, Any],
        *,
        trace_session: TraceSession | None = None,
        status: str = "ok",
        component: str = "pipeline.runner",
        operation: str | None = None,
        duration_ms: int | None = None,
        level: str = "INFO",
        error: dict[str, Any] | None = None,
    ) -> None:
        trace_id = trace_session.trace_id if trace_session is not None else None
        span_id = trace_session.current_span_id if trace_session is not None else None
        if trace_session is not None:
            trace_session.event(
                event_name,
                payload=payload,
                status=status,
                component=component,
                operation=operation,
                duration_ms=duration_ms,
                level=level,
                error=error,
            )
        else:
            self.logger.event(event_name, job_id, **payload)
        self.repositories.record_event(
            job_id,
            event_name,
            payload,
            status=status,
            component=component,
            operation=operation,
            duration_ms=duration_ms,
            level=level,
            trace_id=trace_id,
            span_id=span_id,
            error=error,
        )

    def _serialize_error(self, exc: BaseException) -> dict[str, Any]:
        return {
            "type": exc.__class__.__name__,
            "message": str(exc),
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        }
