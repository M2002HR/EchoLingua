from __future__ import annotations

from copy import deepcopy
from typing import Any

from echolingua.core.errors import ConfigError

SUPPORTED_PROVIDER_TYPES = {"fake", "edge", "piper", "ajil"}
SUPPORTED_PROVIDER_STRATEGIES = {"explicit", "priority", "random"}
SUPPORTED_OUTPUT_FORMATS = {"mp3", "wav"}
SUPPORTED_TEXT_FIELDS = {"persian", "english", "french", "target"}
SUPPORTED_SEGMENT_KINDS = {"tts", "silence"}


def validate_app_config(
    default_config: dict[str, Any],
    providers_config: dict[str, Any],
    recipes_config: dict[str, Any],
) -> None:
    _validate_default_config(default_config)
    _validate_providers_config(providers_config)
    _validate_global_provider_policy(default_config, providers_config)
    _validate_recipes_config(recipes_config, providers_config, default_config)


def resolve_tts_provider_policy(
    default_config: dict[str, Any],
    recipe_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = deepcopy(default_config.get("provider_policy", {}).get("tts", {}))
    if recipe_policy:
        policy.update(recipe_policy.get("tts", {}))
    return policy


def resolve_voice(provider_config: dict[str, Any], language: str | None, configured_voice: str | None) -> str:
    voices = provider_config.get("voices", {})
    if configured_voice:
        requested_voice = str(configured_voice).strip()
        if requested_voice:
            if requested_voice in voices:
                return str(voices[requested_voice])
            if requested_voice in {str(value) for value in voices.values()}:
                return requested_voice
            if _looks_like_provider_voice(str(provider_config.get("provider", "")), requested_voice):
                return requested_voice
    if language and language in voices:
        return str(voices[language])
    default_voice = provider_config.get("default_voice")
    if default_voice:
        return str(default_voice)
    raise ConfigError("TTS provider is missing a usable voice configuration.")


def _looks_like_provider_voice(provider_type: str, voice: str) -> bool:
    if provider_type == "edge":
        parts = voice.split("-")
        if len(parts) < 3:
            return False
        locale, region = parts[0], parts[1]
        if not locale.isalpha() or not region.isalpha() or locale.lower() != locale or region.upper() != region:
            return False
        return parts[-1].endswith("Neural")
    if provider_type == "piper":
        return "_" in voice and "-" in voice
    if provider_type == "fake":
        return True
    return False


def _validate_default_config(default_config: dict[str, Any]) -> None:
    paths = default_config.get("paths")
    if not isinstance(paths, dict):
        raise ConfigError("config/default.yaml is missing paths.")
    for key in ("database", "outputs", "logs", "tts_cache"):
        value = paths.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"config/default.yaml paths.{key} must be a non-empty string.")


def _validate_global_provider_policy(default_config: dict[str, Any], providers_config: dict[str, Any]) -> None:
    policy = default_config.get("provider_policy", {}).get("tts", {})
    _validate_tts_policy(policy, providers_config, "config/default.yaml provider_policy.tts")


def _validate_providers_config(providers_config: dict[str, Any]) -> None:
    tts = providers_config.get("tts")
    if not isinstance(tts, dict) or not tts:
        raise ConfigError("config/providers.yaml must define at least one tts provider.")
    enabled_count = 0
    for name, provider_config in tts.items():
        if not isinstance(provider_config, dict):
            raise ConfigError(f"Provider config for {name} must be a mapping.")
        provider_type = str(provider_config.get("provider", name))
        if provider_type not in SUPPORTED_PROVIDER_TYPES:
            raise ConfigError(
                f"Provider {name} uses unsupported provider type {provider_type!r}. "
                f"Supported types: {sorted(SUPPORTED_PROVIDER_TYPES)}."
            )
        priority = provider_config.get("priority", 100)
        if not isinstance(priority, int):
            raise ConfigError(f"Provider {name} priority must be an integer.")
        default_voice = provider_config.get("default_voice")
        if not isinstance(default_voice, str) or not default_voice.strip():
            raise ConfigError(f"Provider {name} must define default_voice.")
        voices = provider_config.get("voices", {})
        if voices is not None and not isinstance(voices, dict):
            raise ConfigError(f"Provider {name} voices must be a mapping when provided.")
        if provider_type == "piper" and bool(provider_config.get("enabled", False)):
            model_path = provider_config.get("model_path")
            config_path = provider_config.get("config_path")
            if not isinstance(model_path, str) or not model_path.strip():
                raise ConfigError(f"Provider {name} must define model_path before it can be enabled.")
            if not isinstance(config_path, str) or not config_path.strip():
                raise ConfigError(f"Provider {name} must define config_path before it can be enabled.")
        if provider_type == "ajil" and bool(provider_config.get("enabled", False)):
            base_url = provider_config.get("base_url")
            if not isinstance(base_url, str) or not base_url.strip():
                raise ConfigError(f"Provider {name} must define base_url before it can be enabled.")
        if bool(provider_config.get("enabled", False)):
            enabled_count += 1
    if enabled_count == 0:
        raise ConfigError("config/providers.yaml must enable at least one tts provider.")


