# EchoLingua

EchoLingua is a provider-based language-learning audio pipeline. It turns bilingual or multilingual sentence CSV files into structured shadowing and review audio, with manifests, logs, SQLite persistence, and a CLI-first workflow.

Version `0.1` focuses on a solid local pipeline:

- CSV validation and reporting
- recipe-driven AudioPlan generation
- provider routing and offline fake TTS
- cache-aware audio generation
- manifest output
- structured JSONL logs
- SQLite stats and diagnostics

## Architecture

EchoLingua owns runtime configuration and orchestration. The shared service layer lives in `echolingua.pipeline.runner.PipelineRunner`, so the CLI and future API/dashboard can use the same behavior.

Current provider-oriented building blocks:

- `TTSProvider`
- placeholder `LLMProvider`
- placeholder `ExportProvider`
- SQLite-backed storage and analytics stubs

Current TTS providers:

- `FakeTTSProvider`: deterministic offline audio for tests and local development
- `EdgeTTSProvider`: optional `edge-tts` provider
- `PiperTTSProvider`: Phase 6 placeholder for future real local/offline TTS using Piper/Wyoming Piper
- `AjilTTSProvider`: Phase 7 placeholder for future AJIL Gateway-backed TTS

AJIL integration remains a future placeholder under `echolingua/ai_gateway/`.

Current AJIL preparation includes:

- placeholder `AjilGatewayClient`
- placeholder `AjilLLMProvider`
- placeholder `AjilTTSProvider`
- config mapping into `UAG_*` environment variables
- documented future submodule target: `vendor/Ajil_Unified_AI_Gateway/`

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Optional Edge support:

```bash
python -m pip install -e ".[edge]"
```

Python support target is `3.10+`.

## Configuration

EchoLingua loads configuration from:

1. `.env`
2. `config/default.yaml`
3. `config/providers.yaml`
4. `config/recipes.yaml`

Configuration is validated during `load_config()`. Friendly `ConfigError` messages are raised when:

- required runtime paths are missing
- no TTS provider is enabled
- a provider type is unsupported
- a provider priority is not an integer
- a recipe output format is unsupported
- a recipe references an unknown provider
- a TTS segment uses an unsupported `text_field`

Important default paths:

- database: `storage/echolingua.sqlite3`
- outputs: `outputs/`
- logs: `logs/events.jsonl`
- cache: `storage/tts_cache/`

Current Piper placeholder paths in `config/providers.yaml`:

- `tts.piper.model_path`
- `tts.piper.config_path`

These are intentionally placeholders in Phase 6 and do not trigger model download or local runtime setup by themselves.

## CSV format

Required columns:

```text
id,persian,french,level,category,recommended_start
```

Supported optional columns:

```text
english,enabled,tags,notes,priority,difficulty,voice_hint,pronunciation_note
```

The current sample dataset is:

```text
data/sample.csv
```

Rows with `enabled=false`, `0`, `no`, or `off` are skipped by default.

## Recipes

Recipes live in `config/recipes.yaml`.

Current recipes:

- `shadowing_basic`
- `active_recall`
- `english_then_target`

Recipes can reference sentence fields such as:

- `persian`
- `english`
- `french`
- `target` aliasing the current target column

## Provider policy

Current TTS provider policy supports:

- `explicit`
- `priority`
- `random`

Provider resolution order is:

1. step-level `provider`
2. recipe-level `provider_policy.tts`
3. global `provider_policy.tts`
4. default provider chosen from the ordered TTS registry

Language voice resolution is config-driven. If a recipe TTS step omits `voice`, EchoLingua uses:

1. the provider's `voices.<language>` entry when present
2. otherwise the provider `default_voice`

Fallback behavior is controlled by:

```yaml
allow_fallback_on_error: true
```

Provider attempts, cache activity, and output metadata are persisted per job.

## CLI

Validate a CSV:

```bash
echolingua validate data/sample.csv
```

Dry-run a recipe without writing audio:

```bash
echolingua dry-run data/sample.csv --recipe shadowing_basic --from 1 --to 5
echolingua dry-run data/sample.csv --recipe english_then_target --from 1 --to 5
```

Generate guaranteed offline audio with fake TTS:

```bash
echolingua generate data/sample.csv --recipe shadowing_basic --from 1 --to 5 --output outputs/smoke_fake.wav
echolingua generate data/sample.csv --recipe english_then_target --from 1 --to 5 --output outputs/english_then_french_fake.wav
```

Force a specific provider for a run:

```bash
echolingua dry-run data/sample.csv --recipe shadowing_basic --from 1 --to 3 --provider edge
echolingua generate data/sample.csv --recipe shadowing_basic --from 1 --to 3 --provider edge --output outputs/edge_french.wav
echolingua generate-folder data/sample.csv outputs/edge_sentence_files --recipe shadowing_basic --from 1 --to 3 --provider edge --output-format wav
```

WAV is the guaranteed offline format. MP3 depends on local export tooling support.

Generate one file per sentence into a folder:

```bash
echolingua generate-folder data/sample.csv outputs/sentence_files --recipe shadowing_basic --from 1 --to 100
```

Provider diagnostics:

```bash
echolingua providers list
echolingua providers test fake
echolingua providers test edge
echolingua providers test piper
echolingua providers test ajil
```

`providers test piper` is expected to fail clearly for now unless you later wire a real Piper runtime into EchoLingua.
`providers test ajil` is also expected to fail clearly in Phase 7 until AJIL runtime integration is implemented.

Runtime diagnostics:

```bash
echolingua stats
echolingua cache-stats
echolingua logs tail --lines 20
```

## Logs, manifests, and SQLite

Each run has a `job_id`.

SQLite stores:

- `sentences`
- `jobs`
- `job_events`
- `provider_attempts`
- `audio_outputs`
- `tts_cache`

Structured logs are appended to:

```text
logs/events.jsonl
```

Each generated audio file gets a sibling manifest:

```text
<output>.manifest.json
```

The manifest includes job id, recipe, source CSV path, target metadata, sentence ids, output info, and rendered segment metadata.

## Testing

Quick checks:

```bash
python -m compileall echolingua tests
pytest -q
```

Detailed local workflow lives in `docs/testing.md`.

## Roadmap

Planned future work:

- richer progress reporting
- Piper preparation
- AJIL provider integration
- FastAPI backend
- dashboard
- more storage/export providers
