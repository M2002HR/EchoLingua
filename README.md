# EchoLingua

EchoLingua is a provider-based language-learning pipeline that converts bilingual sentence CSV files into personalized audio for shadowing, active recall, listening practice, gym mode, pronunciation drills, and future learning workflows.

Version `0.1` focuses on the backend foundation: CSV validation, recipe loading, AudioPlan generation, provider selection, TTS synthesis, audio assembly, manifests, structured logs, and SQLite persistence.

## Architecture

EchoLingua owns runtime configuration and orchestration. CLI commands and future API/dashboard entry points share the same service layer in `echolingua.pipeline.runner.PipelineRunner`.

Major capabilities are provider-based:

- `TTSProvider` for speech synthesis.
- `LLMProvider` placeholder category for future AI workflows.
- `ExportProvider` placeholder category for future exports.
- `StorageProvider` represented initially by SQLite storage.
- `AnalyticsProvider` represented initially by lightweight analytics stubs.

The initial TTS providers are:

- `FakeTTSProvider`: local deterministic placeholder audio for tests and offline development.
- `EdgeTTSProvider`: optional `edge-tts` provider. It is a Python dependency, not a git submodule.

## Future AJIL integration

AJIL Unified AI Gateway is intentionally not implemented in v0.1. EchoLingua includes placeholder interfaces under `echolingua/ai_gateway/` so a future git submodule can be mounted at `vendor/Ajil_Unified_AI_Gateway`.

Submodules must not own EchoLingua runtime configuration. EchoLingua config will later map into AJIL environment/config values through a mapper layer.

## Setup

EchoLingua requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Optional Edge TTS support:

```bash
pip install -e '.[edge]'
```

Copy environment defaults when needed:

```bash
cp .env.example .env
```

## Configuration

EchoLingua loads configuration from:

1. `.env`
2. `config/default.yaml`
3. `config/providers.yaml`
4. `config/recipes.yaml`

Important paths in `config/default.yaml`:

- SQLite database: `storage/echolingua.sqlite3`
- generated audio: `outputs/`
- structured JSONL logs: `logs/`
- TTS cache: `storage/tts_cache/`

## CSV format

Required columns:

```text
id,persian,french,level,category,recommended_start
```

Optional columns:

```text
enabled,tags,notes,priority,difficulty,voice_hint,pronunciation_note
```

A sample CSV is available at:

```text
data/french_100_sentences_mohammad.csv
```

Rows with `enabled=false`, `0`, `no`, or `off` are skipped by default.

## Recipes

Recipes live in `config/recipes.yaml`. A recipe defines ordered segments. Segment kinds supported in v0.1 are:

- `tts`: render a sentence field such as `persian` or `french`.
- `silence`: add a pause in milliseconds.

Included recipes:

- `shadowing_basic`
- `active_recall`

## Provider policy

Provider selection is policy-based, not only fallback-based. v0.1 supports:

- `explicit`: choose a configured provider by name.
- `priority`: sort enabled providers by priority.
- `random`: shuffle enabled providers.

Fallback after provider error is controlled by:

```yaml
allow_fallback_on_error: true
```

Every provider attempt is stored in SQLite and can be logged with the active `job_id`.

## CLI

Dry run without generating audio:

```bash
echolingua dry-run data/french_100_sentences_mohammad.csv --recipe shadowing_basic
```

Generate final MP3 using the configured providers:

```bash
echolingua generate data/french_100_sentences_mohammad.csv --recipe shadowing_basic
```

List providers:

```bash
echolingua providers list
```

Test a provider locally:

```bash
echolingua providers test --name fake --text Bonjour
```

## Logs, storage, and manifests

Each pipeline run has a `job_id`. The runner stores:

- `sentences`
- `jobs`
- `job_events`
- `provider_attempts`
- `audio_outputs`
- `tts_cache`

Structured events are appended to `logs/events.jsonl`.

Every generated audio file gets a sibling manifest named like:

```text
<output>.manifest.json
```

The manifest includes schema version, creation timestamp, job id, recipe name, output path, output duration, segment count, and rendered segment metadata.

## Testing

```bash
pytest
```

Unit tests use `FakeTTSProvider`; they do not call real TTS services or the internet.


## Development Workflow

EchoLingua is currently a personal project, so direct commits to the current branch are the default workflow. Pull requests are optional and should be reserved for high-risk changes or cases where a review branch is explicitly requested.

Use conventional commit messages, keep runtime configuration owned by EchoLingua, and keep AJIL integration behind interfaces/config until it is explicitly implemented. Unit tests must not make real network calls; use fake providers for provider-dependent tests.

Before every commit, run:

```bash
python -m compileall echolingua tests
pytest -q
```

For detailed setup, CLI smoke tests, generated audio checks, manifest inspection, SQLite inspection, cache verification, provider checks, and troubleshooting, see [docs/testing.md](docs/testing.md).

## Roadmap

Planned future work:

- API service for dashboard use.
- React dashboard.
- AJIL Unified AI Gateway submodule integration.
- LLM-assisted sentence enrichment and drills.
- Telegram delivery.
- Rich analytics and learner progress reporting.
- Additional export and storage providers.
