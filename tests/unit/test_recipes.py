from echolingua.core.config import load_config
from echolingua.recipes.loader import get_recipe, load_recipes


def test_recipe_loading() -> None:
    config = load_config()
    recipes = load_recipes(config.recipes)
    assert "shadowing_basic" in recipes
    assert "english_then_target" in recipes
    assert get_recipe(config.recipes, "active_recall").segments[1].duration_ms == 2500
    assert get_recipe(config.recipes, "english_then_target").segments[0].text_field == "english"
    assert get_recipe(config.recipes, "shadowing_basic").provider_policy["tts"]["default_provider"] == "fake"
