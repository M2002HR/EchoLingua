from pathlib import Path

import pytest

from echolingua.core.errors import ProviderError
from echolingua.providers.tts.base import TTSRequest
from echolingua.providers.tts.edge import EdgeTTSProvider


def test_edge_tts_missing_dependency(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None if name == "edge_tts" else object())
    with pytest.raises(ProviderError, match="edge-tts is not installed"):
        EdgeTTSProvider().synthesize(
            TTSRequest(text="Bonjour", voice="fr-FR-DeniseNeural", language="fr"),
            tmp_path / "edge.wav",
        )
