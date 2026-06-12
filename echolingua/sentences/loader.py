from __future__ import annotations

import csv
from pathlib import Path

from echolingua.sentences.validator import Sentence, validate_columns


def load_sentences(path: Path, include_disabled: bool = False) -> list[Sentence]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        validate_columns(list(reader.fieldnames or []))
        sentences = [Sentence.from_row(row) for row in reader]
    if include_disabled:
        return sentences
    return [sentence for sentence in sentences if sentence.enabled]
