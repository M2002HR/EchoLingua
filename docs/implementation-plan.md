# EchoLingua Master Implementation Plan

This is the complete implementation plan and agent instruction document for EchoLingua.

The agent must read this file before making changes.

This file is a living source of truth and must stay synchronized with the actual repository.

If implementation behavior changes, if older assumptions are no longer true, or if new CLI/runtime flows are added, this document must be updated in the same workstream.

Use Plan Mode first.

Do not start coding immediately. First inspect the repository, compare the current codebase with this plan, then produce a clear phased execution plan. After the plan is approved, implement phase by phase.

---

# 1. Project Identity

Project name:

```text
EchoLingua
```

EchoLingua is a provider-based language-learning pipeline.

It converts bilingual or multilingual sentence datasets into personalized audio files for:

* shadowing
* active recall
* listening-only review
* gym mode
* pronunciation drills
* night review
* future spaced repetition
* future Telegram delivery
* future AI-assisted translation/correction/variation generation
* future dashboard-based learning management

The initial language use case is:

```text
Persian → English bridge/reference → French target
```

But the architecture must support other target languages later.

---

# 2. Current Repository Context

The current EchoLingua repository already has a v0.1 skeleton.

Expected existing pieces may include:

* `pyproject.toml`
* Python 3.10+ support
* Typer CLI
* `README.md`
* `AGENTS.md`
* `docs/testing.md`
* `config/default.yaml`
* `config/providers.yaml`
* `config/recipes.yaml`
* `data/sample.csv`
* package under `echolingua/`
* tests under `tests/`
* `FakeTTSProvider`
* optional `EdgeTTSProvider`
* recipe system
* AudioPlan builder
* SQLite storage
* manifest generation
* structured logs
* PipelineRunner

Do not blindly trust this list. Inspect the actual repository.

Current repo reality that must remain reflected here:

* the active sample dataset is `data/sample.csv`
* `docs/testing.md` exists and is maintained
* `generate-folder` exists and generates one audio file per sentence into a target folder
* offline generation is guaranteed with WAV output; MP3 is best-effort depending on local export tooling
* job progress is recorded in SQLite and emitted as `job_progress` events

Start with:

```bash
git status
git branch --show-current
python --version
python -m compileall echolingua tests
pytest -q
```

Then inspect:

```text
README.md
AGENTS.md
docs/testing.md
pyproject.toml
config/default.yaml
config/providers.yaml
config/recipes.yaml
echolingua/
tests/
```

---

# 3. Workflow Rules

This is a personal project.

Default workflow:

* Work directly on the current branch.
* Do not create pull requests by default.
* Do not create separate branches unless explicitly asked.
* Commit directly after tests pass.
* Use conventional commit messages.
* Keep commits small and meaningful.
* Do not claim tests passed unless they actually ran.

Suggested commit messages:

```text
fix: stabilize cli and packaging
feat: add cli diagnostics commands
feat: add english bridge sentence support
feat: add progress reporting
docs: update testing workflow
test: add cli diagnostics coverage
refactor: simplify provider selection
```

Before every commit, run:

```bash
python -m compileall echolingua tests
pytest -q
```

For CLI changes, also run relevant manual smoke tests.

If install fails because of package index, proxy, or network issues, explain clearly and provide the exact local command to run.

Try install when relevant:

```bash
python -m pip install -e ".[dev]"
```

If optional Edge TTS is needed:

```bash
python -m pip install -e ".[dev,edge]"
```

or:

```bash
python -m pip install edge-tts
```

---

# 4. Core Product Pipeline

The main pipeline:

```text
CSV sentences
→ validation
→ sentence storage
→ recipe engine
→ AudioPlan builder
→ provider selection
→ progress reporting
→ TTS segment generation
→ cache
→ audio merge
→ manifest
→ structured logs
→ SQLite stats
→ CLI diagnostics
→ optional export
→ future API/dashboard
→ future AJIL AI gateway
```

EchoLingua must not become a one-off CSV-to-MP3 script.

It should become a modular, configurable, testable language-learning platform.

---

# 5. Main Architecture Principles

## 5.1 EchoLingua owns the product logic

EchoLingua owns:

* runtime config
* sentence loading
* sentence validation
* sentence storage
* recipes
* provider policies
* AudioPlan
* cache
* audio generation workflow
* output files
* manifest
* logs
* analytics
* CLI
* future API
* future dashboard

## 5.2 AJIL is a future AI gateway provider

