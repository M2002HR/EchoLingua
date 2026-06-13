from __future__ import annotations

from pathlib import Path

from echolingua.core.errors import ProviderError
from echolingua.providers.base import ProviderMetadata
from echolingua.providers.tts.base import TTSRequest, TTSResult

AJIL_REPOSITORY_URL = "https://github.com/M2002HR/Ajil_Unified_AI_Gateway.git"
AJIL_SUBMODULE_PATH = "vendor/Ajil_Unified_AI_Gateway/"


class AjilTTSProvider:
    def __init__(self, name: str = "ajil", priority: int = 40, enabled: bool = False, config: dict | None = None) -> None:
        self.metadata = ProviderMetadata(name=name, kind="tts", priority=priority, enabled=enabled, config=config or {})

    def synthesize(self, request: TTSRequest, output_path: Path) -> TTSResult:
        base_url = self.metadata.config.get("base_url", "http://127.0.0.1:8080")
        raise ProviderError(
            "AjilTTSProvider is a Phase 7 placeholder. "
            f"Expected future AJIL repo: {AJIL_REPOSITORY_URL} at {AJIL_SUBMODULE_PATH}. "
            f"Configured base_url={base_url!r}, requested output={str(output_path)!r}."
        )
