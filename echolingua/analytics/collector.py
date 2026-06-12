from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnalyticsCollector:
    events: list[dict[str, Any]] = field(default_factory=list)

    def collect(self, event: str, **payload: Any) -> None:
        self.events.append({"event": event, **payload})
