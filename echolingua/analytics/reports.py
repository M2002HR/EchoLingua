from __future__ import annotations

from typing import Any


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {"event_count": len(events)}
