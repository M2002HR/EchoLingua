from pathlib import Path

import pytest

from echolingua.core.errors import ValidationError
from echolingua.sentences.loader import load_sentences


def test_load_sentences_sample() -> None:
    sentences = load_sentences(Path("data/sample.csv"))
    assert len(sentences) >= 39
    assert sentences[0].persian == "سلام."
    assert sentences[0].english == "Hello."
    assert sentences[0].french == "Salut."
    assert sentences[0].recommended_start == "day_1"
    assert sentences[0].tags == ["starter", "daily"]


def test_csv_validation_missing_required(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("id,persian\n1,سلام\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_sentences(csv_path)
