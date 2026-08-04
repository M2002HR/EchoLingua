# EchoLingua

**A configurable multilingual audio-generation pipeline for shadowing, active recall, and pronunciation practice.**

EchoLingua transforms bilingual or multilingual CSV datasets into structured learning audio. It uses recipe-driven generation, provider routing, caching, manifests, JSONL logs, SQLite persistence, and a CLI-first architecture that can also support future API and dashboard clients.

## Engineering highlights

- Config-driven audio recipes instead of hard-coded lesson logic
- Provider abstraction for local, remote, and test TTS backends
- Deterministic offline fake TTS for reliable tests
- Optional Edge TTS integration
- Cache-aware generation and persisted job metadata
- CSV validation with friendly error reporting
- Structured manifests, JSONL events, and SQLite statistics
- Telegram-bot foundation for user-managed workflows
- Shared pipeline runner reusable by CLI and future interfaces

## Technology

`Python` · `CLI` · `SQLite` · `YAML` · `CSV` · `Edge TTS` · `Audio Processing` · `Telegram Bot` · `pytest`

## Architecture

```text
CSV sentence dataset
  │
  ▼
Validation and normalization
  │
  ▼
Recipe-driven AudioPlan
  │
  ▼
Provider policy and voice resolution
  │
  ├── Fake TTS
  ├── Edge TTS
  ├── Piper placeholder
  └── Ajil placeholder
        │
        ▼
Audio generation and caching
  │
  ├── output audio
  ├── manifest
  ├── JSONL logs
  └── SQLite job statistics
```

## Main use cases

- Persian prompts followed by French or English answers
- Full-sentence shadowing
- Word-by-word pronunciation practice
- Slow and normal-speed repetition
- Active-recall audio exercises
- Folder generation for offline language study

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Optional Edge TTS support:

```bash
python -m pip install -e '.[edge]'
```

Python 3.10+ is supported.

## Dataset format

Required CSV columns:

```text
id,persian,french,level,category,recommended_start
```

Optional columns include:

```text
english,enabled,tags,notes,priority,difficulty,voice_hint,pronunciation_note
```

Rows marked as disabled are skipped by default.

## Recipe system

Recipes are defined in `config/recipes.yaml`. They can control:

- source and target language fields
- voice and provider selection
- repeat count
- playback speed
- pauses between segments
- word splitting
- pauses between words
- output format

Included recipes demonstrate:

- `shadowing_basic`
- `active_recall`
- `english_then_target`
- `persian_prompt_french_ladder`

The Persian-to-French ladder can generate:

1. Persian prompt at normal speed
2. French sentence at normal speed
3. French word-by-word playback
4. French sentence at reduced speed
5. Final French sentence at normal speed

## CLI examples

Validate a dataset:

```bash
echolingua validate data/sample.csv
```

Preview a recipe without generating audio:

```bash
echolingua dry-run data/sample.csv \
  --recipe shadowing_basic \
  --from 1 \
  --to 5
```

Generate deterministic offline test audio:

```bash
echolingua generate data/sample.csv \
  --recipe shadowing_basic \
  --from 1 \
  --to 5 \
  --output outputs/smoke_fake.wav
```

Generate real Edge TTS sentence files:

```bash
echolingua generate-folder data/sample.csv \
  outputs/edge_sentence_files \
  --recipe persian_prompt_french_ladder \
  --from 1 \
  --to 100 \
  --provider edge \
  --output-format wav
```

## Provider policy

Provider selection supports:

- `explicit`
- `priority`
- `random`

Resolution order is:

1. step-level provider
2. recipe-level provider policy
3. global provider policy
4. default ordered provider

Voice resolution is also configuration-driven and can vary by language.

## Configuration

EchoLingua loads and validates:

1. `.env`
2. `config/default.yaml`
3. `config/providers.yaml`
4. `config/recipes.yaml`

Important default paths:

```text
storage/echolingua.sqlite3
outputs/
logs/events.jsonl
storage/tts_cache/
```

Configuration errors are reported before generation when paths, providers, formats, recipes, or text fields are invalid.

## Reliability and observability

Each generation run can persist:

- selected provider and voice
- cache hits and misses
- generation attempts
- output metadata
- job statistics
- structured event logs
- manifest records

The fake provider keeps tests deterministic and avoids external-network dependencies.

## Repository structure

```text
echolingua/
  pipeline/      # shared orchestration and planning
  providers/     # TTS and future AI provider abstractions
  storage/       # SQLite-backed state and statistics
  telegram/      # bot service and UI foundation
config/
data/
outputs/
logs/
storage/
```

## Current scope

The implemented core focuses on local recipe-driven generation. Piper, Ajil, LLM-assisted content generation, and richer export providers remain planned extension points and should not be interpreted as completed integrations.

## Verification

```bash
pytest -q
echolingua validate data/sample.csv
echolingua dry-run data/sample.csv --recipe shadowing_basic --from 1 --to 3
```

## Project status

EchoLingua demonstrates provider-oriented architecture, configuration-driven workflows, multilingual audio processing, persistence, caching, testability, and product-oriented CLI design.