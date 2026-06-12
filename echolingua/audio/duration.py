from __future__ import annotations

from pathlib import Path

from echolingua.audio.simple_audio import get_audio_segment

AudioSegment = get_audio_segment()


def audio_duration_ms(path: Path) -> int:
    return len(AudioSegment.from_file(path))
