from echolingua.core.config import load_config
from echolingua.recipes.loader import get_recipe
from echolingua.recipes.planner import AudioPlanBuilder
from echolingua.sentences.loader import load_sentences


def test_audio_plan_generation() -> None:
    config = load_config()
    recipe = get_recipe(config.recipes, "shadowing_basic")
    sentences = load_sentences(config.root_dir / "data" / "sample.csv")[:2]
    plan = AudioPlanBuilder().build("job-1", recipe, sentences, source_csv_path="data/sample.csv")
    assert plan.job_id == "job-1"
    assert plan.estimate_segment_count() == 10
    assert plan.segments[0].text == "سلام."
    assert plan.source_csv_path == "data/sample.csv"


def test_audio_plan_generation_with_english_then_target() -> None:
    config = load_config()
    recipe = get_recipe(config.recipes, "english_then_target")
    sentences = load_sentences(config.root_dir / "data" / "sample.csv")[:1]
    plan = AudioPlanBuilder().build("job-2", recipe, sentences, target_column="french")
    assert plan.recipe_name == "english_then_target"
    assert plan.segments[0].text == "Hello."
    assert plan.segments[2].text == "Salut."
