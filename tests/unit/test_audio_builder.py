from pathlib import Path

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
    info = AudioBuilder(selector, tmp_path / "cache").build(plan, output)
    assert output.exists()
    assert info["duration_ms"] > 0
