from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class JobProgress:
    stage: str
    message: str
    completed_steps: int
    total_steps: int
    status: str = "running"

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "message": self.message,
            "completed_steps": self.completed_steps,
            "total_steps": self.total_steps,
            "status": self.status,
        }


class ProgressReporter(Protocol):
    def start(self, progress: JobProgress) -> None:
        ...

    def update(self, progress: JobProgress) -> None:
        ...

    def stop(self, progress: JobProgress | None = None) -> None:
        ...


class NullProgressReporter:
    def start(self, progress: JobProgress) -> None:
        return None

    def update(self, progress: JobProgress) -> None:
        return None

    def stop(self, progress: JobProgress | None = None) -> None:
        return None


class RichProgressReporter:
    def __init__(self) -> None:
        from rich.console import Console
        from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

        self.console = Console(stderr=True)
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=self.console,
            transient=False,
        )
        self._task_id: int | None = None
        self._started = False

    def start(self, progress: JobProgress) -> None:
        if self._started:
            return
        self._progress.start()
        self._task_id = self._progress.add_task(self._description(progress), total=max(progress.total_steps, 1), completed=progress.completed_steps)
        self._started = True

    def update(self, progress: JobProgress) -> None:
        if not self._started:
            self.start(progress)
            return
        assert self._task_id is not None
        self._progress.update(
            self._task_id,
            description=self._description(progress),
            total=max(progress.total_steps, 1),
            completed=progress.completed_steps,
        )

    def stop(self, progress: JobProgress | None = None) -> None:
        if progress is not None:
            self.update(progress)
        if self._started:
            self._progress.stop()
            self._started = False

    def _description(self, progress: JobProgress) -> str:
        return f"{progress.stage}: {progress.message}"


def build_progress_reporter(no_progress: bool = False) -> ProgressReporter:
    if no_progress or not sys.stderr.isatty():
        return NullProgressReporter()
    if importlib.util.find_spec("rich") is None:
        return NullProgressReporter()
    return RichProgressReporter()
