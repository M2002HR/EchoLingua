from pathlib import Path
import wave

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


def test_edge_tts_converts_mp3_to_wav(monkeypatch, tmp_path: Path) -> None:
    provider = EdgeTTSProvider()

    def fake_save_mp3(request: TTSRequest, output_path: Path) -> None:
        output_path.write_bytes(Path("tests/fixtures/edge_sample.mp3").read_bytes())

    monkeypatch.setattr(provider, "_save_mp3", fake_save_mp3)
    result = provider.synthesize(
        TTSRequest(text="Bonjour", voice="fr-FR-DeniseNeural", language="fr"),
        tmp_path / "edge.wav",
    )
    assert result.path.suffix == ".wav"
    assert result.duration_ms > 0
    with wave.open(str(result.path), "rb") as handle:
        assert handle.getnframes() > 0