AJIL must not own EchoLingua runtime config.

AJIL will later be integrated as a git submodule or external service.

Correct GitHub repository:

```text
https://github.com/M2002HR/Ajil_Unified_AI_Gateway.git
```

Future submodule path:

```text
vendor/Ajil_Unified_AI_Gateway/
```

Future command:

```bash
git submodule add https://github.com/M2002HR/Ajil_Unified_AI_Gateway.git vendor/Ajil_Unified_AI_Gateway
git submodule update --init --recursive
```

Before adding the submodule, verify the remote:

```bash
git ls-remote https://github.com/M2002HR/Ajil_Unified_AI_Gateway.git
```

AJIL should later be used for:

* LLM
* STT
* optional TTS
* model routing
* provider aggregation
* Gemini
* Groq
* future AI APIs

But all EchoLingua settings must be controlled from EchoLingua config and mapped into AJIL config/env when needed.

## 5.3 edge-tts is not a submodule

`edge-tts` is only an optional Python dependency.

Correct model:

```text
edge-tts = optional pip dependency
Piper = future real local/offline TTS provider
AJIL = future AI gateway submodule/provider
```

Edge TTS is online/no-key, not truly local.

Piper is the future local/offline TTS provider.

## 5.4 Provider selection is not only fallback

Provider policy must support choosing from enabled providers.

Required selection modes:

```text
explicit
priority
random
```

Future selection modes:

```text
round_robin
weighted
speed_first
quality_first
cost_first
```

Fallback is optional:

```yaml
allow_fallback_on_error: true
```

or:

```yaml
allow_fallback_on_error: false
```

If fallback is disabled and the selected provider fails, the job must fail clearly.

## 5.5 Provider override order

Provider resolution order:

```text
step-level provider
→ recipe-level provider_policy
→ global provider_policy
→ default provider
```

This must be implemented, documented, and tested.

---

# 6. Data Model and CSV Schema

The CSV should support these language columns:

```text
persian = original source/native sentence
english = bridge/reference sentence
french = current target sentence
```

The project should later support other target columns/languages.

For now:

```text
target_column = french
target_language = fr
```

Required columns:

```csv
id,persian,english,french,level,category,recommended_start
```

Backward compatibility:

* Existing CSV files without `english` should still work.
* `english` can be optional at the loader level.
* If a recipe uses `english`, then rows missing `english` should fail clearly or be skipped based on validation settings.

Optional columns:

```csv
enabled,tags,notes,priority,difficulty,voice_hint,pronunciation_note
```

Sentence object should support:

```text
id
persian
english optional
target text
target_language
target_column
french backward-compatible field
level
category
recommended_start
enabled
tags
notes
priority
difficulty
voice_hint
pronunciation_note
```

Target alias behavior:

```text
field: french  → uses french column
field: target  → uses current target column, initially french
field: english → uses english column
field: persian → uses persian column
```

---

# 7. Validation Requirements

Validation command:

```bash
echolingua validate data/french_100_sentences_mohammad.csv
```

Options:

```bash
--strict
--no-strict
```

Validation output must include:

```text
total rows
enabled rows
disabled rows
valid rows
invalid rows
duplicate ids
missing required fields
rows with English
rows missing English
levels summary
categories summary
tags summary if easy
```

Strict mode:

* exit non-zero if validation fails

Non-strict mode:

* report problems clearly
* do not crash unnecessarily

Suggested valid levels:

```text
A0
A0+
A1-
A1
A1+
A2
```

Initial file may use:

```text
A0
A0+
A1-
A1
```

---

# 8. Recipes

Recipes must be config-driven, not hard-coded.

Existing or required recipes:

```text
shadowing_basic
active_recall
english_then_target
```

Future recipes:

```text
listen_only
gym_loop
pronunciation_drill
night_review
reverse_translation
```

Example:

