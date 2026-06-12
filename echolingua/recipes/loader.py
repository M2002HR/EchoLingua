from __future__ import annotations

from typing import Any

from echolingua.core.errors import ConfigError
from echolingua.recipes.models import Recipe, RecipeSegment


def load_recipes(config: dict[str, Any]) -> dict[str, Recipe]:
    recipes: dict[str, Recipe] = {}
    for name, data in (config.get("recipes") or {}).items():
        segments = [RecipeSegment.from_dict(segment) for segment in data.get("segments", [])]
        if not segments:
            raise ConfigError(f"Recipe {name} has no segments")
        recipes[name] = Recipe(
            name=name,
            description=str(data.get("description", "")),
            output_format=str(data.get("output_format", "mp3")),
            provider_policy=data.get("provider_policy") or {},
            segments=segments,
        )
    return recipes


def get_recipe(config: dict[str, Any], name: str) -> Recipe:
    recipes = load_recipes(config)
    if name not in recipes:
        raise ConfigError(f"Unknown recipe: {name}")
    return recipes[name]
