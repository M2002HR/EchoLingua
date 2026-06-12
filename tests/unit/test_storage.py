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
    assert cache_stats.entry_count == 1
