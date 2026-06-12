from __future__ import annotations

import csv
from pathlib import Path

from echolingua.core.errors import ValidationError
from echolingua.sentences.validator import Sentence, SentenceValidationReport, build_validation_report, validate_columns


def load_sentences(path: Path, include_disabled: bool = False) -> list[Sentence]:
    sentences, report = load_sentences_with_report(path, include_disabled=True)
    if not report.is_valid:
        if report.issues:
            raise ValidationError(report.issues[0].message)
        raise ValidationError("CSV validation failed.")
    if include_disabled:
        return sentences
    return [sentence for sentence in sentences if sentence.enabled]


def load_sentences_with_report(path: Path, include_disabled: bool = False) -> tuple[list[Sentence], SentenceValidationReport]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        validate_columns(list(reader.fieldnames or []))
        rows = [dict(row) for row in reader]
    sentences, report = build_validation_report(rows)
    if include_disabled:
        return sentences, report
    return [sentence for sentence in sentences if sentence.enabled], report
