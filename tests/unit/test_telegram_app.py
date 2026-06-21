from pathlib import Path

import pytest

telegram = pytest.importorskip("telegram")
from telegram.error import NetworkError

from echolingua.core.config import load_config
from echolingua.telegram_bot.app import build_application, _resolve_startup_proxy_url

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _test_config(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(PROJECT_ROOT)
    base = load_config()
    return type(base)(
        root_dir=tmp_path,
        default=base.default,
        providers=base.providers,
        recipes=base.recipes,
    )


def test_build_application_allows_proxy_override(tmp_path: Path, monkeypatch) -> None:
    config = _test_config(tmp_path, monkeypatch)
    app = build_application(config=config, proxy_url_override=None)
    request = app.bot.request
    assert request is app.bot.get_updates_request()
    assert getattr(request, "_client")._trust_env is False


@pytest.mark.parametrize("probe_result,expected", [(None, "http://127.0.0.1:3128"), (NetworkError("boom"), None)])
def test_resolve_startup_proxy_url_falls_back_when_probe_fails(tmp_path: Path, monkeypatch, probe_result, expected) -> None:
    config = _test_config(tmp_path, monkeypatch)

    async def fake_probe(token: str, proxy_url: str | None) -> None:
        assert token == config.telegram_bot_token
        assert proxy_url == "http://127.0.0.1:3128"
        if isinstance(probe_result, Exception):
            raise probe_result

    assert _resolve_startup_proxy_url(config, probe=fake_probe) == expected
