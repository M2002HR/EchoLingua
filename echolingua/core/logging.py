from __future__ import annotations

import json
import os
import traceback
import uuid
from collections import Counter, defaultdict
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class JsonlLogger:
    def __init__(
        self,
        log_dir: Path,
        diagnostic_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.log_dir = log_dir
        self._diagnostic_sink = diagnostic_sink
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / "jobs").mkdir(parents=True, exist_ok=True)
        (self.log_dir / "traces").mkdir(parents=True, exist_ok=True)

    def event(self, name: str, job_id: str | None = None, **payload: Any) -> None:
        record = self._build_record(event_name=name, job_id=job_id, payload=payload)
        self._write_record(record, trace_path=None, job_id=job_id)

    def trace(
        self,
        operation: str,
        *,
        component: str,
        job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "TraceSession":
        return TraceSession(
            logger=self,
            operation=operation,
            component=component,
            job_id=job_id,
            metadata=metadata or {},
        )

    def _build_record(
        self,
        *,
        event_name: str,
        payload: dict[str, Any] | None = None,
        job_id: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        level: str = "INFO",
        component: str = "echolingua",
        operation: str | None = None,
        status: str = "ok",
        duration_ms: int | None = None,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_name,
            "job_id": job_id,
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "level": level,
            "component": component,
            "operation": operation,
            "status": status,
            "duration_ms": duration_ms,
            "payload": self._normalize(payload or {}),
            "error": self._normalize(error) if error else None,
            "pid": os.getpid(),
        }
        return record

    def _write_record(self, record: dict[str, Any], *, trace_path: Path | None, job_id: str | None) -> None:
        with (self.log_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if trace_path is not None:
            with trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if job_id is not None:
            job_path = self._job_dir(job_id) / "events.jsonl"
            with job_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if self._diagnostic_sink is not None:
            self._diagnostic_sink(record)

    def _trace_paths(self, trace_id: str, job_id: str | None) -> tuple[Path, Path]:
        if job_id is not None:
            base_dir = self._job_dir(job_id)
            return base_dir / f"trace-{trace_id}.jsonl", base_dir / f"summary-{trace_id}.json"
        return self.log_dir / "traces" / f"trace-{trace_id}.jsonl", self.log_dir / "traces" / f"summary-{trace_id}.json"

    def _write_summary(self, summary: dict[str, Any], *, summary_path: Path, job_id: str | None) -> None:
        with summary_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
        if job_id is not None:
            latest_path = self._job_dir(job_id) / "latest-summary.json"
            with latest_path.open("w", encoding="utf-8") as handle:
                json.dump(summary, handle, ensure_ascii=False, indent=2)

    def _job_dir(self, job_id: str) -> Path:
        safe_job_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in job_id) or "job"
        path = self.log_dir / "jobs" / safe_job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _normalize(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(key): self._normalize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._normalize(item) for item in value]
        if hasattr(value, "to_dict") and callable(value.to_dict):
            return self._normalize(value.to_dict())
        if hasattr(value, "__dict__"):
            return self._normalize(vars(value))
        return str(value)


class TraceSession(AbstractContextManager["TraceSession"]):
    def __init__(
        self,
        *,
        logger: JsonlLogger,
        operation: str,
        component: str,
        job_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        self.logger = logger
        self.operation = operation
        self.component = component
        self.job_id = job_id
        self.metadata = metadata
        self.trace_id = uuid.uuid4().hex
        self.started_at = datetime.now(timezone.utc)
        self._trace_path, self._summary_path = self.logger._trace_paths(self.trace_id, self.job_id)
        self._records: list[dict[str, Any]] = []
        self._artifacts: dict[str, Any] = {}
        self._summary: dict[str, Any] = {}
        self._span_stack: list[str] = []
        self._closed = False

    def __enter__(self) -> "TraceSession":
        self.event(
            "trace_started",
            payload={"metadata": self.metadata},
            operation=self.operation,
            status="started",
        )
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> bool:
        status = "completed" if exc is None else "failed"
        error = self._serialize_exception(exc) if exc is not None else None
        self._finalize(status=status, error=error)
        return False

    def event(
        self,
        name: str,
        *,
        payload: dict[str, Any] | None = None,
        level: str = "INFO",
        component: str | None = None,
        operation: str | None = None,
        status: str = "ok",
        duration_ms: int | None = None,
        error: dict[str, Any] | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> dict[str, Any]:
        record = self.logger._build_record(
            event_name=name,
            payload=payload,
            job_id=self.job_id,
            trace_id=self.trace_id,
            span_id=span_id if span_id is not None else self.current_span_id,
            parent_span_id=parent_span_id,
            level=level,
            component=component or self.component,
            operation=operation or self.operation,
            status=status,
            duration_ms=duration_ms,
            error=error,
        )
        self._records.append(record)
        self.logger._write_record(record, trace_path=self._trace_path, job_id=self.job_id)
        return record

    def span(
        self,
        operation: str,
        *,
        component: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> "TraceSpan":
        return TraceSpan(
            session=self,
            operation=operation,
            component=component or self.component,
            payload=payload or {},
        )

    def set_artifact(self, name: str, value: Any) -> None:
        self._artifacts[name] = self.logger._normalize(value)

    def set_summary(self, **payload: Any) -> None:
        for key, value in payload.items():
            self._summary[key] = self.logger._normalize(value)

    @property
    def current_span_id(self) -> str | None:
        return self._span_stack[-1] if self._span_stack else None

    def _push_span(self, span_id: str) -> None:
        self._span_stack.append(span_id)

    def _pop_span(self, span_id: str) -> None:
        if self._span_stack and self._span_stack[-1] == span_id:
            self._span_stack.pop()
            return
        self._span_stack = [item for item in self._span_stack if item != span_id]

    def _serialize_exception(self, exc: BaseException | None) -> dict[str, Any] | None:
        if exc is None:
            return None
        return {
            "type": exc.__class__.__name__,
            "message": str(exc),
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        }

    def _finalize(self, *, status: str, error: dict[str, Any] | None) -> None:
        if self._closed:
            return
        self._closed = True
        finished_at = datetime.now(timezone.utc)
        duration_ms = int((finished_at - self.started_at).total_seconds() * 1000)
        self.event(
            "trace_finished",
            payload={"artifacts": self._artifacts, "summary": self._summary},
            operation=self.operation,
            status=status,
            duration_ms=duration_ms,
            error=error,
            level="ERROR" if error else "INFO",
        )
        summary = self._build_summary(
            started_at=self.started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            status=status,
            error=error,
        )
        self.logger._write_summary(summary, summary_path=self._summary_path, job_id=self.job_id)

    def _build_summary(
        self,
        *,
        started_at: datetime,
        finished_at: datetime,
        duration_ms: int,
        status: str,
        error: dict[str, Any] | None,
    ) -> dict[str, Any]:
        level_counts = Counter(str(record["level"]) for record in self._records)
        status_counts = Counter(str(record["status"]) for record in self._records)
        operation_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "total_duration_ms": 0, "max_duration_ms": 0})
        failures: list[dict[str, Any]] = []
        for record in self._records:
            record_operation = str(record.get("operation") or "")
            record_duration = record.get("duration_ms")
            if record_operation and isinstance(record_duration, int):
                stats = operation_stats[record_operation]
                stats["count"] += 1
                stats["total_duration_ms"] += record_duration
                stats["max_duration_ms"] = max(stats["max_duration_ms"], record_duration)
            if record.get("error"):
                failures.append(
                    {
                        "timestamp": record["timestamp"],
                        "event": record["event"],
                        "operation": record.get("operation"),
                        "status": record.get("status"),
                        "error": record.get("error"),
                    }
                )
        return {
            "trace_id": self.trace_id,
            "job_id": self.job_id,
            "component": self.component,
            "operation": self.operation,
            "status": status,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": duration_ms,
            "metadata": self.logger._normalize(self.metadata),
            "artifacts": self._artifacts,
            "summary": self._summary,
            "event_count": len(self._records),
            "level_counts": dict(level_counts),
            "status_counts": dict(status_counts),
            "operation_stats": dict(sorted(operation_stats.items())),
            "failures": failures,
            "error": error,
            "trace_path": str(self._trace_path),
        }


class TraceSpan(AbstractContextManager["TraceSpan"]):
    def __init__(
        self,
        *,
        session: TraceSession,
        operation: str,
        component: str,
        payload: dict[str, Any],
    ) -> None:
        self.session = session
        self.operation = operation
        self.component = component
        self.payload = payload
        self.span_id = uuid.uuid4().hex
        self.parent_span_id = session.current_span_id
        self.started_at: datetime | None = None
        self._result: dict[str, Any] = {}

    def __enter__(self) -> "TraceSpan":
        self.started_at = datetime.now(timezone.utc)
        self.session._push_span(self.span_id)
        self.session.event(
            "span_started",
            component=self.component,
            operation=self.operation,
            status="started",
            payload=self.payload,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
        )
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> bool:
        assert self.started_at is not None
        duration_ms = int((datetime.now(timezone.utc) - self.started_at).total_seconds() * 1000)
        error = self.session._serialize_exception(exc) if exc is not None else None
        payload = dict(self.payload)
        if self._result:
            payload["result"] = self._result
        self.session.event(
            "span_finished",
            component=self.component,
            operation=self.operation,
            status="failed" if exc is not None else "completed",
            duration_ms=duration_ms,
            payload=payload,
            error=error,
            level="ERROR" if exc is not None else "INFO",
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
        )
        self.session._pop_span(self.span_id)
        return False

    def set_result(self, **payload: Any) -> None:
        for key, value in payload.items():
            self._result[key] = self.session.logger._normalize(value)

    def event(self, name: str, **payload: Any) -> dict[str, Any]:
        return self.session.event(
            name,
            component=self.component,
            operation=self.operation,
            payload=payload,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
        )
