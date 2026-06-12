from __future__ import annotations

from typing import Any

from echolingua.providers.tts.edge import EdgeTTSProvider
from echolingua.providers.tts.fake import FakeTTSProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, dict[str, Any]] = {"tts": {}}

    def register(self, kind: str, name: str, provider: Any) -> None:
        self._providers.setdefault(kind, {})[name] = provider

    def get(self, kind: str, name: str) -> Any:
        return self._providers[kind][name]

    def list(self, kind: str) -> list[Any]:
        return list(self._providers.get(kind, {}).values())


def build_registry(providers_config: dict[str, Any]) -> ProviderRegistry:
    registry = ProviderRegistry()
    for name, config in (providers_config.get("tts") or {}).items():
        if not config.get("enabled", False):
            continue
        provider_type = config.get("provider", name)
        priority = int(config.get("priority", 100))
        if provider_type == "fake":
            registry.register("tts", name, FakeTTSProvider(name=name, priority=priority, config=config))
        elif provider_type == "edge":
            registry.register("tts", name, EdgeTTSProvider(name=name, priority=priority, config=config))
    return registry
