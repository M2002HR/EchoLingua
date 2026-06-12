from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from echolingua.core.errors import ProviderError


@dataclass(frozen=True)
class ProviderSelectionPolicy:
    strategy: str = "priority"
    explicit_provider: str | None = None
    allow_fallback_on_error: bool = True
    default_provider: str | None = None

    @classmethod
    def from_config(cls, data: dict[str, Any]) -> "ProviderSelectionPolicy":
        return cls(
            strategy=str(data.get("strategy", "priority")),
            explicit_provider=data.get("explicit_provider"),
            allow_fallback_on_error=bool(data.get("allow_fallback_on_error", True)),
            default_provider=data.get("default_provider"),
        )


class ProviderSelector:
    def __init__(self, providers: list[Any], policy: ProviderSelectionPolicy, include_disabled: bool = False) -> None:
        self.providers = list(providers) if include_disabled else [provider for provider in providers if provider.metadata.enabled]
        self.policy = policy

    def ordered(self, step_provider: str | None = None) -> list[Any]:
        if not self.providers:
            raise ProviderError("No enabled providers available")
        if step_provider:
            return self._ordered_with_primary(step_provider, "Step-level provider not available")
        if self.policy.strategy == "explicit":
            if not self.policy.explicit_provider:
                raise ProviderError("Explicit provider policy requires explicit_provider")
            return self._ordered_with_primary(self.policy.explicit_provider, "Explicit provider not available")
        if self.policy.strategy == "priority":
            ordered = sorted(self.providers, key=lambda provider: provider.metadata.priority)
            if self.policy.default_provider:
                return self._ordered_with_primary(self.policy.default_provider, "Default provider not available", ordered)
            return ordered
        if self.policy.strategy == "random":
            shuffled = list(self.providers)
            random.shuffle(shuffled)
            if self.policy.default_provider:
                return self._ordered_with_primary(self.policy.default_provider, "Default provider not available", shuffled)
            return shuffled
        raise ProviderError(f"Unknown provider selection strategy: {self.policy.strategy}")

    def _ordered_with_primary(self, provider_name: str, error_prefix: str, ordered: list[Any] | None = None) -> list[Any]:
        source = ordered or self.providers
        matches = [provider for provider in source if provider.metadata.name == provider_name]
        if not matches:
            raise ProviderError(f"{error_prefix}: {provider_name}")
        others = [provider for provider in source if provider.metadata.name != provider_name]
        return matches + (others if self.policy.allow_fallback_on_error else [])
