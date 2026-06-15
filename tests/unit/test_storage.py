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
    repos.record_event("job-1", "plan_built", {"segment_count": 1})
    repos.record_provider_attempt("job-1", "fake", "tts", "success", None)
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
