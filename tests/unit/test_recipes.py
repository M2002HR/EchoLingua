from echolingua.core.config import load_config
from echolingua.recipes.loader import get_recipe, load_recipes


def test_recipe_loading() -> None:
    config = load_config()
    recipes = load_recipes(config.recipes)
    assert "shadowing_basic" in recipes
    assert get_recipe(config.recipes, "active_recall").segments[1].duration_ms == 2500
