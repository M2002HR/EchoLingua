from __future__ import annotations

from pathlib import Path

from echolingua.audio.builder import AudioBuilder
from echolingua.core.config import AppConfig
from echolingua.core.logging import JsonlLogger
from echolingua.pipeline.manifest import write_manifest
from echolingua.providers.registry import build_registry
from echolingua.providers.selector import ProviderSelectionPolicy, ProviderSelector
from echolingua.recipes.loader import get_recipe
from echolingua.recipes.planner import AudioPlan, AudioPlanBuilder
from echolingua.sentences.loader import load_sentences
from echolingua.sentences.repository import SentenceRepository
from echolingua.storage.db import Database
from echolingua.storage.repositories import StorageRepositories


class PipelineRunner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db = Database(config.db_path)
        self.db.initialize()
        self.repositories = StorageRepositories(self.db)
        self.logger = JsonlLogger(config.log_dir)

    def build_plan(self, job_id: str, csv_path: Path, recipe_name: str) -> AudioPlan:
        sentences = load_sentences(csv_path)
        SentenceRepository(self.db).upsert_many(sentences)
        recipe = get_recipe(self.config.recipes, recipe_name)
        return AudioPlanBuilder().build(job_id, recipe, sentences)

    def generate(self, job_id: str, csv_path: Path, recipe_name: str, output_path: Path | None = None) -> dict:
        plan = self.build_plan(job_id, csv_path, recipe_name)
        self.repositories.create_job(job_id, recipe_name)
        self.repositories.record_event(job_id, "plan_built", {"segment_count": len(plan.segments)})
        self.logger.event("plan_built", job_id, recipe_name=recipe_name, segment_count=len(plan.segments))
        registry = build_registry(self.config.providers)
        policy = ProviderSelectionPolicy.from_config(self.config.default.get("provider_policy", {}).get("tts", {}))
        selector = ProviderSelector(registry.list("tts"), policy)
        output = output_path or (self.config.output_dir / f"{job_id}_{recipe_name}.{plan.output_format}")
        builder = AudioBuilder(selector=selector, cache_dir=self.config.tts_cache_dir, repositories=self.repositories)
        output_info = builder.build(plan, output)
        manifest_path = output.with_suffix(output.suffix + ".manifest.json")
        manifest = write_manifest(plan, output_info, manifest_path)
        self.repositories.record_audio_output(job_id, output, manifest_path, output_info["duration_ms"])
        self.repositories.record_event(job_id, "audio_generated", {"output": str(output), "manifest": str(manifest_path)})
        self.repositories.complete_job(job_id)
        self.logger.event("audio_generated", job_id, output=str(output), manifest=str(manifest_path))
        return {"plan": plan, "output": output_info, "manifest_path": manifest_path, "manifest": manifest}
