from pathlib import Path

import pytest

from echolingua.ai_gateway.ajil_client import AjilGatewayClient, AjilGatewaySettings
from echolingua.ai_gateway.config_mapper import map_echolingua_to_ajil_config
from echolingua.ai_gateway.llm_provider import AjilLLMProvider
from echolingua.core.errors import ProviderError
from echolingua.providers.tts.ajil import AjilTTSProvider
from echolingua.providers.tts.base import TTSRequest


def test_map_echolingua_to_ajil_config_maps_uag_envs() -> None:
    payload = map_echolingua_to_ajil_config(
        {
            "default": {
                "provider_policy": {
                    "tts": {
                        "strategy": "priority",
                        "allow_fallback_on_error": True,
                    }
                }
            },
            "providers": {
                "tts": {
                    "ajil": {
                        "base_url": "http://127.0.0.1:8090",
                        "default_voice": "ajil-fr-default",
                        "default_response_format": "wav",
                        "routing_strategy": "fallback_chain",
                        "routing_mode": "quality_first",
                        "auth_enabled": False,
                    }
                }
            },
        }
    )
    env = payload["env"]
    assert payload["repository_url"].endswith("Ajil_Unified_AI_Gateway.git")
    assert payload["submodule_path"] == "vendor/Ajil_Unified_AI_Gateway/"
    assert env["UAG_APP_HOST"] == "127.0.0.1"
    assert env["UAG_APP_PORT"] == "8090"
    assert env["UAG_ROUTER_DEFAULT_STRATEGY"] == "fallback_chain"
    assert env["UAG_GROQ_TTS_DEFAULT_VOICE"] == "ajil-fr-default"


def test_ajil_gateway_client_fails_clearly() -> None:
    client = AjilGatewayClient(AjilGatewaySettings(base_url="http://127.0.0.1:8090"))
    with pytest.raises(ProviderError, match="Phase 7 placeholder"):
        client.tts_request(text="Bonjour", voice="ajil-fr-default", language="fr")


def test_ajil_llm_provider_fails_clearly() -> None:
    provider = AjilLLMProvider(config={"model": "gpt-4o-mini"})
    with pytest.raises(ProviderError, match="AjilLLMProvider is a Phase 7 placeholder"):
        provider.complete("Translate this sentence.")


def test_ajil_tts_provider_fails_clearly(tmp_path: Path) -> None:
    provider = AjilTTSProvider(config={"base_url": "http://127.0.0.1:8090"})
    with pytest.raises(ProviderError, match="AjilTTSProvider is a Phase 7 placeholder"):
        provider.synthesize(
            TTSRequest(text="Bonjour", voice="ajil-fr-default", language="fr"),
            tmp_path / "ajil.wav",
        )
