from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile

from echolingua.core.errors import ProviderError
from echolingua.providers.base import ProviderMetadata
from echolingua.providers.tts.base import TTSRequest, TTSResult


class EdgeTTSProvider:
    def __init__(self, name: str = "edge", priority: int = 20, enabled: bool = True, config: dict | None = None) -> None:
        self.metadata = ProviderMetadata(name=name, kind="tts", priority=priority, enabled=enabled, config=config or {})

    def synthesize(self, request: TTSRequest, output_path: Path) -> TTSResult:
        if importlib.util.find_spec("edge_tts") is None:
            raise ProviderError("edge-tts is not installed. Install with: pip install 'echolingua[edge]'")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(suffix=".mp3", dir=output_path.parent, delete=False) as handle:
            temp_mp3 = Path(handle.name)
        try:
            self._save_mp3(request, temp_mp3)
            desired_format = (output_path.suffix.lstrip(".") or "wav").lower()
            if desired_format == "mp3":
                temp_mp3.replace(output_path)
            else:
                self._transcode_audio(temp_mp3, output_path, desired_format)
            duration_ms = self._duration_ms(output_path)
            return TTSResult(path=output_path, duration_ms=duration_ms, cached=False)
        except Exception as exc:
            raise ProviderError(f"Edge TTS synthesis failed: {exc}") from exc
        finally:
            if temp_mp3.exists():
                temp_mp3.unlink()

    def _save_mp3(self, request: TTSRequest, output_path: Path) -> None:
        import edge_tts

        async def _run() -> None:
            communicate = edge_tts.Communicate(
                text=request.text,
                voice=request.voice,
                rate=request.rate,
                pitch=request.pitch,
                volume=request.volume,
            )
            await communicate.save(str(output_path))

        asyncio.run(_run())

    def _transcode_audio(self, input_path: Path, output_path: Path, output_format: str) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise ProviderError("ffmpeg is required to convert edge-tts output. Install ffmpeg or request MP3 output.")
        completed = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(input_path),
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise ProviderError(completed.stderr.strip() or f"ffmpeg failed while converting to {output_format}.")

    def _duration_ms(self, path: Path) -> int:
        ffprobe = shutil.which("ffprobe")
        if ffprobe is not None:
            completed = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                payload = json.loads(completed.stdout)
                duration = payload.get("format", {}).get("duration")
                if duration is not None:
                    return max(0, int(float(duration) * 1000))
        return 0
