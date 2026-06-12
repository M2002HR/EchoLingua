from pathlib import Path

from echolingua.pipeline.manifest import write_manifest
from echolingua.recipes.planner import AudioPlan


def test_manifest_generation(tmp_path: Path) -> None:
    plan = AudioPlan(
        job_id="job-1",
        recipe_name="shadowing_basic",
        output_format="mp3",
        source_csv_path="data/sample.csv",
        target_language="fr",
        target_column="french",
        selected_sentence_ids=["1", "2"],
        segments=[],
    )
    path = tmp_path / "out.mp3.manifest.json"
    manifest = write_manifest(plan, {"path": "out.mp3", "duration_ms": 1000, "segments": []}, path)
    assert path.exists()
    assert manifest["job_id"] == "job-1"
    assert manifest["output"]["duration_ms"] == 1000
    assert manifest["source_csv_path"] == "data/sample.csv"
    assert manifest["target_column"] == "french"
