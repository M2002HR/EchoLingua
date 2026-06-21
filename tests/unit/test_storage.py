from pathlib import Path

from echolingua.audio.cache import tts_cache_key
from echolingua.core.config import load_config
from echolingua.providers.tts.base import TTSRequest
from echolingua.storage.db import Database
from echolingua.storage.repositories import StorageRepositories


def test_storage_stats_and_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(Path(".").resolve())
    config = load_config()
    config = type(config)(
        root_dir=tmp_path,
        default=config.default,
        providers=config.providers,
        recipes=config.recipes,
    )
    db = Database(config.db_path)
    db.initialize()
    repos = StorageRepositories(db)
    repos.create_job("job-1", "shadowing_basic")
    repos.record_event(
        "job-1",
        "plan_built",
        {"segment_count": 1},
        status="completed",
        component="pipeline.runner",
        operation="pipeline.build_plan",
        duration_ms=15,
        trace_id="trace-1",
        span_id="span-1",
    )
    repos.record_provider_attempt(
        "job-1",
        "fake",
        "tts",
        "success",
        None,
        duration_ms=12,
        cache_key="cache-1",
        request_summary={"text_length": 7},
    )
    output = tmp_path / "out.wav"
    output.write_bytes(b"123")
    repos.record_audio_output("job-1", output, tmp_path / "out.wav.manifest.json", 123)
    request = TTSRequest(text="Bonjour", voice="fake-fr", language="fr")
    repos.upsert_tts_cache(tts_cache_key("fake", request), "fake", request, output, 123)
    stats = repos.stats_summary()
    cache_stats = repos.cache_stats_summary()
    repos.update_job_progress("job-1", "rendering_segments", "Rendering", 3, 10)
    repos.complete_job("job-1", total_steps=10)
    assert stats.total_jobs == 1
    assert stats.successful_jobs == 0
    assert stats.total_provider_attempts == 1
    assert stats.provider_attempts_by_provider["fake"] == 1
    assert stats.generated_audio_outputs == 1
    assert stats.latest_job["job_id"] == "job-1"
    assert cache_stats.entry_count == 1


def test_storage_telegram_user_settings_and_sentence_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(Path(".").resolve())
    config = load_config()
    config = type(config)(
        root_dir=tmp_path,
        default=config.default,
        providers=config.providers,
        recipes=config.recipes,
    )
    db = Database(config.db_path)
    db.initialize()
    repos = StorageRepositories(db)
    repos.upsert_telegram_user(
        telegram_user_id=12345,
        chat_id=999,
        username="demo_user",
        first_name="Demo",
        last_name="User",
        language_code="fa",
    )
    settings = repos.get_telegram_user_settings(12345)
    assert settings.selected_recipe == "persian_prompt_french_ladder"
    assert settings.selected_provider == "edge"
    repos.update_telegram_user_settings(12345, output_format="mp3", extra_config={"page_size": 5})
    updated = repos.get_telegram_user_settings(12345)
    assert updated.output_format == "mp3"
    assert updated.extra_config()["page_size"] == 5
    repos.add_user_sentences(12345, ["1", "2", "3"])
    assert repos.list_user_sentence_ids(12345) == ["1", "2", "3"]
    repos.remove_user_sentence(12345, "2")
    assert repos.list_user_sentence_ids(12345) == ["1", "3"]
    repos.record_telegram_csv_import(12345, "sample.csv", tmp_path / "sample.csv", ["1", "3"])


def test_storage_library_categories_and_activity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(Path(".").resolve())
    config = load_config()
    config = type(config)(
        root_dir=tmp_path,
        default=config.default,
        providers=config.providers,
        recipes=config.recipes,
    )
    db = Database(config.db_path)
    db.initialize()
    repos = StorageRepositories(db)
    repos.upsert_telegram_user(
        telegram_user_id=555,
        chat_id=555,
        username="cats",
        first_name="Cat",
        last_name="User",
        language_code="fa",
    )
    repos.ensure_telegram_library_category(555, "travel", "Travel", target_language="fr", description="Travel items")
    repos.add_sentences_to_category(555, "travel", ["1", "2", "10"], source_type="csv_import")
    repos.record_category_activity(555, "travel", recipe_name="shadowing_basic", action="generate_all", target_language="fr")
    listed = repos.list_telegram_library_categories(555)
    assert len(listed) == 1
    assert listed[0].display_name == "Travel"
    assert repos.list_category_sentence_ids(555, "travel") == ["1", "2", "10"]
    assert repos.category_sentence_counts(555)["travel"] == 3
    assert repos.list_category_activity_counts(555, "travel", group_by="recipe_name")["shadowing_basic"] == 1


def test_storage_user_sentence_ids_are_sorted_numerically(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(Path(".").resolve())
    config = load_config()
    config = type(config)(
        root_dir=tmp_path,
        default=config.default,
        providers=config.providers,
        recipes=config.recipes,
    )
    db = Database(config.db_path)
    db.initialize()
    repos = StorageRepositories(db)
    repos.upsert_telegram_user(
        telegram_user_id=77,
        chat_id=77,
        username="sorter",
        first_name="Sort",
        last_name="Tester",
        language_code="fa",
    )
    repos.add_user_sentences(77, ["1", "10", "100", "11", "2"])
    assert repos.list_user_sentence_ids(77) == ["1", "2", "10", "11", "100"]


def test_storage_telegram_user_recipes_crud(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(Path(".").resolve())
    config = load_config()
    config = type(config)(
        root_dir=tmp_path,
        default=config.default,
        providers=config.providers,
        recipes=config.recipes,
    )
    db = Database(config.db_path)
    db.initialize()
    repos = StorageRepositories(db)
    repos.upsert_telegram_user(
        telegram_user_id=88,
        chat_id=88,
        username="recipe_user",
        first_name="Recipe",
        last_name="Tester",
        language_code="fa",
    )
    repos.upsert_telegram_user_recipe(
        telegram_user_id=88,
        recipe_key="my_recipe",
        display_name="My Recipe",
        recipe_kind="guided",
        template_key="ladder",
        recipe_data={"name": "My Recipe", "pause_between_ms": 1200},
    )
    listed = repos.list_telegram_user_recipes(88)
    assert len(listed) == 1
    assert listed[0].recipe_key == "my_recipe"
    fetched = repos.get_telegram_user_recipe(88, "my_recipe")
    assert fetched is not None
    assert fetched.recipe_data()["pause_between_ms"] == 1200
    repos.delete_telegram_user_recipe(88, "my_recipe")
    assert repos.get_telegram_user_recipe(88, "my_recipe") is None