```yaml
recipes:
  shadowing_basic:
    description: "Slow → medium → normal with pauses"
    provider_policy:
      tts:
        mode: explicit
        provider: fake
        allow_fallback_on_error: false
    steps:
      - type: tts
        field: target
        voice: male
        rate: "-35%"
      - type: silence
        duration_ms: 1500
      - type: tts
        field: target
        voice: female
        rate: "-15%"
      - type: silence
        duration_ms: 1500
      - type: tts
        field: target
        voice: random
        rate: "+0%"
      - type: silence
        duration_ms: 4000

  active_recall:
    description: "Silence first, then target answer"
    provider_policy:
      tts:
        mode: priority
        allow_fallback_on_error: false
    steps:
      - type: silence
        duration_ms: 5000
      - type: tts
        field: target
        voice: male
        rate: "+0%"
      - type: silence
        duration_ms: 2500

  english_then_target:
    description: "English reference first, then target-language sentence"
    provider_policy:
      tts:
        mode: priority
        allow_fallback_on_error: false
    steps:
      - type: tts
        field: english
        voice: neutral
        rate: "+0%"
      - type: silence
        duration_ms: 1200
      - type: tts
        field: target
        voice: male
        rate: "-20%"
      - type: silence
        duration_ms: 1200
      - type: tts
        field: target
        voice: female
        rate: "+0%"
      - type: silence
        duration_ms: 3000
```

Recipes must support arbitrary text fields:

```text
persian
english
french
target
```

If a recipe step references a missing field, fail clearly.

---

# 9. AudioPlan

Before generating audio, EchoLingua must create an AudioPlan.

AudioPlan enables:

* dry-run
* dashboard preview later
* testing
* segment count estimate
* provider call estimate
* progress bar total steps
* manifest generation
* debugging

AudioPlan should include:

```text
job_id
recipe name
source CSV path
target_language
target_column
selected sentence ids
provider policy
all planned segments
TTS segment count
silence segment count
total segment count
estimated provider calls
estimated output path
```

Example segment:

```json
{
  "type": "tts",
  "sentence_id": 5,
  "field": "target",
  "text": "Je m’appelle Mohammad.",
  "provider": "fake",
  "voice": "male",
  "rate": "-35%",
  "target_language": "fr",
  "target_column": "french"
}
```

Dry-run command:

```bash
echolingua dry-run data/french_100_sentences_mohammad.csv --recipe english_then_target --from 1 --to 5
```

Dry-run must not write audio.

It should print:

```text
job_id
recipe
target_language
target_column
sentence count
segment count
TTS segment count
silence segment count
provider policy
selected providers
estimated provider calls
fields used: english,target
```

---

# 10. Progress Bars and Progress Reporting

Progress reporting is required for long-running tasks.

## 10.1 CLI progress bars

Add progress bars for commands that perform multi-step work, especially:

```text
generate
provider testing when multiple providers
batch generation
future imports
future exports
future AJIL calls
```

Preferred libraries:

```text
rich
```

or:

```text
tqdm
```

Recommended choice:

```text
rich
```

because it can also improve CLI tables, panels, status messages, and logs.

If adding `rich`, add it as a dependency only if acceptable. Otherwise keep progress reporting simple and dependency-light.

Progress bar for generate should show:

```text
loading CSV
validating
building plan
rendering TTS segments
cache hits
cache misses
merging audio
saving manifest
writing database records
```

Segment-level progress:

```text
Rendering segment 12/120
Sentence 5
Provider fake
Field target
Cache hit/miss
```

Progress should not break non-interactive environments.

Support:

```bash
--no-progress
```

or auto-disable progress when not TTY.

## 10.2 Job progress model

Each job should track:

```text
total_steps
completed_steps
current_stage
current_message
started_at
finished_at
status
```

Suggested stages:

```text
created
loading_csv
validating
building_plan
rendering_segments
merging_audio
saving_manifest
saving_records
finished
failed
```

## 10.3 Future dashboard progress

Later, FastAPI/WebSocket should stream progress events to dashboard.

Do not build dashboard now, but design job events so they can be reused later.

---

# 11. TTS Providers

Provider files should be structured like:

```text
echolingua/providers/tts/
  base.py
  fake.py
  edge.py
  piper.py
  ajil.py
```

## 11.1 FakeTTSProvider

Required:

* works offline
* used in tests
* generates valid placeholder audio or silence
* no network
* deterministic enough for tests

## 11.2 EdgeTTSProvider

Required:

* optional dependency
* uses `edge-tts`
* no unit tests should call it as a real network provider
* clear error if missing

Error example:

```text
EdgeTTSProvider requires the optional dependency edge-tts.
Install it with:
python -m pip install -e ".[edge]"
```

## 11.3 PiperTTSProvider

Future real local/offline provider.

Do not implement heavy model download/management unless explicitly requested.

For now, it is acceptable to add:

* interface placeholder
* config placeholder
* docs explaining Piper is the local/offline provider

## 11.4 AjilTTSProvider

Future provider that calls AJIL Gateway TTS endpoint.

Do not fully implement until AJIL integration phase.

