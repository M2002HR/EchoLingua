from pathlib import Path

from echolingua.core.config import load_config
from echolingua.telegram_bot.service import TelegramBotService

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_telegram_service_import_export_and_caption(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(PROJECT_ROOT)
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
    import_result = service.import_csv_for_user(1001, PROJECT_ROOT / "data/sample.csv", "sample.csv")
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


def test_telegram_service_caption_does_not_repeat_target_language(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(PROJECT_ROOT)
    base = load_config()
    config = type(base)(
        root_dir=tmp_path,
        default=base.default,
        providers=base.providers,
        recipes=base.recipes,
    )
    service = TelegramBotService(config)
    service.ensure_user(
        telegram_user_id=1004,
        chat_id=2004,
        username="dina",
        first_name="Dina",
        last_name="Demo",
        language_code="fa",
    )
    service.import_csv_for_user(1004, PROJECT_ROOT / "data/sample.csv", "sample.csv")
    sentence = service.list_user_sentences(1004)[0]

    french_caption = service.build_caption(sentence, target_language="fr")
    assert french_caption.count("🇫🇷 Français:") == 1
    assert "🇬🇧 English:" in french_caption

    english_caption = service.build_caption(sentence, target_language="en")
    assert english_caption.count("🇬🇧 English:") == 1
    assert "🇫🇷 Français:" in english_caption


def test_telegram_service_custom_recipe_and_user_library_snapshot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(PROJECT_ROOT)
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
    service.import_csv_for_user(1002, PROJECT_ROOT / "data/sample.csv", "sample.csv")

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
    assert resolved["recipe_name"] == "telegram_custom_ladder_fr"
    assert "word-by-word" in resolved["summary"]

    all_sentences = service.list_user_sentences(1002)
    removed_id = all_sentences[0].id
    service.remove_sentence_from_user(1002, removed_id)
    remaining_ids = [sentence.id for sentence in service.list_user_sentences(1002)]
    assert removed_id not in remaining_ids

    service.add_sentence_to_user(1002, removed_id)
    restored_ids = [sentence.id for sentence in service.list_user_sentences(1002)]
    assert removed_id in restored_ids

    service.update_settings(1002, extra_config={"target_language": "fr", "page_size": 5})
    page = service.paginated_user_sentences(1002, 0, page_size=5)
    assert page["page_size"] == 5
    assert len(page["items"]) == 5


def test_telegram_service_target_language_and_manual_sentence_flow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(PROJECT_ROOT)
    base = load_config()
    config = type(base)(
        root_dir=tmp_path,
        default=base.default,
        providers=base.providers,
        recipes=base.recipes,
    )
    service = TelegramBotService(config)
    service.ensure_user(
        telegram_user_id=1003,
        chat_id=2003,
        username="cara",
        first_name="Cara",
        last_name="Demo",
        language_code="en",
    )
    service.set_target_language(1003, "en")
    sentence = service.add_sentence_from_target_text(
        1003,
        target_language="en",
        target_text="Good morning",
        translation_text="صبح بخیر",
    )
    assert sentence.english == "Good morning"
    assert sentence.persian == "صبح بخیر"
    assert service.build_caption(sentence, target_language="en").splitlines()[0].startswith("🇬🇧 English:")

    updated = service.update_sentence_for_user(1003, sentence.id, english="Good morning!", persian="صبح عالی")
    assert updated.english == "Good morning!"
    assert updated.persian == "صبح عالی"

    resolved = service.resolve_recipe_for_user(1003, "shadowing_basic")
    assert resolved["recipe_name"] == "shadowing_basic_en_tg"
    assert "English" in resolved["summary"]


def test_telegram_service_user_recipe_create_update_and_resolve(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(PROJECT_ROOT)
    base = load_config()
    config = type(base)(
        root_dir=tmp_path,
        default=base.default,
        providers=base.providers,
        recipes=base.recipes,
    )
    service = TelegramBotService(config)
    service.ensure_user(
        telegram_user_id=1005,
        chat_id=2005,
        username="eric",
        first_name="Eric",
        last_name="Demo",
        language_code="fa",
    )
    record = service.create_user_recipe(
        1005,
        {
            "name": "My Drill",
            "template_key": "ladder",
            "prompt_field": "persian",
            "pause_between_ms": 1100,
            "word_pause_ms": 240,
        },
    )
    assert record.recipe_key == "my_drill"
    described = service.describe_user_recipe(1005, "my_drill")
    assert described["payload"]["pause_between_ms"] == 1100
    updated = service.update_user_recipe(1005, "my_drill", {"include_slow_pass": False, "pause_between_ms": 900})
    assert updated.recipe_data()["pause_between_ms"] == 900

    resolved = service.resolve_recipe_for_user(1005, "my_drill")
    assert resolved["recipe_name"] == "my_drill_fr_user"
    assert "My Drill" in resolved["summary"]
    assert any(recipe.recipe_name == "my_drill" for recipe in service.available_recipes(1005))
