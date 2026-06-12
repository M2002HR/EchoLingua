from __future__ import annotations

from pathlib import Path

from echolingua.audio.simple_audio import get_audio_segment

AudioSegment = get_audio_segment()

from echolingua.providers.base import ProviderMetadata
from echolingua.providers.tts.base import TTSRequest, TTSResult


class FakeTTSProvider:
    def __init__(self, name: str = "fake", priority: int = 10, config: dict | None = None) -> None:
        self.metadata = ProviderMetadata(name=name, kind="tts", priority=priority, enabled=True, config=config or {})

    def synthesize(self, request: TTSRequest, output_path: Path) -> TTSResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration_ms = max(250, min(4000, 80 * len(request.text)))
        AudioSegment.silent(duration=duration_ms).export(output_path, format="wav")
        return TTSResult(path=output_path, duration_ms=duration_ms, cached=False)