Add only placeholders/interfaces if useful.

---

# 12. Provider Policy and Config

`config/providers.yaml` should support:

```yaml
providers:
  tts:
    selection:
      mode: priority
      allow_fallback_on_error: false
    items:
      fake:
        enabled: true
        priority: 10
        kind: offline_test
      edge:
        enabled: false
        priority: 20
        kind: online_no_key
      piper:
        enabled: false
        priority: 30
        kind: local_offline
      ajil:
        enabled: false
        priority: 40
        kind: gateway

  llm:
    selection:
      mode: priority
      allow_fallback_on_error: false
    items:
      fake:
        enabled: true
        priority: 10
        kind: offline_test
      ajil:
        enabled: false
        priority: 20
        kind: gateway
```

Config should support language voice profiles:

```yaml
voices:
  en:
    neutral: en-US-AriaNeural
    male: en-US-GuyNeural
    female: en-US-JennyNeural
  fr:
    male: fr-FR-HenriNeural
    female: fr-FR-DeniseNeural
    neutral: fr-FR-DeniseNeural
```

For fake provider, voices do not matter, but metadata must be preserved in AudioPlan and manifest.

---

# 13. Cache

TTS cache key should include:

```text
provider
text
field
voice
rate
pitch
volume
language
target_language
provider config version if available
```

Suggested cache path:

```text
.cache/tts/{provider}/{hash}.wav
```

or:

```text
.cache/tts/{provider}/{hash}.mp3
```

Cache must be recorded in SQLite.

CLI command:

```bash
echolingua cache-stats
```

Must print:

```text
provider
entry count
approx size
hit/miss summary if available
```

---

# 14. Manifest

Every generated audio output must have a manifest JSON.

Manifest should include:

```text
schema_version
app
job_id
recipe
source_csv
target_language
target_column
output path
manifest path
created_at
sentence count
segment count
cache hits
cache misses
provider attempts summary
rendered segments
```

Sentence metadata should include:

```text
id
persian
english if available
target
target_language
target_column
level
category
tags
```

Rendered segment metadata should include:

```text
segment index
type
sentence_id
field
text
provider
voice
rate
language
cache hit/miss
duration if available
```

---

# 15. Logs

Logs should be structured JSONL when possible.

Suggested log files:

```text
logs/app.log
logs/pipeline.log
logs/providers.log
logs/audio.log
logs/errors.log
logs/audit.log
```

Each event should include:

```text
timestamp
level
event
job_id
sentence_id when applicable
provider_type when applicable
provider when applicable
latency_ms when applicable
cached when applicable
stage when applicable
message
metadata
```

Example:

```json
{
  "timestamp": "2026-06-12T12:00:00Z",
  "level": "INFO",
  "event": "tts.segment.finished",
  "job_id": "job_001",
  "sentence_id": 12,
  "provider_type": "tts",
  "provider": "fake",
  "field": "target",
  "latency_ms": 12,
  "cached": false,
  "stage": "rendering_segments",
  "metadata": {}
}
```

CLI:

```bash
echolingua logs tail --lines 50
```

Must handle missing logs gracefully.

---

# 16. SQLite Storage

Initial storage:

```text
SQLite
```

Required tables:

```text
sentences
jobs
job_events
provider_attempts
audio_outputs
tts_cache
```

Future tables:

```text
recipes
recipe_steps
exports
settings_snapshots
learning_reviews
user_feedback
```

## 16.1 jobs

Track:

```text
job_id
recipe
status
progress_total
progress_completed
current_stage
started_at
finished_at
output_path
error info
```

## 16.2 job_events

Track:

```text
job_id
event
stage
level
message
payload_json
created_at
```

## 16.3 provider_attempts

Track:

```text
job_id
provider_type
provider_name
operation
model
voice
field
status
latency_ms
cached
error_code
error_message
created_at
```

## 16.4 audio_outputs

Track:

```text
job_id
recipe_name
output_path
manifest_path
duration_ms
file_size_bytes
created_at
```

## 16.5 tts_cache

Track:

```text
provider
cache_key
text_hash
file_path
created_at
hit_count
```

---

# 17. CLI Requirements

The CLI is currently the main interface.

The CLI must be solid before dashboard work.

## 17.1 Required commands

### Help

```bash
echolingua --help
```

Fallback:

```bash
python -m echolingua.cli --help
```

### Validate

```bash
echolingua validate data/sample.csv
```

Options:

```bash
--strict
--no-strict
```

### Dry-run

