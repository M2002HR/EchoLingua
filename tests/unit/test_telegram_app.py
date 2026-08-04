import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

telegram = pytest.importorskip("telegram")
from telegram.error import NetworkError

from echolingua.core.config import load_config
from echolingua.telegram_bot.app import (
    _run_send_all_sentences,
    build_application,
    handle_callback,
    handle_text_input,
    send_all_sentences,
    _resolve_startup_proxy_url,
)
from echolingua.telegram_bot.service import TelegramBotService

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
    assert request is app.bot.request
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


class _DummyMessage:
    def __init__(self) -> None:
        self.replies: list[dict[str, object]] = []
        self.edits: list[dict[str, object]] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append({"text": text, **kwargs})

    async def edit_text(self, text: str, **kwargs) -> None:
        self.edits.append({"text": text, **kwargs})


class _DummyCallbackQuery:
    def __init__(self, user_id: int, data: str, message: _DummyMessage) -> None:
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(id=user_id)

    async def answer(self) -> None:
        return None


class _DummyUpdate:
    def __init__(self, user_id: int, *, callback_data: str | None = None, text: str | None = None, message: _DummyMessage | None = None) -> None:
        self.effective_user = SimpleNamespace(id=user_id)
        self.effective_chat = SimpleNamespace(id=user_id)
        self.effective_message = message or _DummyMessage()
        self.callback_query = _DummyCallbackQuery(user_id, callback_data, self.effective_message) if callback_data is not None else None
        if text is not None:
            self.effective_message.text = text


class _DummyContext:
    def __init__(self, service: TelegramBotService) -> None:
        self.user_data: dict[str, object] = {}
        self.bot = _DummyBot()
        self.application = _DummyApplication(service)


class _DummyTask:
    def __init__(self, *, done: bool = False) -> None:
        self._done = done
        self.callbacks: list[object] = []

    def done(self) -> bool:
        return self._done

    def add_done_callback(self, callback) -> None:
        self.callbacks.append(callback)


class _DummyApplication:
    def __init__(self, service: TelegramBotService) -> None:
        self.bot_data = {"service": service}
        self.created_coroutines: list[object] = []

    def create_task(self, coro):
        self.created_coroutines.append(coro)
        coro.close()
        return _DummyTask(done=False)


class _DummyBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.audios: list[dict[str, object]] = []
        self.chat_actions: list[dict[str, object]] = []

    async def send_message(self, **kwargs) -> None:
        self.messages.append(kwargs)

    async def send_audio(self, **kwargs) -> None:
        self.audios.append(kwargs)

    async def send_chat_action(self, **kwargs) -> None:
        self.chat_actions.append(kwargs)


def test_import_existing_category_callback_completes(tmp_path: Path, monkeypatch) -> None:
    config = _test_config(tmp_path, monkeypatch)
    service = TelegramBotService(config)
    service.ensure_user(telegram_user_id=42, chat_id=42, username="importer")
    category = service.create_library_category(42, "First 100")

    import_source = PROJECT_ROOT / "data/sample.csv"
    pending_copy = config.telegram_import_dir / "sample.csv"
    pending_copy.parent.mkdir(parents=True, exist_ok=True)
    pending_copy.write_bytes(import_source.read_bytes())

    context = _DummyContext(service)
    context.user_data["pending_import_path"] = str(pending_copy)
    context.user_data["pending_import_file_name"] = "sample.csv"
    update = _DummyUpdate(42, callback_data=f"library:category:import_here:{category.key}")

    asyncio.run(handle_callback(update, context))

    assert update.effective_message.edits
    assert "ایمپورت انجام شد" in update.effective_message.edits[-1]["text"]
    assert service.library_category_summary(42, category.key)["sentence_count"] == 100


def test_import_new_category_text_flow_completes(tmp_path: Path, monkeypatch) -> None:
    config = _test_config(tmp_path, monkeypatch)
    service = TelegramBotService(config)
    service.ensure_user(telegram_user_id=77, chat_id=77, username="creator")

    import_source = PROJECT_ROOT / "data/sample.csv"
    pending_copy = config.telegram_import_dir / "sample.csv"
    pending_copy.parent.mkdir(parents=True, exist_ok=True)
    pending_copy.write_bytes(import_source.read_bytes())

    context = _DummyContext(service)
    context.user_data["awaiting_input"] = "import_new_category_name"
    context.user_data["pending_import_path"] = str(pending_copy)
    context.user_data["pending_import_file_name"] = "sample.csv"
    update = _DummyUpdate(77, text="Fresh Import")

    asyncio.run(handle_text_input(update, context))

    assert update.effective_message.replies
    assert "ایمپورت انجام شد" in update.effective_message.replies[-1]["text"]
    assert service.library_category_summary(77, "fresh_import")["sentence_count"] == 100


def test_send_all_sentences_schedules_background_job(tmp_path: Path, monkeypatch) -> None:
    config = _test_config(tmp_path, monkeypatch)
    service = TelegramBotService(config)
    service.ensure_user(telegram_user_id=55, chat_id=55, username="sender")
    service.import_csv_for_user(55, PROJECT_ROOT / "data/sample.csv", "sample.csv", new_category_name="Batch")
    service.set_selected_library_category(55, "batch")

    context = _DummyContext(service)
    update = _DummyUpdate(55, text="🎧 ارسال همه")

    asyncio.run(send_all_sentences(update, context))

    assert update.effective_message.replies
    assert "شروع ارسال 100 ویس" in update.effective_message.replies[-1]["text"]
    assert len(context.application.created_coroutines) == 1
    assert "55:batch" in context.application.bot_data["active_send_all_jobs"]


def test_send_all_sentences_rejects_duplicate_running_job(tmp_path: Path, monkeypatch) -> None:
    config = _test_config(tmp_path, monkeypatch)
    service = TelegramBotService(config)
    service.ensure_user(telegram_user_id=56, chat_id=56, username="sender")
    service.import_csv_for_user(56, PROJECT_ROOT / "data/sample.csv", "sample.csv", new_category_name="Batch")
    service.set_selected_library_category(56, "batch")

    context = _DummyContext(service)
    context.application.bot_data["active_send_all_jobs"] = {"56:batch": _DummyTask(done=False)}
    update = _DummyUpdate(56, text="🎧 ارسال همه")

    asyncio.run(send_all_sentences(update, context))

    assert update.effective_message.replies
    assert "از قبل در حال اجراست" in update.effective_message.replies[-1]["text"]
    assert context.application.created_coroutines == []


def test_run_send_all_sentences_continues_after_item_failure(tmp_path: Path, monkeypatch) -> None:
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFFtestWAVEfmt ")

    class _Service:
        def generate_sentence_audio_for_user(self, telegram_user_id: int, sentence_id: str, *, library_category_key: str):
            if sentence_id == "2":
                raise RuntimeError("boom")
            return {
                "audio_path": audio_path,
                "caption": f"caption-{sentence_id}",
                "recipe_name": "recipe-x",
            }

    bot = _DummyBot()
    asyncio.run(
        _run_send_all_sentences(
            bot=bot,
            service=_Service(),
            chat_id=99,
            telegram_user_id=99,
            category_key="batch",
            category_display_name="Batch",
            sentence_ids=["1", "2", "3"],
        )
    )

    assert len(bot.audios) == 2
    assert any("ناموفق" in str(message["text"]) for message in bot.messages)
