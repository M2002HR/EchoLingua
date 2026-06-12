from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from echolingua.providers.base import ProviderMetadata


@dataclass(frozen=True)
class TTSRequest:
    text: str
    voice: str
    language: str
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"


@dataclass(frozen=True)
class TTSResult:
    path: Path
    duration_ms: int
    cached: bool = False


class TTSProvider(Protocol):
    metadata: ProviderMetadata

    def synthesize(self, request: TTSRequest, output_path: Path) -> TTSResult:
        ...
