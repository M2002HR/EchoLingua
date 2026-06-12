from pathlib import Path

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
