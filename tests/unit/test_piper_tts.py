from pathlib import Path

import pytest

from echolingua.core.errors import ProviderError
from echolingua.providers.tts.base import TTSRequest
from echolingua.providers.tts.piper import PiperTTSProvider


def test_piper_tts_requires_model_configuration(tmp_path: Path) -> None:
    provider = PiperTTSProvider(config={"default_voice": "fr_FR-upmc-medium"})
    with pytest.raises(ProviderError, match="not configured yet"):
        provider.synthesize(
            TTSRequest(text="Bonjour", voice="fr_FR-upmc-medium", language="fr"),
            tmp_path / "piper.wav",
        )


def test_piper_tts_reports_placeholder_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider = PiperTTSProvider(
        config={
            "default_voice": "fr_FR-upmc-medium",
            "model_path": "models/piper/fr_FR-upmc-medium.onnx",
            "config_path": "models/piper/fr_FR-upmc-medium.onnx.json",
        }
    )
    monkeypatch.setattr(provider, "_runtime_available", lambda: True)
    with pytest.raises(ProviderError, match="currently a placeholder"):
        provider.synthesize(
            TTSRequest(text="Bonjour", voice="fr_FR-upmc-medium", language="fr"),
            tmp_path / "piper.wav",
        )
