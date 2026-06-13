from __future__ import annotations

from dataclasses import dataclass, field

from echolingua.core.errors import ProviderError
from echolingua.providers.tts.ajil import AJIL_REPOSITORY_URL, AJIL_SUBMODULE_PATH


@dataclass(frozen=True)
class AjilGatewaySettings:
    base_url: str = "http://127.0.0.1:8090"
    tts_route: str = "/v1/tts"
    llm_route: str = "/v1/chat/completions"
    api_key_env: str = "UAG_API_KEY"
    repository_url: str = AJIL_REPOSITORY_URL
    submodule_path: str = AJIL_SUBMODULE_PATH
    extra_env: dict[str, str] = field(default_factory=dict)


class AjilGatewayClient:
    """Phase 7 placeholder for future AJIL Unified AI Gateway integration."""

    def __init__(self, settings: AjilGatewaySettings | None = None) -> None:
        self.settings = settings or AjilGatewaySettings()

    def tts_request(self, *, text: str, voice: str, language: str) -> dict[str, object]:
        self._placeholder_error("tts")
        return {"text": text, "voice": voice, "language": language}

    def llm_request(self, *, prompt: str, model: str | None = None) -> dict[str, object]:
        self._placeholder_error("llm")
        return {"prompt": prompt, "model": model}

    def _placeholder_error(self, capability: str) -> None:
        raise ProviderError(
            "AJIL integration is a Phase 7 placeholder. "
            f"Capability={capability!r}, base_url={self.settings.base_url!r}, "
            f"repo={self.settings.repository_url}, submodule={self.settings.submodule_path}."
        )
