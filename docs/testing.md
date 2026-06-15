# Testing EchoLingua

This document is the practical local verification checklist for EchoLingua.

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

If package installation fails because of a proxy or package index issue, continue with direct local Python commands and capture the exact install error.

## Required checks before commit

```bash
python -m compileall echolingua tests
pytest -q
```

## Sample CSV

Use the real sample file in this repo:

```text
data/sample.csv
```

## Manual smoke tests

CLI help:

```bash
echolingua --help
python -m echolingua.cli --help
```

Validate:

```bash
echolingua validate data/sample.csv
echolingua validate data/sample.csv --strict
```

Dry-run:

```bash
echolingua dry-run data/sample.csv --recipe shadowing_basic --from 1 --to 5
echolingua dry-run data/sample.csv --recipe english_then_target --from 1 --to 5
echolingua dry-run data/sample.csv --recipe persian_prompt_french_ladder --from 1 --to 3 --provider edge
```

Generate offline fake audio:

```bash
echolingua generate data/sample.csv --recipe shadowing_basic --from 1 --to 5 --output outputs/smoke_fake.wav
echolingua generate data/sample.csv --recipe english_then_target --from 1 --to 5 --output outputs/english_then_french_fake.wav
```

Generate one file per sentence into a target folder:

```bash
echolingua generate-folder data/sample.csv outputs/sentence_files --recipe shadowing_basic --from 1 --to 5
echolingua generate-folder data/sample.csv outputs/persian_french_ladder --recipe persian_prompt_french_ladder --from 1 --to 100 --provider edge --output-format wav --no-progress
```

Real Edge French smoke test:

```bash
echolingua providers test edge --text "Bonjour tout le monde"
echolingua dry-run data/sample.csv --recipe shadowing_basic --from 1 --to 3 --provider edge
echolingua generate data/sample.csv --recipe shadowing_basic --from 1 --to 3 --provider edge --output outputs/edge_french.wav --no-progress
```

MP3 output is best-effort. WAV is the guaranteed offline fallback when local export tooling is limited.

Provider diagnostics:

```bash
echolingua providers list
echolingua providers test fake
echolingua providers test edge
echolingua providers test piper
echolingua providers test ajil
```

Piper placeholder smoke check:

```bash
echolingua providers list
echolingua providers test piper
```

`providers test piper` should fail clearly in Phase 6 unless you later wire a real Piper runtime into EchoLingua.
`providers test ajil` should fail clearly in Phase 7 unless you later wire a real AJIL runtime into EchoLingua.

Config correctness smoke checks:

```bash
python - <<'PY'
from echolingua.core.config import load_config
config = load_config()
print(config.providers["tts"]["fake"]["voices"]["fr"])
print(config.recipes["recipes"]["shadowing_basic"]["provider_policy"]["tts"]["default_provider"])
print(config.recipes["recipes"]["persian_prompt_french_ladder"]["segments"][4]["split_words"])
PY
```

Runtime diagnostics:

```bash
echolingua stats
echolingua cache-stats
echolingua logs tail --lines 20
```

## Telegram Bot Smoke Checks

Bot env:

```bash
sed -n '1,200p' .env
```

Bot import checks:

```bash
python - <<'PY'
from pathlib import Path
from echolingua.core.config import load_config
from echolingua.telegram_bot.service import TelegramBotService

service = TelegramBotService(load_config())
service.ensure_user(
    telegram_user_id=1,
    chat_id=1,
    username="local_test",
    first_name="Local",
    last_name="Tester",
    language_code="fa",
)
result = service.import_csv_for_user(1, Path("data/sample.csv"), "sample.csv")
print(len(result["imported_sentence_ids"]))
print(service.export_user_csv(1))
PY
```

Bot service behavior checks:

```bash
python - <<'PY'
from pathlib import Path
from echolingua.core.config import load_config
from echolingua.telegram_bot.service import TelegramBotService

service = TelegramBotService(load_config())
service.ensure_user(telegram_user_id=11, chat_id=11, username="botcheck")
service.import_csv_for_user(11, Path("data/sample.csv"), "sample.csv")
print(service.sentence_summary(11))
print(service.describe_custom_recipe(11)["summary"])
service.create_or_update_custom_recipe(11, {"pause_between_ms": 3500, "word_pause_ms": 1100})
print(service.describe_custom_recipe(11))
page = service.paginated_user_sentences(11, 0, page_size=5)
print(page["page"], page["page_size"], len(page["items"]))
PY
```

Bot startup hardening check:

```bash
python - <<'PY'
from echolingua.telegram_bot.app import build_application
app = build_application()
print(type(app).__name__)
PY
```

Bot runtime:

```bash
python -m echolingua.telegram_bot.app
echolingua-bot
```

Docker Compose:

```bash
docker compose build
docker compose up bot
```

Security note:

- the current Telegram bot token in `.env` should be rotated after setup because it was provided directly in chat
- CSV import currently replaces the importing user's active library with the latest enabled rows from that CSV

## Inspect generated artifacts

Manifest:

```bash
sed -n '1,200p' outputs/smoke_fake.wav.manifest.json
sed -n '1,200p' outputs/english_then_french_fake.wav.manifest.json
```

SQLite:

```bash
python - <<'PY'
import sqlite3
conn = sqlite3.connect("storage/echolingua.sqlite3")
for table in ["jobs", "job_events", "provider_attempts", "audio_outputs", "tts_cache", "sentences"]:
    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(table, count)
PY
```

Logs:

```bash
tail -n 20 logs/events.jsonl
```

## Notes

- Unit tests must stay offline.
- `FakeTTSProvider` is the default test provider.
- `EdgeTTSProvider` must fail clearly when `edge-tts` is unavailable, but it may succeed on machines where the dependency is installed.
- Range selection uses inclusive sentence IDs from the CSV.
