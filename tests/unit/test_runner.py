from pathlib import Path
import sqlite3

import pytest

from echolingua.core.config import load_config
from echolingua.core.errors import ProviderError
from echolingua.pipeline.runner import PipelineRunner


def test_plan_summary_uses_sample_csv(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(Path("/home/mhr/Code/EchoLingua"))
    base = load_config()
    config = type(base)(
        root_dir=tmp_path,
        default=base.default,
        providers=base.providers,
        recipes=base.recipes,
    )
    runner = PipelineRunner(config)
    summary = runner.build_plan_summary(
        "job-1",
        Path("/home/mhr/Code/EchoLingua/data/sample.csv"),
        "english_then_target",
        from_sentence_id="1",
        to_sentence_id="2",
    )
    assert summary["sentence_count"] == 2
    assert summary["tts_segment_count"] == 6
    assert summary["target_column"] == "french"
    assert summary["fields_used"] == ["english", "target"]
    assert summary["provider_policy"]["default_provider"] == "fake"


def test_generate_records_progress_events(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(Path("/home/mhr/Code/EchoLingua"))
    base = load_config()
    config = type(base)(
        root_dir=tmp_path,
        default=base.default,
        providers=base.providers,
        recipes=base.recipes,
    )
    runner = PipelineRunner(config)
    result = runner.generate(
        "job-progress-1",
        Path("/home/mhr/Code/EchoLingua/data/sample.csv"),
        "shadowing_basic",
        output_path=tmp_path / "progress.wav",
    )
    assert Path(result["output"]["path"]).exists()
    conn = sqlite3.connect(config.db_path)
    stages = [row[0] for row in conn.execute("SELECT current_stage FROM jobs WHERE job_id='job-progress-1'").fetchall()]
    assert stages == ["finished"]
    event_names = [row[0] for row in conn.execute("SELECT event_name FROM job_events WHERE job_id='job-progress-1'").fetchall()]
    assert "job_progress" in event_names


def test_generate_sentence_files_creates_one_file_per_sentence(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(Path("/home/mhr/Code/EchoLingua"))
    base = load_config()
    config = type(base)(
        root_dir=tmp_path,
        default=base.default,
        providers=base.providers,
        recipes=base.recipes,
    )
    runner = PipelineRunner(config)
    result = runner.generate_sentence_files(
        "job-folder-1",
        Path("/home/mhr/Code/EchoLingua/data/sample.csv"),
        "shadowing_basic",
        tmp_path / "sentence_outputs",
        output_format="wav",
        from_sentence_id="1",
        to_sentence_id="3",
    )
    assert result["file_count"] == 3
    files = result["files"]
    assert len(files) == 3
    assert Path(files[0]["output"]).exists()
    assert Path(files[1]["output"]).exists()
    assert Path(files[2]["output"]).exists()
    assert Path(files[0]["manifest"]).exists()


def test_plan_summary_provider_override_uses_requested_provider(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(Path("/home/mhr/Code/EchoLingua"))
    base = load_config()
    config = type(base)(
        root_dir=tmp_path,
        default=base.default,
        providers=base.providers,
        recipes=base.recipes,
    )
    runner = PipelineRunner(config)
    summary = runner.build_plan_summary(
        "job-edge-1",
        Path("/home/mhr/Code/EchoLingua/data/sample.csv"),
        "shadowing_basic",
        from_sentence_id="1",
        to_sentence_id="1",
        provider_name="edge",
    )
    assert summary["provider_policy"]["strategy"] == "explicit"
    assert summary["provider_policy"]["explicit_provider"] == "edge"
    assert summary["selected_providers"] == ["edge"]


def test_list_providers_include_placeholder_backends(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(Path("/home/mhr/Code/EchoLingua"))
    base = load_config()
    config = type(base)(
        root_dir=tmp_path,
        default=base.default,
        providers=base.providers,
        recipes=base.recipes,
    )
    rows = PipelineRunner(config).list_providers("tts")
    names = {row["name"]: row for row in rows}
    assert "piper" in names
    assert "ajil" in names
    assert names["piper"]["provider_type"] == "piper"
    assert names["ajil"]["provider_type"] == "ajil"
    assert names["piper"]["enabled"] is False
    assert names["ajil"]["enabled"] is False


def test_provider_test_piper_fails_clearly(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(Path("/home/mhr/Code/EchoLingua"))
    monkeypatch.setattr("echolingua.providers.tts.piper.PiperTTSProvider._runtime_available", lambda self: False)
    base = load_config()
    config = type(base)(
        root_dir=tmp_path,
        default=base.default,
        providers=base.providers,
        recipes=base.recipes,
    )
    runner = PipelineRunner(config)
    with pytest.raises(ProviderError, match="Piper runtime is not available"):
        runner.test_provider("piper")


def test_provider_test_ajil_fails_clearly(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(Path("/home/mhr/Code/EchoLingua"))
    base = load_config()
    config = type(base)(
        root_dir=tmp_path,
        default=base.default,
        providers=base.providers,
        recipes=base.recipes,
    )
    runner = PipelineRunner(config)
    with pytest.raises(ProviderError, match="AjilTTSProvider is a Phase 7 placeholder"):
        runner.test_provider("ajil")
