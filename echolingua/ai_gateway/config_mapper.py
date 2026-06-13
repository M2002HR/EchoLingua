from __future__ import annotations

from urllib.parse import urlparse
from typing import Any

from echolingua.providers.tts.ajil import AJIL_REPOSITORY_URL, AJIL_SUBMODULE_PATH

def map_echolingua_to_ajil_config(config: dict[str, Any]) -> dict[str, Any]:
    """Map EchoLingua-owned config into AJIL UAG_* env vars."""
    providers_config = config.get("providers", config)
    default_config = config.get("default", {})
    ajil = ((providers_config.get("tts") or {}).get("ajil")) or {}
    parsed = urlparse(str(ajil.get("base_url", "http://127.0.0.1:8090")))
    host = parsed.hostname or "127.0.0.1"
    port = str(parsed.port or (443 if parsed.scheme == "https" else 80))
    output_format = str(ajil.get("default_response_format", "wav"))
    default_voice = str(ajil.get("default_voice", "ajil-fr-default"))
    policy = default_config.get("provider_policy", {}).get("tts", {})
    env = {
        "UAG_APP_HOST": host,
        "UAG_APP_PORT": port,
        "UAG_APP_DOCS_ENABLED": str(bool(ajil.get("docs_enabled", True))).lower(),
        "UAG_AUTH_ENABLED": str(bool(ajil.get("auth_enabled", False))).lower(),
        "UAG_AUTH_TOKEN": str(ajil.get("auth_token", "")),
        "UAG_LOG_ENABLED": str(bool(ajil.get("log_enabled", True))).lower(),
        "UAG_APP_LOG_LEVEL": str(ajil.get("log_level", "info")),
        "UAG_ROUTER_DEFAULT_STRATEGY": str(ajil.get("routing_strategy", "fallback_chain")),
        "UAG_ROUTER_DEFAULT_MODE": str(ajil.get("routing_mode", "quality_first")),
        "UAG_GROQ_TTS_DEFAULT_VOICE": default_voice,
        "UAG_GROQ_TTS_DEFAULT_RESPONSE_FORMAT": output_format,
        "ECHOLINGUA_PROVIDER_POLICY_STRATEGY": str(policy.get("strategy", "priority")),
        "ECHOLINGUA_PROVIDER_POLICY_FALLBACK": str(bool(policy.get("allow_fallback_on_error", True))).lower(),
    }
    redis_url = ajil.get("redis_url")
    if redis_url:
        env["UAG_REDIS_URL"] = str(redis_url)
    proxy_url = ajil.get("proxy_url")
    if proxy_url:
        env["UAG_PROXY_URL"] = str(proxy_url)
        env["UAG_PROXY_ENABLED"] = "true"
    return {
        "source": "echolingua",
        "repository_url": AJIL_REPOSITORY_URL,
        "submodule_path": AJIL_SUBMODULE_PATH,
        "env": env,
    }