```bash
echolingua dry-run data/sample.csv --recipe shadowing_basic --from 1 --to 5
```

Also test:

```bash
echolingua dry-run data/sample.csv --recipe english_then_target --from 1 --to 5
```

### Generate

```bash
echolingua generate data/sample.csv --recipe shadowing_basic --from 1 --to 5 --output outputs/smoke_fake.wav
```

Also test:

```bash
echolingua generate data/sample.csv --recipe english_then_target --from 1 --to 5 --output outputs/english_then_french_fake.wav
```

Per-sentence folder generation:

```bash
echolingua generate-folder data/sample.csv outputs/sentence_files --recipe shadowing_basic --from 1 --to 5
```

Generate should support:

```bash
--no-progress
```

if progress bars are implemented.

### Providers list

```bash
echolingua providers list
```

### Providers test

```bash
echolingua providers test fake
echolingua providers test edge
```

### Stats

```bash
echolingua stats
```

Must show:

```text
total jobs
successful jobs
failed jobs
total provider attempts
provider attempts by provider
cache hits/misses
generated audio outputs
total output duration if available
```

### Cache stats

```bash
echolingua cache-stats
```

### Logs tail

```bash
echolingua logs tail --lines 20
```

---

# 18. Documentation Requirements

Keep docs synced with real CLI.

Update:

```text
README.md
docs/testing.md
docs/master-implementation-plan.md
```

README should cover:

```text
What EchoLingua is
Architecture
Setup
Python 3.10+
CSV format
English bridge sentence
Target language concept
Recipes
Provider policy
Progress bars
Dry-run
Generate
Logs
Manifest
SQLite
CLI diagnostics
Future AJIL integration
Future dashboard
Roadmap
```

docs/testing.md should cover:

```text
venv setup
pip install -e ".[dev]"
compileall
pytest
validate
dry-run
generate fake audio
generate one file per sentence into folder
english_then_target recipe
manifest inspection
SQLite inspection
cache stats
provider list/test
logs tail
optional Edge TTS test
troubleshooting package index/proxy issues
required checks before commit
```

---

# 19. Testing Requirements

Tests must be offline and fast.

Required tests:

```text
CSV loading with english
CSV loading without english
CSV validation
English coverage reporting
Recipe loading
english_then_target recipe
Config loading
Provider registry
Provider selector explicit
Provider selector priority
Provider selector random
Provider fallback disabled
Provider fallback enabled if implemented
AudioPlan with target alias
AudioPlan with english field
FakeTTSProvider
EdgeTTSProvider missing dependency
Cache key generation
Audio builder with fake provider
Manifest generation with persian/english/target metadata
SQLite record creation
CLI validate
CLI dry-run
CLI generate with fake
CLI providers list
CLI providers test fake
CLI stats missing DB
CLI stats populated DB if feasible
CLI cache-stats
CLI logs tail missing logs
CLI logs tail existing logs
Progress reporting does not break non-TTY usage
```

Always run:

```bash
python -m compileall echolingua tests
pytest -q
```

Manual smoke tests:

```bash
echolingua --help
echolingua validate data/sample.csv
echolingua dry-run data/sample.csv --recipe shadowing_basic --from 1 --to 5
echolingua dry-run data/sample.csv --recipe english_then_target --from 1 --to 5
echolingua generate data/sample.csv --recipe shadowing_basic --from 1 --to 5 --output outputs/smoke_fake.wav
echolingua generate data/sample.csv --recipe english_then_target --from 1 --to 5 --output outputs/english_then_french_fake.wav
echolingua generate-folder data/sample.csv outputs/sentence_files --recipe shadowing_basic --from 1 --to 5
echolingua providers list
echolingua providers test fake
echolingua stats
echolingua cache-stats
echolingua logs tail --lines 20
```

Fallback:

```bash
python -m echolingua.cli --help
```

---

# 20. Development Phases

## Phase 0 — Inspect and Stabilize

Goal:

Make sure the existing repo is healthy.

Tasks:

* inspect current repo
* run compile/test
* verify Python 3.10 support
* verify package discovery
* verify CLI entry point
* fix broken imports
* fix ignored package directories
* fix docs mismatch
* check install behavior

Acceptance:

```bash
python -m compileall echolingua tests
pytest -q
```

passes.

## Phase 1 — English Bridge Support

Goal:

Support English as a bridge/reference field.

Tasks:

