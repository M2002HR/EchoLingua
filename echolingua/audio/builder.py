from __future__ import annotations

from time import perf_counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from echolingua.audio.simple_audio import get_audio_segment
from echolingua.core.errors import ProviderError
from echolingua.core.logging import TraceSession

AudioSegment = get_audio_segment()

from echolingua.audio.cache import cache_path, tts_cache_key
from echolingua.audio.duration import audio_duration_ms
from echolingua.providers.selector import ProviderSelector
from echolingua.providers.tts.base import TTSRequest
from echolingua.recipes.planner import AudioPlan, AudioPlanSegment
from echolingua.storage.repositories import StorageRepositories

if TYPE_CHECKING:
    from echolingua.providers.tts.base import TTSResult


class AudioBuilder:
    def __init__(
        self,
        selector: ProviderSelector,
        cache_dir: Path,
        repositories: StorageRepositories | None = None,
        progress_callback: Callable[[str, str], None] | None = None,
        trace_session: TraceSession | None = None,
    ) -> None:
        self.selector = selector
        self.cache_dir = cache_dir
        self.repositories = repositories
        self.progress_callback = progress_callback
        self.trace_session = trace_session

    def build(self, plan: AudioPlan, output_path: Path, output_format: str | None = None) -> dict[str, Any]:
        with self._span(
            "audio_builder.build",
            payload={
                "output_path": str(output_path),
                "output_format": output_format or plan.output_format,
                "segment_count": len(plan.segments),
                "job_id": plan.job_id,
            },
        ) as build_span:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            combined = AudioSegment.empty()
            rendered_segments: list[dict[str, Any]] = []
            total_segments = len(plan.segments)
            for segment in plan.segments:
                self._notify_progress(
                    "rendering_segments",
                    f"Rendering segment {segment.sequence}/{total_segments} for sentence {segment.sentence_id}",
                )
                with self._span(
                    "audio_builder.render_segment",
                    payload={
                        "sequence": segment.sequence,
                        "sentence_id": segment.sentence_id,
                        "kind": segment.kind,
                        "text_field": segment.text_field,
                    },
                ) as segment_span:
                    if segment.kind == "silence":
                        duration = int(segment.duration_ms or 0)
                        combined += AudioSegment.silent(duration=duration)
                        rendered_segments.append({"kind": "silence", "duration_ms": duration, "sequence": segment.sequence})
                        segment_span.set_result(duration_ms=duration)
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
                    segment_span.set_result(
                        audio_path=str(audio_path),
                        duration_ms=duration,
                        provider=provider_name,
                        cached=cached,
                    )
            self._notify_progress("merging_audio", f"Merging {total_segments} segments into {output_path.name}")
            with self._span(
                "audio_builder.export_audio",
                payload={"output_path": str(output_path), "output_format": output_format or plan.output_format},
            ) as export_span:
                self._export_audio(combined, output_path, output_format or plan.output_format)
                export_span.set_result(duration_ms=len(combined), output_path=str(output_path))
            result = {"path": str(output_path), "duration_ms": len(combined), "segments": rendered_segments}
            build_span.set_result(duration_ms=len(combined), output_path=str(output_path), rendered_segments=len(rendered_segments))
            return result

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
        request = self._request(segment)
        for provider in ordered_providers:
            path = cache_path(self.cache_dir, provider.metadata.name, request)
            key = tts_cache_key(provider.metadata.name, request)
            try:
                with self._span(
                    "audio_builder.provider_attempt",
                    payload={
                        "provider": provider.metadata.name,
                        "sentence_id": segment.sentence_id,
                        "sequence": segment.sequence,
                        "cache_key": key,
                        "request": self._request_summary(request),
                    },
                ) as attempt_span:
                    if path.exists():
                        duration = audio_duration_ms(path)
                        if self.repositories:
                            self.repositories.record_provider_attempt(
                                job_id,
                                provider.metadata.name,
                                "tts",
                                "cache_hit",
                                None,
                                duration_ms=duration,
                                cache_key=key,
                                request_summary=self._request_summary(request),
                            )
                            self.repositories.upsert_tts_cache(key, provider.metadata.name, request, path, duration)
                        attempt_span.set_result(path=str(path), duration_ms=duration, cached=True)
                        return path, duration, provider.metadata.name, True
                    started = perf_counter()
                    result = provider.synthesize(request, path)
                    duration = result.duration_ms or audio_duration_ms(result.path)
                    attempt_duration_ms = int((perf_counter() - started) * 1000)
                    if self.repositories:
                        self.repositories.record_provider_attempt(
                            job_id,
                            provider.metadata.name,
                            "tts",
                            "success",
                            None,
                            duration_ms=attempt_duration_ms,
                            cache_key=key,
                            request_summary=self._request_summary(request),
                        )
                        self.repositories.upsert_tts_cache(key, provider.metadata.name, request, result.path, duration)
                    attempt_span.set_result(
                        path=str(result.path),
                        provider_duration_ms=duration,
                        attempt_duration_ms=attempt_duration_ms,
                        cached=False,
                    )
                    return result.path, duration, provider.metadata.name, False
            except Exception as exc:
                last_error = exc
                if self.repositories:
                    self.repositories.record_provider_attempt(
                        job_id,
                        provider.metadata.name,
                        "tts",
                        "error",
                        str(exc),
                        cache_key=key,
                        request_summary=self._request_summary(request),
                    )
                if not self.selector.policy.allow_fallback_on_error:
                    raise
        raise ProviderError(f"All TTS providers failed: {last_error}")

    def _notify_progress(self, stage: str, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(stage, message)

    def _request_summary(self, request: TTSRequest) -> dict[str, Any]:
        return {
            "text_length": len(request.text),
            "voice": request.voice,
            "language": request.language,
            "rate": request.rate,
            "pitch": request.pitch,
            "volume": request.volume,
        }

    def _span(self, operation: str, *, payload: dict[str, Any]) -> AbstractBuilderSpan:
        return AbstractBuilderSpan(self.trace_session, operation, payload)


class AbstractBuilderSpan:
    def __init__(self, trace_session: TraceSession | None, operation: str, payload: dict[str, Any]) -> None:
        self.trace_session = trace_session
        self.operation = operation
        self.payload = payload
        self._span: Any = None

    def __enter__(self) -> Any:
        if self.trace_session is None:
            return _NullSpan()
        self._span = self.trace_session.span(operation=self.operation, component="audio.builder", payload=self.payload)
        return self._span.__enter__()

    def __exit__(self, exc_type, exc, exc_tb) -> bool:
        if self._span is None:
            return False
        return bool(self._span.__exit__(exc_type, exc, exc_tb))


class _NullSpan:
    def set_result(self, **payload: Any) -> None:
        return None
