from __future__ import annotations

from echolingua.core.errors import ProviderError
from echolingua.providers.base import ProviderMetadata
from echolingua.providers.tts.ajil import AJIL_REPOSITORY_URL, AJIL_SUBMODULE_PATH


class AjilLLMProvider:
    def __init__(self, name: str = "ajil-llm", priority: int = 40, enabled: bool = False, config: dict | None = None) -> None:
        self.metadata = ProviderMetadata(name=name, kind="llm", priority=priority, enabled=enabled, config=config or {})

    def complete(self, prompt: str, **kwargs: object) -> str:
        model = self.metadata.config.get("model", "auto")
        raise ProviderError(
            "AjilLLMProvider is a Phase 7 placeholder. "
            f"Expected future AJIL repo: {AJIL_REPOSITORY_URL} at {AJIL_SUBMODULE_PATH}. "
            f"Configured model={model!r}, prompt_length={len(prompt)}."
        )
