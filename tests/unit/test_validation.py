from pathlib import Path

import pytest

from echolingua.core.errors import ValidationError
from echolingua.sentences.loader import load_sentences, load_sentences_with_report


def test_validation_report_sample() -> None:
    sentences, report = load_sentences_with_report(Path("data/sample.csv"))
    assert len(sentences) >= 39
    assert report.total_rows >= 39
    assert report.enabled_rows >= 39
    assert report.invalid_rows == 0
    assert report.levels_summary["A0"] >= 1


def test_validation_missing_required_field(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("id,persian\n1,سلام\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_sentences(csv_path)
