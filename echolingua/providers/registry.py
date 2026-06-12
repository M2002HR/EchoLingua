from __future__ import annotations

import importlib.util
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


def provider_dependency_available(provider_type: str) -> bool:
    if provider_type == "edge":
        return importlib.util.find_spec("edge_tts") is not None
    return True


def _provider_from_config(name: str, config: dict[str, Any]) -> Any:
    provider_type = str(config.get("provider", name))
    priority = int(config.get("priority", 100))
    enabled = bool(config.get("enabled", False))
    if provider_type == "fake":
        return FakeTTSProvider(name=name, priority=priority, enabled=enabled, config=config)
    if provider_type == "edge":
        return EdgeTTSProvider(name=name, priority=priority, enabled=enabled, config=config)
    raise KeyError(f"Unsupported provider type: {provider_type}")


def list_provider_configs(providers_config: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, config in (providers_config.get(kind) or {}).items():
        provider_type = str(config.get("provider", name))
        rows.append(
            {
                "name": name,
                "kind": kind,
                "provider_type": provider_type,
                "enabled": bool(config.get("enabled", False)),
                "priority": int(config.get("priority", 100)),
                "dependency_available": provider_dependency_available(provider_type),
            }
        )
    return rows


def provider_config(providers_config: dict[str, Any], kind: str, name: str) -> dict[str, Any]:
    config = (providers_config.get(kind) or {}).get(name)
    if config is None:
        raise KeyError(name)
    return config


def build_provider(providers_config: dict[str, Any], kind: str, name: str) -> Any:
    return _provider_from_config(name, provider_config(providers_config, kind, name))


def build_registry(providers_config: dict[str, Any]) -> ProviderRegistry:
    registry = ProviderRegistry()
    for name, config in (providers_config.get("tts") or {}).items():
        if not config.get("enabled", False):
            continue
        registry.register("tts", name, _provider_from_config(name, config))
    return registry
