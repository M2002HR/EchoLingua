from pathlib import Path
import sqlite3

from echolingua.core.config import load_config
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
