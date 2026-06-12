from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echolingua.recipes.planner import AudioPlan


def build_manifest(plan: AudioPlan, output_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "job_id": plan.job_id,
        "recipe_name": plan.recipe_name,
        "source_csv_path": plan.source_csv_path,
        "target_language": plan.target_language,
        "target_column": plan.target_column,
        "selected_sentence_ids": plan.selected_sentence_ids,
        "output": {"path": output_info["path"], "duration_ms": output_info["duration_ms"]},
        "segment_count": len(plan.segments),
        "segments": output_info.get("segments", []),
    }


def write_manifest(plan: AudioPlan, output_info: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    manifest = build_manifest(plan, output_info)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