* add `english` support to Sentence model
* keep backward compatibility with CSVs without `english`
* add target alias:

  * `target` maps to current target column
  * default target column is `french`
  * default target language is `fr`
* update validation to report English coverage
* update AudioPlan to support `field: english`
* add `english_then_target` recipe
* update manifest
* update docs
* add tests

Acceptance:

```bash
echolingua dry-run data/french_100_sentences_mohammad.csv --recipe english_then_target --from 1 --to 5
```

works.

## Phase 2 — CLI Diagnostics

Goal:

Make the project testable from terminal.

Implement/improve:

* validate
* dry-run
* generate
* providers list
* providers test
* stats
* cache-stats
* logs tail

Acceptance:

All CLI smoke tests pass with fake provider.

## Phase 3 — Progress Bars

Goal:

Show progress for long-running commands.

Current implementation status:

* implemented for `generate`
* implemented for `generate-folder`
* `--no-progress` is supported
* non-TTY environments auto-disable visible progress
* progress is recorded in `job_events` and in `jobs.current_stage/current_message/completed_steps/total_steps`

Tasks:

* add progress reporting to generate
* show progress for:

  * loading
  * validating
  * planning
  * rendering segments
  * merging
  * saving manifest
  * saving DB records
* support non-TTY environments
* add `--no-progress` if needed
* record progress in job events
* update docs
* add tests where feasible

Acceptance:

Generate shows useful progress locally but tests remain stable.

## Phase 4 — Storage, Logs, Stats Hardening

Goal:

Make debugging reliable.

Current implementation status:

* jobs, events, provider attempts, outputs, and cache are persisted in SQLite
* `stats` reports aggregate counts plus `latest_job`
* `cache-stats` reports entry counts and approximate size
* `logs tail` handles existing and missing logs
* manifests include source CSV path, target metadata, and selected sentence ids

Tasks:

* ensure jobs are recorded correctly
* ensure provider attempts are recorded
* ensure cache entries are recorded
* ensure logs are written
* ensure stats command reads real DB
* ensure logs tail handles missing/existing logs
* ensure manifest and DB agree

Acceptance:

After generate:

```bash
echolingua stats
echolingua cache-stats
echolingua logs tail --lines 20
```

show meaningful output.

## Phase 5 — Config Correctness

Goal:

Make provider and recipe config future-proof.

Tasks:

* validate config
* friendly config errors
* implement/verify provider override order
* add language voice config
* keep secrets in `.env`
* keep recipes/provider policy in YAML
* docs sync

Acceptance:

Provider selection behavior is tested and documented.

Current implementation status:

* done: config validation runs inside `load_config()`
* done: friendly `ConfigError` messages cover invalid paths, providers, recipe formats, and unsupported segment fields
* done: provider override order is implemented as:

```text
step-level provider
→ recipe-level provider_policy
→ global provider_policy
→ default provider from the ordered enabled registry
```

* done: language voice resolution is config-driven through provider `voices.<language>` and `default_voice`
* done: recipes remain YAML-driven and now carry `provider_policy`
* done: tests cover recipe-policy override, step-level override, config validation failures, and voice resolution
* note: current shipped recipes default to `fake` through recipe-level policy and rely on provider voice maps instead of hard-coded segment voices
* note: secrets still belong in `.env`; no secrets were moved into recipe/provider YAML

## Phase 6 — Local TTS Preparation

Goal:

Prepare for Piper.

Tasks:

* add `PiperTTSProvider` placeholder/interface if not present
* document Piper as real local/offline provider
* keep Edge as online optional provider
* do not implement heavy model download unless explicitly asked

Acceptance:

No real Piper dependency required yet.

Current implementation status:

* done: added `echolingua.providers.tts.piper.PiperTTSProvider` placeholder
* done: `config/providers.yaml` now includes a disabled `piper` entry with `model_path`, `config_path`, language voices, and `default_voice`
* done: `providers list` reports `piper` and whether Piper/Wyoming Piper runtime appears available locally
* done: `providers test piper` fails clearly with placeholder/runtime guidance
* done: config validation requires `model_path` and `config_path` before `piper` can be enabled
* note: no model download, no local Piper bootstrapping, and no real Piper synthesis path are implemented in this phase

## Phase 7 — AJIL Preparation

Goal:

Prepare for future AJIL integration.

Tasks:

* keep or improve:

  * `echolingua/ai_gateway/ajil_client.py`
  * `echolingua/ai_gateway/config_mapper.py`
* add placeholder provider classes if useful:

  * `AjilLLMProvider`
  * `AjilTTSProvider`
