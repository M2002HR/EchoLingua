# EchoLingua v0.1 Testing Guide

This guide describes the practical verification flow for EchoLingua v0.1. Run commands from the repository root.

## 1. Python 3.10+ environment

EchoLingua supports Python 3.10 or newer. Confirm your interpreter first:

```bash
python --version
```

If your system default Python is older, use a Python 3.10+ executable explicitly, for example:

```bash
python3.10 --version
```

## 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

On Windows PowerShell, activate with:

```powershell
.venv\Scripts\Activate.ps1
```

## 3. Install EchoLingua for development

```bash
python -m pip install -e ".[dev]"
```

This installs the package, CLI entry point, and development test dependencies.

## 4. Required checks before every commit

Always run both commands before committing:

```bash
python -m compileall echolingua tests
pytest -q
```

Unit tests must not make real network calls. Use `FakeTTSProvider` for TTS tests. Use `FakeLLMProvider` for future LLM tests once LLM functionality is implemented.

## 5. CLI help check

After installation, verify the CLI loads:

```bash
echolingua --help
```

You can also run the module function directly during development:

```bash
python -m echolingua.cli --help
```

## 6. CSV validation check

There is not a dedicated `validate-csv` CLI command in v0.1. The current equivalent is loading the CSV with the sentence loader:

```bash
python - <<'PY'
from pathlib import Path
from echolingua.sentences.loader import load_sentences

sentences = load_sentences(Path("data/french_100_sentences_mohammad.csv"))
print(f"Loaded {len(sentences)} enabled sentences")
PY
```

TODO: add a dedicated `echolingua validate-csv ...` command in a future version.

## 7. Dry-run an AudioPlan

Dry-run validates the CSV, loads the recipe, builds an `AudioPlan`, and prints the estimated segment count without generating audio:

```bash
echolingua dry-run data/french_100_sentences_mohammad.csv --recipe shadowing_basic
```

Use `active_recall` to test the second built-in recipe:

```bash
echolingua dry-run data/french_100_sentences_mohammad.csv --recipe active_recall
```

## 8. Generate audio with FakeTTSProvider

The default configuration enables the fake TTS provider and disables Edge TTS. This command should run offline:

```bash
echolingua generate data/french_100_sentences_mohammad.csv --recipe shadowing_basic --output outputs/shadowing_basic.mp3
```

Expected outputs:

- `outputs/shadowing_basic.mp3`
- `outputs/shadowing_basic.mp3.manifest.json`
- `logs/events.jsonl`
- `storage/echolingua.sqlite3`
- cached TTS files under `storage/tts_cache/`

## 9. Inspect the generated manifest

```bash
python -m json.tool outputs/shadowing_basic.mp3.manifest.json
```

Useful quick checks:

```bash
python - <<'PY'
import json
from pathlib import Path

manifest = json.loads(Path("outputs/shadowing_basic.mp3.manifest.json").read_text(encoding="utf-8"))
print(manifest["job_id"])
print(manifest["recipe_name"])
print(manifest["segment_count"])
print(manifest["output"]["duration_ms"])
PY
```

## 10. Inspect SQLite storage

If the `sqlite3` shell is installed:

```bash
sqlite3 storage/echolingua.sqlite3 ".tables"
sqlite3 storage/echolingua.sqlite3 "SELECT id, recipe_name, status, created_at, completed_at FROM jobs ORDER BY created_at DESC LIMIT 5;"
sqlite3 storage/echolingua.sqlite3 "SELECT provider_name, provider_kind, status, COUNT(*) FROM provider_attempts GROUP BY provider_name, provider_kind, status;"
sqlite3 storage/echolingua.sqlite3 "SELECT path, manifest_path, duration_ms FROM audio_outputs ORDER BY created_at DESC LIMIT 5;"
sqlite3 storage/echolingua.sqlite3 "SELECT provider_name, voice, language, duration_ms FROM tts_cache LIMIT 5;"
```

If the shell is unavailable, use Python's built-in SQLite module:

```bash
python - <<'PY'
import sqlite3

conn = sqlite3.connect("storage/echolingua.sqlite3")
for table in ["jobs", "provider_attempts", "audio_outputs", "tts_cache"]:
    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(table, count)
PY
```

## 11. Verify TTS cache behavior

Run the same generation command twice:

```bash
echolingua generate data/french_100_sentences_mohammad.csv --recipe shadowing_basic --output outputs/shadowing_basic_cached.mp3
```

Then check for cache hits:

```bash
sqlite3 storage/echolingua.sqlite3 "SELECT provider_name, status, COUNT(*) FROM provider_attempts GROUP BY provider_name, status;"
```

Or without the `sqlite3` shell:

```bash
python - <<'PY'
import sqlite3

conn = sqlite3.connect("storage/echolingua.sqlite3")
for row in conn.execute("SELECT provider_name, status, COUNT(*) FROM provider_attempts GROUP BY provider_name, status"):
    print(row)
PY
```

## 12. Provider commands

List configured and enabled TTS providers:

```bash
echolingua providers list
```

Test the fake provider locally:

```bash
echolingua providers test --name fake --text Bonjour
```

The provider test writes a local WAV file under `outputs/provider_tests/`.

## 13. Optional real EdgeTTSProvider test

Edge TTS is optional, disabled by default, and may make network calls. Do not use it in unit tests.

Install optional dependencies:

```bash
python -m pip install -e ".[edge]"
```

Temporarily enable the `edge` provider in `config/providers.yaml`, then run:

```bash
echolingua providers list
echolingua providers test --name edge --text Bonjour
```

If `edge-tts` is not installed, `EdgeTTSProvider` should fail gracefully with a clear installation message.

## 14. Troubleshooting package-index or proxy errors

If installation fails with errors such as `403 Forbidden`, `ProxyError`, `Tunnel connection failed`, or `No matching distribution found` while fetching build dependencies, this is usually an environment or package-index issue rather than an EchoLingua code issue.

Retry locally with normal PyPI access:

```bash
python -m pip install -e ".[dev]"
```

If your organization requires an internal index, configure it explicitly:

```bash
python -m pip install -e ".[dev]" --index-url https://<your-package-index>/simple
```

You can also ask pip to show its active configuration:

```bash
python -m pip config list
```

## 15. Clean runtime artifacts

Generated runtime files are ignored by git at the repository root. Remove them when you want a fresh local run:

```bash
rm -rf logs outputs storage
```
