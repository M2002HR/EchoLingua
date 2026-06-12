from __future__ import annotations

from typing import Any


def map_echolingua_to_ajil_config(config: dict[str, Any]) -> dict[str, Any]:
    """Future mapper from EchoLingua-owned runtime config to AJIL gateway config."""
    return {"source": "echolingua", "config": config}
