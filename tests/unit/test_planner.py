from echolingua.core.config import load_config
from echolingua.recipes.loader import get_recipe
from echolingua.recipes.planner import AudioPlanBuilder
from echolingua.sentences.loader import load_sentences


def test_audio_plan_generation() -> None:
    config = load_config()
    recipe = get_recipe(config.recipes, "shadowing_basic")
    sentences = load_sentences(config.root_dir / "data/french_100_sentences_mohammad.csv")[:2]
    plan = AudioPlanBuilder().build("job-1", recipe, sentences)
    assert plan.job_id == "job-1"
    assert plan.estimate_segment_count() == 10
    assert plan.segments[0].text == "سلام"
