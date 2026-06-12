from pathlib import Path
import struct
import wave

from echolingua.providers.tts.base import TTSRequest
from echolingua.providers.tts.fake import FakeTTSProvider


def test_fake_tts_generates_local_audio(tmp_path: Path) -> None:
    output = tmp_path / "fake.wav"
    result = FakeTTSProvider().synthesize(TTSRequest(text="Bonjour", voice="fake-fr", language="fr"), output)
    assert result.path.exists()
    assert result.duration_ms > 0
    with wave.open(str(output), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
    samples = struct.unpack("<" + "h" * (len(frames) // 2), frames)
    assert max(abs(sample) for sample in samples) > 0
