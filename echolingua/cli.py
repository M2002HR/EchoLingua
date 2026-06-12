from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import importlib.util

if importlib.util.find_spec("typer") is not None:
    import typer
else:
    class _TyperShim:
        def Typer(self, help: str | None = None):
            return self

        def add_typer(self, app, name: str):
            return None

        def command(self, name: str | None = None):
            def decorator(func):
                return func
            return decorator

        def Argument(self, default, help: str | None = None):
            return default

        def Option(self, default, help: str | None = None):
            return default

        def echo(self, message):
            print(message)

        def Exit(self, code: int = 0):
            return SystemExit(code)

        def __call__(self):
            raise RuntimeError("Typer is not installed. Install project dependencies to use the CLI.")

    typer = _TyperShim()

from echolingua.core.config import load_config
from echolingua.core.errors import EchoLinguaError
from echolingua.core.progress import build_progress_reporter
from echolingua.pipeline.jobs import new_job_id
from echolingua.pipeline.runner import PipelineRunner

app = typer.Typer(help="EchoLingua language-learning audio pipeline")
providers_app = typer.Typer(help="Provider commands")
logs_app = typer.Typer(help="Log commands")
app.add_typer(providers_app, name="providers")
app.add_typer(logs_app, name="logs")


def _echo_json(payload: object) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _run_command(action) -> None:
    try:
        action()
    except EchoLinguaError as exc:
        typer.echo(f"Error: {exc}")
        raise SystemExit(1) from exc


def _format_validation(report: dict[str, object]) -> None:
    for key in [
        "total_rows",
        "enabled_rows",
        "disabled_rows",
        "valid_rows",
        "invalid_rows",
        "duplicate_ids",
        "missing_required_fields",
        "levels_summary",
        "categories_summary",
    ]:
        typer.echo(f"{key}: {report[key]}")
    issues = report.get("issues", [])
    if issues:
        typer.echo("issues:")
        for issue in issues:
            typer.echo(
                f"- row {issue['row_number']} id={issue['row_id'] or '<missing>'}: {issue['message']}"
            )


@app.command("validate")
def validate(
    csv_path: Path = typer.Argument(..., help="Input bilingual sentence CSV"),
    strict: bool = typer.Option(True, "--strict/--no-strict", help="Exit non-zero if validation fails"),
) -> None:
    def _action() -> None:
        runner = PipelineRunner(load_config())
        report = runner.validate_csv(csv_path)
        _format_validation(report.to_dict())
        if strict and not report.is_valid:
            raise SystemExit(1)

    _run_command(_action)


@app.command("dry-run")
def dry_run(
    csv_path: Path = typer.Argument(..., help="Input bilingual sentence CSV"),
    recipe: str = typer.Option("shadowing_basic", help="Recipe name"),
    from_sentence_id: Optional[str] = typer.Option(None, "--from", help="Inclusive starting sentence id"),
    to_sentence_id: Optional[str] = typer.Option(None, "--to", help="Inclusive ending sentence id"),
    job_id: Optional[str] = typer.Option(None, help="Existing job id or generated if omitted"),
) -> None:
    def _action() -> None:
        runner = PipelineRunner(load_config())
        summary = runner.build_plan_summary(
            job_id or new_job_id(),
            csv_path,
            recipe,
            from_sentence_id=from_sentence_id,
            to_sentence_id=to_sentence_id,
        )
        _echo_json(summary)

    _run_command(_action)


@app.command()
def generate(
    csv_path: Path = typer.Argument(..., help="Input bilingual sentence CSV"),
    recipe: str = typer.Option("shadowing_basic", help="Recipe name"),
    from_sentence_id: Optional[str] = typer.Option(None, "--from", help="Inclusive starting sentence id"),
    to_sentence_id: Optional[str] = typer.Option(None, "--to", help="Inclusive ending sentence id"),
    output: Optional[Path] = typer.Option(None, help="Output audio path"),
    job_id: Optional[str] = typer.Option(None, help="Existing job id or generated if omitted"),
    no_progress: bool = typer.Option(False, "--no-progress", help="Disable progress display"),
) -> None:
    def _action() -> None:
        result = PipelineRunner(load_config()).generate(
            job_id or new_job_id(),
            csv_path,
            recipe,
            output,
            from_sentence_id=from_sentence_id,
            to_sentence_id=to_sentence_id,
            progress_reporter=build_progress_reporter(no_progress=no_progress),
        )
        _echo_json({"output": result["output"]["path"], "manifest": str(result["manifest_path"])})

    _run_command(_action)


@app.command("generate-folder")
def generate_folder(
    csv_path: Path = typer.Argument(..., help="Input bilingual sentence CSV"),
    output_dir: Path = typer.Argument(..., help="Output folder for per-sentence files"),
    recipe: str = typer.Option("shadowing_basic", help="Recipe name"),
    from_sentence_id: Optional[str] = typer.Option(None, "--from", help="Inclusive starting sentence id"),
    to_sentence_id: Optional[str] = typer.Option(None, "--to", help="Inclusive ending sentence id"),
    output_format: str = typer.Option("wav", help="Output audio format for each sentence file"),
    job_id: Optional[str] = typer.Option(None, help="Existing job id or generated if omitted"),
    no_progress: bool = typer.Option(False, "--no-progress", help="Disable progress display"),
) -> None:
    def _action() -> None:
        result = PipelineRunner(load_config()).generate_sentence_files(
            job_id or new_job_id(),
            csv_path,
            recipe,
            output_dir,
            output_format=output_format,
            from_sentence_id=from_sentence_id,
            to_sentence_id=to_sentence_id,
            progress_reporter=build_progress_reporter(no_progress=no_progress),
        )
        _echo_json(
            {
                "job_id": result["job_id"],
                "output_dir": result["output_dir"],
                "file_count": result["file_count"],
                "files": [
                    {
                        "sentence_id": item["sentence_id"],
                        "output": item["output"],
                        "manifest": item["manifest"],
                    }
                    for item in result["files"]
                ],
            }
        )

    _run_command(_action)


@providers_app.command("list")
def providers_list(kind: str = typer.Option("tts", help="Provider kind")) -> None:
    def _action() -> None:
        rows = PipelineRunner(load_config()).list_providers(kind)
        _echo_json(rows)

    _run_command(_action)


@providers_app.command("test")
def providers_test(
    name: str = typer.Argument(..., help="Provider name"),
    text: str = typer.Option("Bonjour", help="Text to synthesize"),
) -> None:
    def _action() -> None:
        result = PipelineRunner(load_config()).test_provider(name, text)
        _echo_json(result)

    _run_command(_action)


@app.command("stats")
def stats() -> None:
    runner = PipelineRunner(load_config())
    if not runner.db_preexisting:
        typer.echo("No SQLite database found yet. Run generate first to create runtime stats.")
        return
    _echo_json(runner.stats().to_dict())


@app.command("cache-stats")
def cache_stats() -> None:
    runner = PipelineRunner(load_config())
    if not runner.config.tts_cache_dir.exists():
        typer.echo("No cache directory found yet.")
        return
    summary = runner.cache_stats()
    if summary.entry_count == 0:
        typer.echo("No cache entries found yet.")
        return
    _echo_json(summary.to_dict())


@logs_app.command("tail")
def logs_tail(lines: int = typer.Option(50, help="Number of log lines to show")) -> None:
    runner = PipelineRunner(load_config())
    entries = runner.tail_logs(lines)
    if not entries:
        typer.echo("No log file found yet.")
        return
    for entry in entries:
        typer.echo(entry)


if __name__ == "__main__":
    app()