def _validate_recipes_config(
    recipes_config: dict[str, Any],
    providers_config: dict[str, Any],
    default_config: dict[str, Any],
) -> None:
    recipes = recipes_config.get("recipes")
    if not isinstance(recipes, dict) or not recipes:
        raise ConfigError("config/recipes.yaml must define at least one recipe.")
    for name, recipe in recipes.items():
        if not isinstance(recipe, dict):
            raise ConfigError(f"Recipe {name} must be a mapping.")
        output_format = str(recipe.get("output_format", "mp3"))
        if output_format not in SUPPORTED_OUTPUT_FORMATS:
            raise ConfigError(f"Recipe {name} output_format must be one of {sorted(SUPPORTED_OUTPUT_FORMATS)}.")
        policy = resolve_tts_provider_policy(default_config, recipe.get("provider_policy"))
        _validate_tts_policy(policy, providers_config, f"Recipe {name} provider_policy.tts")
        segments = recipe.get("segments")
        if not isinstance(segments, list) or not segments:
            raise ConfigError(f"Recipe {name} has no segments.")
        for index, segment in enumerate(segments, start=1):
            _validate_recipe_segment(name, index, segment, providers_config)


def _validate_recipe_segment(
    recipe_name: str,
    index: int,
    segment: dict[str, Any],
    providers_config: dict[str, Any],
) -> None:
    if not isinstance(segment, dict):
        raise ConfigError(f"Recipe {recipe_name} segment {index} must be a mapping.")
    kind = str(segment.get("kind", ""))
    if kind not in SUPPORTED_SEGMENT_KINDS:
        raise ConfigError(f"Recipe {recipe_name} segment {index} kind must be one of {sorted(SUPPORTED_SEGMENT_KINDS)}.")
    if kind == "silence":
        duration_ms = segment.get("duration_ms")
        if not isinstance(duration_ms, int) or duration_ms < 0:
            raise ConfigError(f"Recipe {recipe_name} silence segment {index} must define a non-negative integer duration_ms.")
        return
    text_field = segment.get("text_field")
    if text_field not in SUPPORTED_TEXT_FIELDS:
        raise ConfigError(
            f"Recipe {recipe_name} tts segment {index} text_field must be one of {sorted(SUPPORTED_TEXT_FIELDS)}."
        )
    provider_name = segment.get("provider")
    if provider_name is not None:
        _ensure_provider_exists(str(provider_name), providers_config, f"Recipe {recipe_name} segment {index}")
    repeat = segment.get("repeat", 1)
    if not isinstance(repeat, int) or repeat < 1:
        raise ConfigError(f"Recipe {recipe_name} tts segment {index} repeat must be an integer >= 1.")
    pause_after_ms = segment.get("pause_after_ms")
    if pause_after_ms is not None and (not isinstance(pause_after_ms, int) or pause_after_ms < 0):
        raise ConfigError(f"Recipe {recipe_name} tts segment {index} pause_after_ms must be a non-negative integer.")
    split_words = segment.get("split_words", False)
    if not isinstance(split_words, bool):
        raise ConfigError(f"Recipe {recipe_name} tts segment {index} split_words must be boolean.")
    word_pause_ms = segment.get("word_pause_ms")
    if word_pause_ms is not None and (not isinstance(word_pause_ms, int) or word_pause_ms < 0):
        raise ConfigError(f"Recipe {recipe_name} tts segment {index} word_pause_ms must be a non-negative integer.")
    if word_pause_ms is not None and not split_words:
        raise ConfigError(f"Recipe {recipe_name} tts segment {index} uses word_pause_ms without split_words=true.")
    delimiter_pattern = segment.get("delimiter_pattern")
    if delimiter_pattern is not None and not isinstance(delimiter_pattern, str):
        raise ConfigError(f"Recipe {recipe_name} tts segment {index} delimiter_pattern must be a string.")


def _validate_tts_policy(policy: dict[str, Any], providers_config: dict[str, Any], label: str) -> None:
    strategy = str(policy.get("strategy", "priority"))
    if strategy not in SUPPORTED_PROVIDER_STRATEGIES:
        raise ConfigError(f"{label} strategy must be one of {sorted(SUPPORTED_PROVIDER_STRATEGIES)}.")
    explicit_provider = policy.get("explicit_provider")
    default_provider = policy.get("default_provider")
    if strategy == "explicit":
        if not explicit_provider:
            raise ConfigError(f"{label} with strategy=explicit requires explicit_provider.")
        _ensure_provider_exists(str(explicit_provider), providers_config, label)
    elif explicit_provider:
        _ensure_provider_exists(str(explicit_provider), providers_config, label)
    if default_provider:
        _ensure_provider_exists(str(default_provider), providers_config, label)


def _ensure_provider_exists(provider_name: str, providers_config: dict[str, Any], label: str) -> None:
    tts = providers_config.get("tts", {})
    if provider_name not in tts:
        raise ConfigError(f"{label} references unknown provider {provider_name!r}.")
