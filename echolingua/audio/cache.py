from __future__ import annotations

import hashlib
from pathlib import Path

from echolingua.providers.tts.base import TTSRequest


def tts_cache_key(provider: str, request: TTSRequest) -> str:
    raw = "|".join([
        provider,
        request.text,
        request.voice,
        request.rate,
        request.pitch,
        request.volume,
        request.language,
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_path(cache_dir: Path, provider: str, request: TTSRequest) -> Path:
    return cache_dir / f"{tts_cache_key(provider, request)}.wav"
