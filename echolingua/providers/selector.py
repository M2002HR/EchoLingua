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

    @classmethod
    def from_config(cls, data: dict[str, Any]) -> "ProviderSelectionPolicy":
        return cls(
            strategy=str(data.get("strategy", "priority")),
            explicit_provider=data.get("explicit_provider"),
            allow_fallback_on_error=bool(data.get("allow_fallback_on_error", True)),
        )


class ProviderSelector:
    def __init__(self, providers: list[Any], policy: ProviderSelectionPolicy) -> None:
        self.providers = [provider for provider in providers if provider.metadata.enabled]
        self.policy = policy

    def ordered(self) -> list[Any]:
        if not self.providers:
            raise ProviderError("No enabled providers available")
        if self.policy.strategy == "explicit":
            if not self.policy.explicit_provider:
                raise ProviderError("Explicit provider policy requires explicit_provider")
            matches = [p for p in self.providers if p.metadata.name == self.policy.explicit_provider]
            if not matches:
                raise ProviderError(f"Explicit provider not available: {self.policy.explicit_provider}")
            others = [p for p in self.providers if p.metadata.name != self.policy.explicit_provider]
            return matches + (others if self.policy.allow_fallback_on_error else [])
        if self.policy.strategy == "priority":
            return sorted(self.providers, key=lambda provider: provider.metadata.priority)
        if self.policy.strategy == "random":
            shuffled = list(self.providers)
            random.shuffle(shuffled)
            return shuffled
        raise ProviderError(f"Unknown provider selection strategy: {self.policy.strategy}")
