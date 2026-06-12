from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

from echolingua.core.errors import ProviderError
from echolingua.providers.base import ProviderMetadata
from echolingua.providers.tts.base import TTSRequest, TTSResult


class PiperTTSProvider:
    def __init__(self, name: str = "piper", priority: int = 30, enabled: bool = False, config: dict | None = None) -> None:
        self.metadata = ProviderMetadata(name=name, kind="tts", priority=priority, enabled=enabled, config=config or {})

    def synthesize(self, request: TTSRequest, output_path: Path) -> TTSResult:
        model_path = self.metadata.config.get("model_path")
        config_path = self.metadata.config.get("config_path")
        if not model_path:
            raise ProviderError(
                "PiperTTSProvider is not configured yet. Set tts.piper.model_path and config_path in config/providers.yaml."
            )
        if not self._runtime_available():
            raise ProviderError(
                "Piper runtime is not available. Install Piper locally or run wyoming-piper before enabling this provider."
            )
        raise ProviderError(
            "PiperTTSProvider is currently a placeholder in EchoLingua Phase 6. "
            f"Configured model_path={model_path!r}, config_path={config_path!r}, requested output={str(output_path)!r}."
        )

    def _runtime_available(self) -> bool:
        return (
            shutil.which("piper") is not None
            or shutil.which("wyoming-piper") is not None
            or importlib.util.find_spec("wyoming_piper") is not None
        )