* document exact AJIL repo URL:

```text
https://github.com/M2002HR/Ajil_Unified_AI_Gateway.git
```

* document submodule path:

```text
vendor/Ajil_Unified_AI_Gateway/
```

* do not require editing AJIL config manually
* map future EchoLingua config to AJIL `UAG_*` env vars

Acceptance:

Interfaces exist, docs are clear, no full AJIL runtime required yet.

Current implementation status:

* done: confirmed official AJIL repository URL is `https://github.com/M2002HR/Ajil_Unified_AI_Gateway.git`
* done: preserved the planned submodule target `vendor/Ajil_Unified_AI_Gateway/`
* done: added placeholder `AjilGatewayClient`, `AjilLLMProvider`, and `AjilTTSProvider`
* done: added disabled `ajil` provider config placeholder with `base_url`, route metadata, and voices
* done: added AJIL-aware config validation for enabled-provider basics
* done: mapped EchoLingua-owned config into a concrete `UAG_*` env payload through `echolingua.ai_gateway.config_mapper`
* done: `providers list` now reports `ajil`, and `providers test ajil` fails clearly with placeholder guidance
* note: no real AJIL submodule checkout, live gateway calls, or end-to-end AJIL synthesis/completion are implemented in this phase

Current implementation status beyond Phase 7:

* done: recipe TTS segments now support config-driven `repeat`, `pause_after_ms`, `split_words`, `word_pause_ms`, and `delimiter_pattern`
* done: added `persian_prompt_french_ladder` recipe for practical Persian prompt plus multi-pass French playback
* done: recipe expansion supports French word-by-word rendering with silence inserted between generated word segments
* done: Edge voice config now includes commented male/female options for Persian, French, and English
* done: unit tests cover word-by-word plan expansion, recipe loading, summary counts, and config validation for word-pause misuse

Current implementation status beyond the original phases:

* done: added a Telegram bot foundation in Python under `echolingua.telegram_bot`
* done: Telegram user, user settings, user sentence library, and CSV import history are now persisted in SQLite
* done: the bot service can import/export CSV, build captions, and trigger per-sentence audio generation through the shared pipeline
* done: added `echolingua-bot` entrypoint plus `Dockerfile` and `docker-compose.yml`
* done: Telegram startup now ignores incompatible ambient proxy env vars by building PTB requests with `trust_env=False`
* done: Telegram runtime also supports an explicit `ECHOLINGUA_TELEGRAM_BOT_PROXY_URL` for deployments that must reach the Bot API through a proxy
* done: imported Telegram CSV data is now stored as a user-scoped sentence snapshot so one user's library does not overwrite another user's imported content
* done: the bot UI now includes paginated library browsing, numeric sentence ordering, per-sentence send/edit/remove actions, page-size settings, and a Telegram-managed custom ladder recipe flow
* done: the bot now supports target-language selection beyond French and adapts runtime recipes and captions to the selected target language
* done: practical in-bot sentence creation now works from target-language text plus Persian translation instead of only adding by shared sentence id
* done: the in-bot recipe editor can reduce or increase silence for existing recipes and the default custom ladder pauses were shortened for a tighter listening flow
* done: each Telegram user can now create and edit multiple personal guided recipes, stored in SQLite and resolved into runtime recipes at generation time
* done: the Telegram bot now has a more interactive recipe-building flow that mixes buttons with focused text inputs for names and timing values
* done: Edge TTS synthesis is now safe inside the Telegram bot event loop and no longer crashes on nested `asyncio.run()` usage
* done: Telegram message edits now safely ignore the benign `Message is not modified` API response
* note: full arbitrary segment-by-segment recipe authoring from chat is still not implemented; the current in-bot recipe editor focuses on practical guided ladder/listen-repeat style flows
* note: the Telegram bot token currently lives in `.env` for local runtime and should be rotated after verification because it was shared in chat

## Phase 8 — Future API/Dashboard Preparation

Do not build full dashboard yet.

But keep service layer clean so future FastAPI/React can reuse it.

Future backend:

```text
FastAPI
routes for sentences/jobs/audio/logs/analytics/providers/settings
WebSocket for job progress/logs
```

Future frontend:

```text
React + Vite + Tailwind
```

---

# 21. Future Dashboard Vision

Dashboard pages:

```text
Main Dashboard
Sentences Manager
Recipe Builder
Audio Plan Preview
Jobs Monitor
Audio Library
Provider Center
Logs Explorer
Analytics
Settings
AI Studio
```

