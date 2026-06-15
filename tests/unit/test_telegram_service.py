from pathlib import Path

from echolingua.core.config import load_config
from echolingua.telegram_bot.service import TelegramBotService


def test_telegram_service_import_export_and_caption(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(Path("/home/mhr/Code/EchoLingua"))
    base = load_config()
    config = type(base)(
        root_dir=tmp_path,
        default=base.default,
        providers=base.providers,
        recipes=base.recipes,
    )
    service = TelegramBotService(config)
    service.ensure_user(
        telegram_user_id=1001,
        chat_id=2001,
        username="alice",
        first_name="Alice",
        last_name="Demo",
        language_code="fa",
    )
    import_result = service.import_csv_for_user(1001, Path("/home/mhr/Code/EchoLingua/data/sample.csv"), "sample.csv")
    assert len(import_result["imported_sentence_ids"]) == 100
    settings = service.get_settings(1001)
    assert settings.selected_recipe == "persian_prompt_french_ladder"
    sentences = service.list_user_sentences(1001)
    assert len(sentences) == 100
    caption = service.build_caption(sentences[0])
    assert "فارسی" in caption
    assert "English" in caption
    assert "Français" in caption
    export_path = service.export_user_csv(1001)
    assert export_path.exists()


def test_telegram_service_custom_recipe_and_user_library_snapshot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(Path("/home/mhr/Code/EchoLingua"))
    base = load_config()
    config = type(base)(
        root_dir=tmp_path,
        default=base.default,
        providers=base.providers,
        recipes=base.recipes,
    )
    service = TelegramBotService(config)
    service.ensure_user(
        telegram_user_id=1002,
        chat_id=2002,
        username="bob",
        first_name="Bob",
        last_name="Demo",
        language_code="fa",
    )
    service.import_csv_for_user(1002, Path("/home/mhr/Code/EchoLingua/data/sample.csv"), "sample.csv")

    custom = service.create_or_update_custom_recipe(
        1002,
        {
            "prompt_field": "english",
            "pause_between_ms": 4500,
            "word_pause_ms": 1200,
            "normal_voice": "fr-FR-HenriNeural",
        },
    )
    assert custom["prompt_field"] == "english"
    assert custom["pause_between_ms"] == 4500
    resolved = service.resolve_recipe_for_user(1002, "telegram_custom_ladder")
    assert resolved["recipe_name"] == "telegram_custom_ladder"
    assert "word-by-word" in resolved["summary"]

    all_sentences = service.list_user_sentences(1002)
    removed_id = all_sentences[0].id
    service.remove_sentence_from_user(1002, removed_id)
    remaining_ids = [sentence.id for sentence in service.list_user_sentences(1002)]
    assert removed_id not in remaining_ids

    service.add_sentence_to_user(1002, removed_id)
    restored_ids = [sentence.id for sentence in service.list_user_sentences(1002)]
    assert removed_id in restored_ids

    page = service.paginated_user_sentences(1002, 0, page_size=5)
    assert page["page_size"] == 5
    assert len(page["items"]) == 5
