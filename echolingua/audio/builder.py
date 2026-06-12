from __future__ import annotations

from pathlib import Path
from typing import Any

from echolingua.audio.simple_audio import get_audio_segment

AudioSegment = get_audio_segment()

from echolingua.audio.cache import cache_path, tts_cache_key
from echolingua.audio.duration import audio_duration_ms
from echolingua.providers.selector import ProviderSelector
from echolingua.providers.tts.base import TTSRequest
from echolingua.recipes.planner import AudioPlan, AudioPlanSegment
from echolingua.storage.repositories import StorageRepositories


class AudioBuilder:
    def __init__(self, selector: ProviderSelector, cache_dir: Path, repositories: StorageRepositories | None = None) -> None:
        self.selector = selector
        self.cache_dir = cache_dir
        self.repositories = repositories

    def build(self, plan: AudioPlan, output_path: Path) -> dict[str, Any]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        combined = AudioSegment.empty()
        rendered_segments: list[dict[str, Any]] = []
        for segment in plan.segments:
            if segment.kind == "silence":
                duration = int(segment.duration_ms or 0)
                combined += AudioSegment.silent(duration=duration)
                rendered_segments.append({"kind": "silence", "duration_ms": duration, "sequence": segment.sequence})
                continue
            audio_path, duration, provider_name, cached = self._render_tts(plan.job_id, segment)
            combined += AudioSegment.from_file(audio_path)
            rendered_segments.append({
                "kind": "tts",
                "duration_ms": duration,
                "sequence": segment.sequence,
                "provider": provider_name,
                "cache_key": tts_cache_key(provider_name, self._request(segment)),
                "cached": cached,
            })
        combined.export(output_path, format=plan.output_format)
        return {"path": str(output_path), "duration_ms": len(combined), "segments": rendered_segments}

    def _request(self, segment: AudioPlanSegment) -> TTSRequest:
        return TTSRequest(
            text=segment.text or "",
            voice=segment.voice or "default",
            language=segment.language or "und",
            rate=segment.rate,
            pitch=segment.pitch,
            volume=segment.volume,
        )

    def _render_tts(self, job_id: str, segment: AudioPlanSegment) -> tuple[Path, int, str, bool]:
        last_error: Exception | None = None
        for provider in self.selector.ordered():
            request = self._request(segment)
            path = cache_path(self.cache_dir, provider.metadata.name, request)
            key = tts_cache_key(provider.metadata.name, request)
            if path.exists():
                duration = audio_duration_ms(path)
                if self.repositories:
                    self.repositories.record_provider_attempt(job_id, provider.metadata.name, "tts", "cache_hit", None)
                    self.repositories.upsert_tts_cache(key, provider.metadata.name, request, path, duration)
                return path, duration, provider.metadata.name, True
            try:
                result = provider.synthesize(request, path)
                duration = result.duration_ms or audio_duration_ms(result.path)
                if self.repositories:
                    self.repositories.record_provider_attempt(job_id, provider.metadata.name, "tts", "success", None)
                    self.repositories.upsert_tts_cache(key, provider.metadata.name, request, result.path, duration)
                return result.path, duration, provider.metadata.name, False
            except Exception as exc:
                last_error = exc
                if self.repositories:
                    self.repositories.record_provider_attempt(job_id, provider.metadata.name, "tts", "error", str(exc))
                if not self.selector.policy.allow_fallback_on_error:
                    raise
        raise RuntimeError(f"All TTS providers failed: {last_error}")
