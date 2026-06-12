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

        def __call__(self):
            raise RuntimeError("Typer is not installed. Install project dependencies to use the CLI.")

    typer = _TyperShim()

from echolingua.core.config import load_config
from echolingua.pipeline.jobs import new_job_id
from echolingua.pipeline.runner import PipelineRunner
from echolingua.providers.registry import build_registry
from echolingua.providers.tts.base import TTSRequest

app = typer.Typer(help="EchoLingua language-learning audio pipeline")
providers_app = typer.Typer(help="Provider commands")
app.add_typer(providers_app, name="providers")


@app.command("dry-run")
def dry_run(
    csv_path: Path = typer.Argument(..., help="Input bilingual sentence CSV"),
    recipe: str = typer.Option("shadowing_basic", help="Recipe name"),
    job_id: Optional[str] = typer.Option(None, help="Existing job id or generated if omitted"),
) -> None:
    config = load_config()
    runner = PipelineRunner(config)
    plan = runner.build_plan(job_id or new_job_id(), csv_path, recipe)
    typer.echo(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    typer.echo(f"Estimated segment count: {plan.estimate_segment_count()}")


@app.command()
def generate(
    csv_path: Path = typer.Argument(..., help="Input bilingual sentence CSV"),
    recipe: str = typer.Option("shadowing_basic", help="Recipe name"),
    output: Optional[Path] = typer.Option(None, help="Output MP3 path"),
    job_id: Optional[str] = typer.Option(None, help="Existing job id or generated if omitted"),
) -> None:
    config = load_config()
    result = PipelineRunner(config).generate(job_id or new_job_id(), csv_path, recipe, output)
    typer.echo(json.dumps({"output": result["output"]["path"], "manifest": str(result["manifest_path"])}, ensure_ascii=False, indent=2))


@providers_app.command("list")
def providers_list(kind: str = typer.Option("tts", help="Provider kind")) -> None:
    config = load_config()
    registry = build_registry(config.providers)
    rows = [
        {"name": provider.metadata.name, "kind": provider.metadata.kind, "priority": provider.metadata.priority}
        for provider in registry.list(kind)
    ]
    typer.echo(json.dumps(rows, indent=2))


@providers_app.command("test")
def providers_test(name: str = typer.Option("fake", help="Provider name"), text: str = typer.Option("Bonjour", help="Text to synthesize")) -> None:
    config = load_config()
    registry = build_registry(config.providers)
    provider = registry.get("tts", name)
    output = config.output_dir / "provider_tests" / f"{name}.wav"
    result = provider.synthesize(TTSRequest(text=text, voice="fake-neutral", language="fr"), output)
    typer.echo(json.dumps({"provider": name, "path": str(result.path), "duration_ms": result.duration_ms}, indent=2))


if __name__ == "__main__":
    app()
