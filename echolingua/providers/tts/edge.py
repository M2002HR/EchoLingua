from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

from echolingua.core.errors import ProviderError
from echolingua.providers.base import ProviderMetadata
from echolingua.providers.tts.base import TTSRequest, TTSResult


class EdgeTTSProvider:
    def __init__(self, name: str = "edge", priority: int = 20, config: dict | None = None) -> None:
        self.metadata = ProviderMetadata(name=name, kind="tts", priority=priority, enabled=True, config=config or {})

    def synthesize(self, request: TTSRequest, output_path: Path) -> TTSResult:
        if importlib.util.find_spec("edge_tts") is None:
            raise ProviderError("edge-tts is not installed. Install with: pip install 'echolingua[edge]'")
        import edge_tts

        async def _run() -> None:
            communicate = edge_tts.Communicate(
                text=request.text,
                voice=request.voice,
                rate=request.rate,
                pitch=request.pitch,
                volume=request.volume,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            await communicate.save(str(output_path))

        asyncio.run(_run())
        return TTSResult(path=output_path, duration_ms=0, cached=False)
