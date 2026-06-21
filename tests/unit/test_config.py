from copy import deepcopy
from pathlib import Path

import pytest

from echolingua.core.config import load_config
from echolingua.core.config_validation import resolve_tts_provider_policy, resolve_voice, validate_app_config
from echolingua.core.errors import ConfigError
from echolingua.pipeline.runner import PipelineRunner

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_load_config_validates_recipe_policy() -> None:
    config = load_config()
    recipe = config.recipes["recipes"]["shadowing_basic"]
    assert recipe["provider_policy"]["tts"]["default_provider"] == "fake"


def test_validate_app_config_rejects_unknown_explicit_provider() -> None:
    config = load_config()
    recipes = deepcopy(config.recipes)
    recipes["recipes"]["shadowing_basic"]["provider_policy"]["tts"]["explicit_provider"] = "missing"
    recipes["recipes"]["shadowing_basic"]["provider_policy"]["tts"]["strategy"] = "explicit"
    with pytest.raises(ConfigError, match="unknown provider"):
        validate_app_config(config.default, config.providers, recipes)


def test_validate_app_config_rejects_invalid_segment_text_field() -> None:
    config = load_config()
    recipes = deepcopy(config.recipes)
    recipes["recipes"]["shadowing_basic"]["segments"][0]["text_field"] = "german"
    with pytest.raises(ConfigError, match="text_field"):
        validate_app_config(config.default, config.providers, recipes)


def test_validate_app_config_rejects_enabled_piper_without_paths() -> None:
    config = load_config()
    providers = deepcopy(config.providers)
    providers["tts"]["piper"]["enabled"] = True
    providers["tts"]["piper"]["model_path"] = ""
    with pytest.raises(ConfigError, match="model_path"):
        validate_app_config(config.default, providers, config.recipes)


def test_validate_app_config_rejects_word_pause_without_split_words() -> None:
    config = load_config()
    recipes = deepcopy(config.recipes)
    recipes["recipes"]["shadowing_basic"]["segments"][0]["word_pause_ms"] = 500
    with pytest.raises(ConfigError, match="word_pause_ms without split_words=true"):
        validate_app_config(config.default, config.providers, recipes)


def test_resolve_tts_provider_policy_prefers_recipe_values() -> None:
    default = {
        "provider_policy": {
            "tts": {
                "strategy": "priority",
                "allow_fallback_on_error": True,
                "default_provider": "edge",
            }
        }
    }
    recipe_policy = {
        "tts": {
            "strategy": "explicit",
            "explicit_provider": "fake",
            "allow_fallback_on_error": False,
        }
    }
    resolved = resolve_tts_provider_policy(default, recipe_policy)
    assert resolved == {
        "strategy": "explicit",
        "allow_fallback_on_error": False,
        "default_provider": "edge",
        "explicit_provider": "fake",
    }


def test_resolve_voice_uses_language_map_then_default() -> None:
    provider = {"voices": {"fr": "fake-fr", "en": "fake-en"}, "default_voice": "fake-neutral"}
    assert resolve_voice(provider, "fr", None) == "fake-fr"
    assert resolve_voice(provider, "de", None) == "fake-neutral"
    assert resolve_voice(provider, "fr", "manual-voice") == "manual-voice"


def test_runner_recipe_policy_and_voice_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(PROJECT_ROOT)
    base = load_config()
    recipes = deepcopy(base.recipes)
    recipes["recipes"]["shadowing_basic"]["provider_policy"]["tts"]["strategy"] = "explicit"
    recipes["recipes"]["shadowing_basic"]["provider_policy"]["tts"]["explicit_provider"] = "fake"
    recipes["recipes"]["shadowing_basic"]["provider_policy"]["tts"]["allow_fallback_on_error"] = False
    config = type(base)(
        root_dir=tmp_path,
        default=base.default,
        providers=base.providers,
        recipes=recipes,
    )
    runner = PipelineRunner(config)
    plan = runner.build_plan(
        "job-policy-1",
        PROJECT_ROOT / "data/sample.csv",
        "shadowing_basic",
        from_sentence_id="1",
        to_sentence_id="1",
    )
    assert all(segment.provider == "fake" for segment in plan.segments if segment.kind == "tts")
    voices = [segment.voice for segment in plan.segments if segment.kind == "tts"]
    assert voices == ["fake-fa", "fake-fr", "fake-fr"]
    summary = runner.build_plan_summary(
        "job-policy-2",
        PROJECT_ROOT / "data/sample.csv",
        "shadowing_basic",
        from_sentence_id="1",
        to_sentence_id="1",
    )
    assert summary["provider_policy"]["strategy"] == "explicit"
    assert summary["provider_policy"]["explicit_provider"] == "fake"
