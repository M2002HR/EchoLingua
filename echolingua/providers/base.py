from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderMetadata:
    name: str
    kind: str
    priority: int = 100
    enabled: bool = True
    config: dict[str, Any] | None = None


class Provider(Protocol):
    metadata: ProviderMetadata


class LLMProvider(Protocol):
    metadata: ProviderMetadata

    def complete(self, prompt: str, **kwargs: Any) -> str:
        ...


class ExportProvider(Protocol):
    metadata: ProviderMetadata

    def export(self, payload: dict[str, Any], destination: Path) -> Path:
        ...


class StorageProvider(Protocol):
    metadata: ProviderMetadata

    def save(self, collection: str, payload: dict[str, Any]) -> str:
        ...


class AnalyticsProvider(Protocol):
    metadata: ProviderMetadata

    def track(self, event: str, payload: dict[str, Any]) -> None:
        ...
