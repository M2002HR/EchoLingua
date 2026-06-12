from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import importlib.util

from echolingua.core.config_validation import validate_app_config
from echolingua.core.simple_yaml import loads as simple_yaml_loads

if importlib.util.find_spec("dotenv") is not None:
    from dotenv import load_dotenv
else:
    def load_dotenv(path: Path) -> None:
        return None


@dataclass(frozen=True)
class AppConfig:
    root_dir: Path
    default: dict[str, Any]
    providers: dict[str, Any]
    recipes: dict[str, Any]

    @property
    def db_path(self) -> Path:
        return self.root_dir / os.getenv("ECHOLINGUA_DB_PATH", self.default["paths"]["database"])

    @property
    def output_dir(self) -> Path:
        return self.root_dir / os.getenv("ECHOLINGUA_OUTPUT_DIR", self.default["paths"]["outputs"])

    @property
    def log_dir(self) -> Path:
        return self.root_dir / os.getenv("ECHOLINGUA_LOG_DIR", self.default["paths"]["logs"])

    @property
    def tts_cache_dir(self) -> Path:
        return self.root_dir / self.default["paths"].get("tts_cache", "storage/tts_cache")


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        if importlib.util.find_spec("yaml") is not None:
            import yaml

            return yaml.safe_load(handle) or {}
        return simple_yaml_loads(handle.read())


def load_config(root_dir: Path | None = None) -> AppConfig:
    root = (root_dir or Path.cwd()).resolve()
    load_dotenv(root / ".env")
    default = _read_yaml(root / "config" / "default.yaml")
    providers = _read_yaml(root / "config" / "providers.yaml")
    recipes = _read_yaml(root / "config" / "recipes.yaml")
    validate_app_config(default, providers, recipes)
    return AppConfig(
        root_dir=root,
        default=default,
        providers=providers,
        recipes=recipes,
    )
