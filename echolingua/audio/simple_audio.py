from __future__ import annotations

import wave
from pathlib import Path

FRAME_RATE = 8000
SAMPLE_WIDTH = 2
CHANNELS = 1


class SimpleAudioSegment:
    def __init__(self, duration_ms: int = 0) -> None:
        self.duration_ms = duration_ms

    @classmethod
    def silent(cls, duration: int) -> "SimpleAudioSegment":
        return cls(duration)

    @classmethod
    def empty(cls) -> "SimpleAudioSegment":
        return cls(0)

    @classmethod
    def from_file(cls, path: Path) -> "SimpleAudioSegment":
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            return cls(int(frames * 1000 / rate))

    def export(self, path: Path, format: str = "wav") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frames = int(self.duration_ms * FRAME_RATE / 1000)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(CHANNELS)
            handle.setsampwidth(SAMPLE_WIDTH)
            handle.setframerate(FRAME_RATE)
            handle.writeframes(b"\x00\x00" * frames)

    def __add__(self, other: "SimpleAudioSegment") -> "SimpleAudioSegment":
        return SimpleAudioSegment(self.duration_ms + other.duration_ms)

    def __len__(self) -> int:
        return self.duration_ms


def get_audio_segment():
    import importlib.util

    if importlib.util.find_spec("pydub") is not None:
        from pydub import AudioSegment

        return AudioSegment
    return SimpleAudioSegment