Main Dashboard:

```text
total sentences
active sentences
generated audio files
total audio duration
last job
provider health
cache hit rate
AJIL status
Telegram status
recent errors
```

Jobs Monitor:

```text
live progress bar
current stage
completed/total segments
provider attempts
cache hits
errors
download output
view manifest
```

Provider Center:

```text
enable/disable providers
priority
health check
test provider
last error
latency
```

AI Studio:

```text
translate
improve French
generate variations
pronunciation notes
quiz generation
dialogue generation
```

AI Studio should later use AJIL.

---

# 22. Error Handling Rules

Use friendly errors.

Examples:

Missing CSV:

```text
CSV file not found: data/missing.csv
```

Missing recipe:

```text
Recipe not found: english_then_target
Available recipes: shadowing_basic, active_recall
```

Missing English field when recipe needs it:

```text
Recipe step uses field 'english', but sentence 12 has no English text.
```

Missing Edge dependency:

```text
EdgeTTSProvider requires the optional dependency edge-tts.
Install it with:
python -m pip install -e ".[edge]"
```

Missing DB:

```text
No EchoLingua database found yet. Run a generate command first.
```

Missing logs:

```text
No logs found yet.
```

---

# 23. Code Quality Rules

* Keep modules small.
* Use typed functions.
* Use `pathlib`.
* Prefer dependency injection.
* Keep CLI/API/dashboard sharing service layer.
* Do not duplicate pipeline logic in CLI.
* Avoid hard-coded provider choices.
* Avoid hard-coded paths when config exists.
* Keep tests fast.
* Keep tests offline.
* Use clear error messages.
* Use fake providers for tests.
* Do not overbuild dashboard before CLI/storage/logs are solid.

---

# 24. Acceptance Criteria for Current Milestone

The near-term milestone is:

```text
EchoLingua v0.1 is locally reliable and testable through CLI.
```

Required:

```bash
python -m compileall echolingua tests
pytest -q
```

Required manual commands:

```bash
echolingua --help
echolingua validate data/french_100_sentences_mohammad.csv
echolingua dry-run data/french_100_sentences_mohammad.csv --recipe shadowing_basic --from 1 --to 5
echolingua dry-run data/french_100_sentences_mohammad.csv --recipe english_then_target --from 1 --to 5
echolingua generate data/french_100_sentences_mohammad.csv --recipe shadowing_basic --from 1 --to 5 --output outputs/smoke_fake.mp3
echolingua generate data/french_100_sentences_mohammad.csv --recipe english_then_target --from 1 --to 5 --output outputs/english_then_french_fake.mp3
echolingua providers list
echolingua providers test fake
echolingua stats
echolingua cache-stats
echolingua logs tail --lines 20
```

After generate, verify:

```text
output audio exists
manifest exists
SQLite DB exists
logs exist
provider attempts exist
cache entries exist
progress events exist or job stages are recorded
```

---

# 25. Final Agent Response Format

After each completed phase, respond with:

```text
Summary
- ...

Changed files
- ...

Tests run
- ...

Manual verification
- ...

Known issues / follow-ups
- ...

Commit
- <hash>
```

Do not claim something passed unless it actually ran.

---

# 26. Suggested First Prompt for Codex

Use this after saving the document:

```text
Read these files first:
- AGENTS.md
- README.md
- docs/testing.md
- docs/master-implementation-plan.md

Use Plan Mode.

This repository is EchoLingua. Follow docs/master-implementation-plan.md as the source of truth.

First inspect the current codebase and compare it with the plan.

Create a phased implementation plan focused on:
1. repository health
2. English bridge sentence support
3. CLI diagnostics
4. progress bars
5. storage/logs/stats hardening
6. tests
7. docs sync

Do not implement dashboard, Telegram, or full AJIL integration yet.

After I approve the plan:
- work directly on the current branch
- do not create a PR
- run tests after each phase
- commit directly with conventional commit messages
- keep all tests offline
- use FakeTTSProvider for tests
- report what passed, what failed, and what remains
```

---

# 27. Suggested Next Implementation Commit Group

Recommended commits:

```text
feat: add english bridge sentence support
feat: add cli diagnostics commands
feat: add progress reporting
feat: add per-sentence folder generation
test: add cli and pipeline coverage
docs: sync implementation and testing guides
```

If everything is tightly connected, one commit is acceptable:

```text
feat: improve multilingual cli pipeline workflow
```
