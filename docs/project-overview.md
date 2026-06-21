# EchoLingua Project Overview

## Purpose

EchoLingua is a local-first language-learning audio pipeline. It converts multilingual sentence CSV files into recipe-driven audio outputs, stores runtime state in SQLite, and exposes the pipeline through both a CLI and a Telegram bot service.

## Main Runtime Components

- `echolingua.pipeline.runner.PipelineRunner`
  Central orchestration layer for validation, planning, rendering, manifest writing, persistence, and runtime logging.

- `echolingua.audio.builder.AudioBuilder`
  Renders plan segments, handles silence insertion, runs TTS provider attempts, records cache hits/misses, and exports merged audio.

- `echolingua.providers.*`
  Provider selection and concrete TTS backends. Current practical backends are `fake` and `edge`; `piper` and `ajil` are placeholders.

- `echolingua.storage.*`
  SQLite schema and repository helpers for jobs, events, provider attempts, audio outputs, cache metadata, and Telegram user data.

- `echolingua.telegram_bot.service.TelegramBotService`
  User-scoped sentence library management, Telegram imports/exports, recipe resolution, and audio generation through the same pipeline.

- `echolingua.cli`
  CLI entrypoint for validation, dry-run, generation, stats, cache inspection, and log inspection.

## High-Level Execution Flow

### CLI `generate`

1. Create or reset the job record in SQLite.
2. Start a trace session and write a `job_started` event.
3. Load CSV rows.
4. Validate the CSV report.
5. Filter sentences by optional `--from` / `--to`.
6. Build an `AudioPlan`.
7. Resolve provider defaults per TTS segment.
8. Render all plan segments.
9. Export the merged audio.
10. Write the manifest.
11. Store output metadata in SQLite.
12. Finalize the trace summary artifact.

### CLI `generate-folder`

1. Create or reset the batch job.
2. Load and validate CSV.
3. Filter sentences.
4. Iterate sentence-by-sentence:
   - build a single-sentence plan
   - render audio
   - write manifest
   - store output metadata
5. Finalize the batch summary artifact.

### Telegram sentence audio generation

1. Resolve the user settings and target sentence.
2. Resolve the effective recipe and provider.
3. Write a temporary single-sentence CSV.
4. Call `PipelineRunner.generate_sentence_files(...)`.
5. Return the generated audio path, manifest path, caption, and resolved recipe details.

## Logging and Instrumentation Coverage

The project now captures structured runtime data at these levels:

- trace session lifecycle
- span start/finish with duration
- job progress updates
- plan creation
- provider attempts
- cache hits and cache misses
- manifest creation
- output recording
- Telegram CSV import/export
- Telegram per-sentence audio generation
- exceptions with full traceback text

## Persisted Observability Outputs

### JSONL logs

- `logs/events.jsonl`
  Global append-only stream for all emitted records.

- `logs/jobs/<job_id>/events.jsonl`
  Job-scoped event stream for focused debugging.

- `logs/jobs/<job_id>/trace-<trace_id>.jsonl`
  Full trace-local event stream.

### Summary artifacts

- `logs/jobs/<job_id>/summary-<trace_id>.json`
  Immutable summary for a specific trace.

- `logs/jobs/<job_id>/latest-summary.json`
  Most recent summary for that job id.

### SQLite

- `jobs`
- `job_events`
- `provider_attempts`
- `audio_outputs`
- `tts_cache`

The SQLite layer now stores status, component, operation, duration, trace ids, span ids, error payloads, provider attempt timing, cache keys, and request summaries.

## Design Intent

This implementation is optimized for postmortem debugging and operational improvement:

- reconstruct exact execution order
- detect slow stages and slow providers
- inspect failure locations with traceback context
- compare cache effectiveness across runs
- query job history from SQLite
- inspect raw event streams or summarized artifacts depending on depth needed
