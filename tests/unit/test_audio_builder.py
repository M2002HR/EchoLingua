from pathlib import Path
import struct
import wave

from echolingua.audio.builder import AudioBuilder
from echolingua.providers.selector import ProviderSelectionPolicy, ProviderSelector
from echolingua.providers.tts.fake import FakeTTSProvider
from echolingua.recipes.planner import AudioPlan, AudioPlanSegment


def test_audio_builder_with_fake_provider(tmp_path: Path) -> None:
    plan = AudioPlan(
        job_id="job-1",
        recipe_name="test",
        output_format="mp3",
        segments=[AudioPlanSegment(kind="tts", sentence_id="1", text="Bonjour", voice="fake-fr", language="fr", sequence=1)],
    )
    selector = ProviderSelector([FakeTTSProvider()], ProviderSelectionPolicy())
    output = tmp_path / "out.mp3"
    info = AudioBuilder(selector, tmp_path / "cache").build(plan, output, output_format="wav")
    assert output.exists()
    assert info["duration_ms"] > 0
    with wave.open(str(output), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
    samples = struct.unpack("<" + "h" * (len(frames) // 2), frames)
    assert max(abs(sample) for sample in samples) > 0
