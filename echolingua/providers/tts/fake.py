from __future__ import annotations

import math
import wave
from pathlib import Path

from echolingua.providers.base import ProviderMetadata
from echolingua.providers.tts.base import TTSRequest, TTSResult

FRAME_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1
AMPLITUDE = 12000


class FakeTTSProvider:
    def __init__(self, name: str = "fake", priority: int = 10, enabled: bool = True, config: dict | None = None) -> None:
        self.metadata = ProviderMetadata(name=name, kind="tts", priority=priority, enabled=enabled, config=config or {})

    def synthesize(self, request: TTSRequest, output_path: Path) -> TTSResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration_ms = max(250, min(4000, 80 * len(request.text)))
        waveform = self._waveform_bytes(request.text, duration_ms)
        with wave.open(str(output_path), "wb") as handle:
            handle.setnchannels(CHANNELS)
            handle.setsampwidth(SAMPLE_WIDTH)
            handle.setframerate(FRAME_RATE)
            handle.writeframes(waveform)
        return TTSResult(path=output_path, duration_ms=duration_ms, cached=False)

    def _waveform_bytes(self, text: str, duration_ms: int) -> bytes:
        frame_count = int(FRAME_RATE * duration_ms / 1000)
        frequency = self._frequency_for_text(text)
        data = bytearray()
        fade_frames = min(frame_count // 10, int(FRAME_RATE * 0.02))
        for index in range(frame_count):
            envelope = 1.0
            if fade_frames > 0:
                if index < fade_frames:
                    envelope = index / fade_frames
                elif index >= frame_count - fade_frames:
                    envelope = (frame_count - index - 1) / fade_frames
            sample = int(
                AMPLITUDE
                * envelope
                * math.sin(2 * math.pi * frequency * (index / FRAME_RATE))
            )
            data.extend(sample.to_bytes(2, byteorder="little", signed=True))
        return bytes(data)

    def _frequency_for_text(self, text: str) -> float:
        base = 220
        span = 220
        checksum = sum(ord(char) for char in text) % span
        return float(base + checksum)
