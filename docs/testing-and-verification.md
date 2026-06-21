# Testing and Verification

## Automated Validation Performed

The logging implementation was verified with:

```bash
python3 -m compileall echolingua
pytest -q tests/unit/test_runner.py tests/unit/test_storage.py tests/unit/test_telegram_service.py
pytest -q
```

Result at implementation time:

- `51 passed`

## What The Tests Now Cover

- trace summaries are written for successful jobs
- trace summaries are written for failed jobs
- per-job log artifacts are retrievable
- storage schema changes remain compatible
- provider attempt metadata can store duration and request summaries
- Telegram import/export and audio generation still behave correctly
- existing pipeline behavior still passes all unit tests

## Recommended Manual Smoke Tests

### Validation

```bash
echolingua validate data/sample.csv
```

### Dry-run

```bash
echolingua dry-run data/sample.csv --recipe shadowing_basic --from 1 --to 3
```

### Single output generation

```bash
echolingua generate data/sample.csv --recipe shadowing_basic --from 1 --to 3 --output outputs/manual_check.wav
```

### Folder generation

```bash
echolingua generate-folder data/sample.csv outputs/manual_folder --recipe shadowing_basic --from 1 --to 3
```

### Log inspection after a run

```bash
echolingua logs tail --lines 30
echolingua logs summary <job_id>
```

### Runtime inspection

```bash
echolingua stats
echolingua cache-stats
```

## Recommended Post-Run Review Checklist

After every important manual test, inspect:

1. `logs/jobs/<job_id>/latest-summary.json`
2. `logs/jobs/<job_id>/events.jsonl`
3. the generated manifest next to the output file
4. SQLite `provider_attempts`
5. SQLite `job_events`

Questions to answer during review:

- Did the run complete or fail?
- Which operation took the most time?
- Was provider fallback triggered?
- Did cache hits happen as expected?
- Did the produced manifest match the intended sentence range and recipe?
- Was the error captured with enough detail to fix it quickly?

## Suggested SQL Queries

Inspect recent job events:

```sql
SELECT job_id, event_name, event_status, component, operation, duration_ms, created_at
FROM job_events
ORDER BY id DESC
LIMIT 50;
```

Inspect recent provider attempts:

```sql
SELECT job_id, provider_name, status, duration_ms, cache_key, error_message, created_at
FROM provider_attempts
ORDER BY id DESC
LIMIT 50;
```

Inspect failed jobs:

```sql
SELECT job_id, recipe_name, status, error_message, created_at, completed_at
FROM jobs
WHERE status = 'failed'
ORDER BY created_at DESC;
```

## Operational Outcome

The project now produces enough runtime evidence to support:

- exact sequencing of what happened
- identification of slow stages
- identification of failing stages
- provider behavior analysis
- cache effectiveness analysis
- reliable postmortem debugging without relying only on terminal output
