from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from echolingua.audio.simple_audio import get_audio_segment
from echolingua.core.errors import ProviderError

AudioSegment = get_audio_segment()

from echolingua.audio.cache import cache_path, tts_cache_key
from echolingua.audio.duration import audio_duration_ms
from echolingua.providers.selector import ProviderSelector
from echolingua.providers.tts.base import TTSRequest
from echolingua.recipes.planner import AudioPlan, AudioPlanSegment
from echolingua.storage.repositories import StorageRepositories


class AudioBuilder:
    def __init__(
        self,
        selector: ProviderSelector,
        cache_dir: Path,
        repositories: StorageRepositories | None = None,
        progress_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        self.selector = selector
        self.cache_dir = cache_dir
        self.repositories = repositories
        self.progress_callback = progress_callback

    def build(self, plan: AudioPlan, output_path: Path, output_format: str | None = None) -> dict[str, Any]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        combined = AudioSegment.empty()
        rendered_segments: list[dict[str, Any]] = []
        total_segments = len(plan.segments)
        for segment in plan.segments:
            self._notify_progress(
                "rendering_segments",
                f"Rendering segment {segment.sequence}/{total_segments} for sentence {segment.sentence_id}",
            )
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
        self._notify_progress("merging_audio", f"Merging {total_segments} segments into {output_path.name}")
        self._export_audio(combined, output_path, output_format or plan.output_format)
        return {"path": str(output_path), "duration_ms": len(combined), "segments": rendered_segments}

    def _export_audio(self, combined: Any, output_path: Path, output_format: str) -> None:
        try:
            combined.export(output_path, format=output_format)
        except Exception as exc:
            if output_format.lower() == "mp3":
                raise ProviderError(
                    "MP3 export is unavailable in this environment. Use a WAV output path for guaranteed offline generation."
                ) from exc
            raise

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
        ordered_providers = self.selector.ordered(segment.provider)
        for provider in ordered_providers:
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
        raise ProviderError(f"All TTS providers failed: {last_error}")

    def _notify_progress(self, stage: str, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(stage, message)
