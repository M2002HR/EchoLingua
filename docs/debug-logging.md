# Debug Logging Guide

## What Was Implemented

The logging layer was upgraded from a minimal event appender into a structured trace system with:

- global JSONL logs
- per-job JSONL logs
- per-trace JSONL logs
- trace summaries
- span timing
- failure serialization with traceback text
- database-backed event metadata
- provider-attempt timing and request summaries

## Event Record Shape

Every structured log record now includes the following core fields:

- `timestamp`
- `event`
- `job_id`
- `trace_id`
- `span_id`
- `parent_span_id`
- `level`
- `component`
- `operation`
- `status`
- `duration_ms`
- `payload`
- `error`
- `pid`

## Important Event Families

### Trace events

- `trace_started`
- `trace_finished`

These bracket the full run and write the summary artifact at the end.

### Span events

- `span_started`
- `span_finished`

These show detailed stage boundaries and duration breakdowns.

### Pipeline events

- `job_started`
- `job_progress`
- `plan_built`
- `audio_generated`
- `folder_generated`
- `job_failed`

### Provider-level events

Provider attempts are currently recorded primarily in SQLite with:

- provider name
- provider kind
- status
- error message
- duration
- cache key
- request summary

The surrounding spans in JSONL show where those attempts happened in the full trace.

## Summary Artifact Contents

Each summary JSON contains:

- trace metadata
- operation name
- final status
- wall-clock duration
- event count
- level counts
- status counts
- operation timing aggregates
- failure list
- final error payload
- custom summary data
- artifact references
- path to the trace JSONL file

This file is the fastest way to inspect a run after tests or manual smoke checks.

## Where to Look First During Debugging

### When a run fails

1. Open `logs/jobs/<job_id>/latest-summary.json`.
2. Check:
   - `status`
   - `error`
   - `failures`
   - `operation_stats`
3. If needed, open the referenced `trace_path`.
4. Correlate with SQLite:
   - `job_events`
   - `provider_attempts`
   - `audio_outputs`

### When a run is slow

Inspect `operation_stats` in the summary file.

Useful operations include:

- `pipeline.load_csv`
- `pipeline.validate_csv`
- `pipeline.build_plan`
- `pipeline.render_audio`
- `audio_builder.provider_attempt`
- `audio_builder.export_audio`
- `pipeline.write_manifest`

### When provider behavior is suspicious

Check SQLite `provider_attempts` for:

- repeated failures
- fallback chains
- excessive latency
- low cache-hit ratio

## CLI Commands for Inspection

Tail global JSONL logs:

```bash
echolingua logs tail --lines 50
```

Read the most recent summary for a job:

```bash
echolingua logs summary <job_id>
```

Read general runtime stats:

```bash
echolingua stats
echolingua cache-stats
```

## Example Debugging Workflow

1. Run a generation command with a known `job_id`.
2. Reproduce the issue.
3. Read `logs/jobs/<job_id>/latest-summary.json`.
4. Identify the slowest or failed operation.
5. Open `logs/jobs/<job_id>/events.jsonl` for the exact sequence.
6. Query SQLite if cross-run comparison is needed.
7. Fix the bug or bottleneck.
8. Re-run with the same scenario and compare summaries.

## Practical Notes

- `latest-summary.json` is overwritten for repeated runs with the same job id.
- `summary-<trace_id>.json` remains as the immutable trace-specific artifact.
- Telegram service operations also emit traces, including import/export and per-sentence generation.
- Failures now preserve traceback text so root-cause inspection does not depend on reproducing the crash immediately.
