from __future__ import annotations

from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from echolingua.core.config import load_config
from echolingua.core.errors import EchoLinguaError
from echolingua.telegram_bot.service import TelegramBotService

STATE_WAITING_FOR_CSV = 1

SENTENCES_PAGE_SIZE = 8


def build_application() -> Application:
    config = load_config()
    if not config.telegram_bot_token:
        raise RuntimeError("ECHOLINGUA_TELEGRAM_BOT_TOKEN is not configured.")
    request = HTTPXRequest(httpx_kwargs={"trust_env": False})
    application = (
        Application.builder()
        .token(config.telegram_bot_token)
        .request(request)
        .get_updates_request(request)
        .build()
    )
    service = TelegramBotService(config)
    application.bot_data["service"] = service

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("settings", settings_menu))
    application.add_handler(CommandHandler("library", library_menu))
    application.add_handler(CommandHandler("export_csv", export_csv))
    application.add_handler(CommandHandler("send_all", send_all_sentences))

    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("import_csv", import_csv_prompt)],
            states={
                STATE_WAITING_FOR_CSV: [MessageHandler(filters.Document.ALL, import_csv_document)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )
    application.add_handler(CommandHandler("add_sentence", add_sentence_prompt))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    application.add_handler(CallbackQueryHandler(handle_callback))
    return application


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service = _service(context)
    user = update.effective_user
    chat = update.effective_chat
    service.ensure_user(
        telegram_user_id=user.id,
        chat_id=chat.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        language_code=user.language_code or "",
    )
    await _send_or_edit(
        update,
        _welcome_text(service, user.id),
        reply_markup=_main_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_or_edit(update, _help_text(), reply_markup=_main_menu_keyboard())


async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service = _service(context)
    user_id = _effective_user_id(update)
    await _send_or_edit(update, _settings_text(service, user_id), reply_markup=_settings_keyboard(service, user_id), parse_mode=ParseMode.MARKDOWN)


async def library_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_library(update, context, page=0)


async def import_csv_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(
        "📥 فایل CSV را همینجا بفرست.\n\nراهنما:\n- ستون‌های استاندارد EchoLingua را نگه دار\n- با ایمپورت جدید، کتابخانه فعلی همین کاربر با CSV جدید جایگزین می‌شود\n- برای لغو: /cancel",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_WAITING_FOR_CSV


async def import_csv_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    service = _service(context)
    document = update.effective_message.document
    if document is None:
        await update.effective_message.reply_text("❌ فایل دریافت نشد. دوباره تلاش کن.")
        return STATE_WAITING_FOR_CSV
    temp_path = service.config.telegram_import_dir / document.file_name
    telegram_file = await document.get_file()
    await telegram_file.download_to_drive(custom_path=str(temp_path))
    try:
        result = service.import_csv_for_user(update.effective_user.id, temp_path, document.file_name)
    except EchoLinguaError as exc:
        await update.effective_message.reply_text(f"❌ ایمپورت ناموفق بود:\n{exc}")
        return ConversationHandler.END
    report = result["report"]
    summary = service.sentence_summary(update.effective_user.id)
    await update.effective_message.reply_text(
        "✅ ایمپورت انجام شد\n\n"
        f"Rows: {report.total_rows}\n"
        f"Enabled: {report.enabled_rows}\n"
        f"Imported: {len(result['imported_sentence_ids'])}\n"
        f"Levels: {', '.join(f'{k}:{v}' for k, v in summary['levels'].items()) or '-'}\n"
        f"Categories: {', '.join(f'{k}:{v}' for k, v in summary['categories'].items()) or '-'}",
        reply_markup=_post_import_keyboard(),
    )
    return ConversationHandler.END


async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service = _service(context)
    export_path = service.export_user_csv(_effective_user_id(update))
    await _message(update).reply_document(document=str(export_path), caption="📤 خروجی CSV شما آماده است.")


async def send_all_sentences(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service = _service(context)
    user_id = _effective_user_id(update)
    sentences = service.list_user_sentences(user_id)
    if not sentences:
        await _send_or_edit(update, "📭 هنوز جمله‌ای برای شما ثبت نشده. اول CSV وارد کن.", reply_markup=_main_menu_keyboard())
        return
    await _send_or_edit(update, f"🎧 شروع ارسال {len(sentences)} ویس. این کار ممکن است کمی زمان ببرد.", reply_markup=_main_menu_keyboard())
    for index, sentence in enumerate(sentences, start=1):
        await context.bot.send_chat_action(chat_id=_chat_id(update), action=ChatAction.UPLOAD_VOICE)
        payload = service.generate_sentence_audio_for_user(user_id, sentence.id)
        caption = f"{payload['caption']}\n\n🧩 {index}/{len(sentences)} | Recipe: {payload['recipe_name']}"
        with payload["audio_path"].open("rb") as handle:
            await context.bot.send_audio(
                chat_id=_chat_id(update),
                audio=handle,
                caption=caption,
            )
    await context.bot.send_message(chat_id=_chat_id(update), text="✅ ارسال همه فایل‌ها تمام شد.", reply_markup=_main_menu_keyboard())


async def add_sentence_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["awaiting_input"] = "add_sentence"
    await _message(update).reply_text(
        "➕ شناسه جمله را بفرست.\nمثال: `15`\nبرای لغو: /cancel",
        parse_mode=ParseMode.MARKDOWN,
    )


async def add_sentence_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service = _service(context)
    sentence_id = (update.effective_message.text or "").strip()
    try:
        service.add_sentence_to_user(update.effective_user.id, sentence_id)
    except EchoLinguaError as exc:
        await update.effective_message.reply_text(f"❌ افزودن جمله ناموفق بود:\n{exc}")
        return
    context.user_data.pop("awaiting_input", None)
    await update.effective_message.reply_text(f"✅ جمله `{sentence_id}` به کتابخانه‌ات اضافه شد.", parse_mode=ParseMode.MARKDOWN)


async def custom_recipe_set_pause_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_input"] = "custom_pause"
    await query.message.reply_text("⏱ مکث بین بخش‌ها را به میلی‌ثانیه بفرست. مثال: `3000`", parse_mode=ParseMode.MARKDOWN)


async def custom_recipe_set_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service = _service(context)
    user_id = update.effective_user.id
    value = await _parse_positive_int(update, "pause_between_ms")
    if value is None:
        return
    service.create_or_update_custom_recipe(user_id, {"pause_between_ms": value})
    context.user_data.pop("awaiting_input", None)
    await update.effective_message.reply_text("✅ مکث بین بخش‌ها ذخیره شد.")
    await update.effective_message.reply_text(
        _custom_recipe_text(service, user_id),
        reply_markup=_custom_recipe_keyboard(service, user_id),
        parse_mode=ParseMode.MARKDOWN,
    )


async def custom_recipe_set_word_pause_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_input"] = "custom_word_pause"
    await query.message.reply_text("🪶 مکث بین کلمات فرانسوی را به میلی‌ثانیه بفرست. مثال: `900`", parse_mode=ParseMode.MARKDOWN)


async def custom_recipe_set_word_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service = _service(context)
    user_id = update.effective_user.id
    value = await _parse_positive_int(update, "word_pause_ms")
    if value is None:
        return
    service.create_or_update_custom_recipe(user_id, {"word_pause_ms": value})
    context.user_data.pop("awaiting_input", None)
    await update.effective_message.reply_text("✅ مکث بین کلمات ذخیره شد.")
    await update.effective_message.reply_text(
        _custom_recipe_text(service, user_id),
        reply_markup=_custom_recipe_keyboard(service, user_id),
        parse_mode=ParseMode.MARKDOWN,
    )


async def settings_set_page_size_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_input"] = "page_size"
    await query.message.reply_text("📚 تعداد آیتم هر صفحه را بفرست. بازه مناسب: `4` تا `20`", parse_mode=ParseMode.MARKDOWN)


async def settings_set_page_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service = _service(context)
    user_id = update.effective_user.id
    value = await _parse_positive_int(update, "page_size")
    if value is None:
        return
    settings = service.get_settings(user_id)
    extra = settings.extra_config()
    extra["page_size"] = max(4, min(20, value))
    service.update_settings(user_id, extra_config=extra)
    context.user_data.pop("awaiting_input", None)
    await update.effective_message.reply_text("✅ تعداد آیتم هر صفحه ذخیره شد.")
    await update.effective_message.reply_text(
        _settings_text(service, user_id),
        reply_markup=_settings_keyboard(service, user_id),
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    awaiting = context.user_data.get("awaiting_input")
    if awaiting == "add_sentence":
        await add_sentence_message(update, context)
        return
    if awaiting == "custom_pause":
        await custom_recipe_set_pause(update, context)
        return
    if awaiting == "custom_word_pause":
        await custom_recipe_set_word_pause(update, context)
        return
    if awaiting == "page_size":
        await settings_set_page_size(update, context)
        return


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service = _service(context)
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    user_id = query.from_user.id

    if data == "menu:import_csv":
        await query.message.reply_text("📥 فایل CSV را بفرست یا /import_csv را بزن.")
        return
    if data == "menu:library":
        await _show_library(update, context, page=0)
        return
    if data == "menu:send_all":
        await send_all_sentences(update, context)
        return
    if data == "menu:settings":
        await settings_menu(update, context)
        return
    if data == "menu:export_csv":
        await export_csv(update, context)
        return
    if data == "menu:help":
        await help_command(update, context)
        return
    if data == "library:refresh":
        await _show_library(update, context, page=0)
        return
    if data.startswith("library:page:"):
        await _show_library(update, context, page=int(data.split(":")[2]))
        return
    if data.startswith("library:view:"):
        sentence_id = data.split(":", 2)[2]
        await _show_sentence_detail(update, context, sentence_id)
        return
    if data.startswith("library:send:"):
        sentence_id = data.split(":", 2)[2]
        await _send_single_sentence(update, context, sentence_id)
        return
    if data.startswith("library:remove:"):
        sentence_id = data.split(":", 2)[2]
        service.remove_sentence_from_user(user_id, sentence_id)
        await _show_library(update, context, page=0, flash=f"🗑 جمله {sentence_id} حذف شد.")
        return
    if data == "library:add":
        await query.message.reply_text("➕ برای افزودن دستی، دستور /add_sentence را بزن و شناسه جمله را بفرست.")
        return
    if data == "settings:recipe":
        await _send_or_edit(update, _recipe_selection_text(service, user_id), reply_markup=_recipe_selection_keyboard(service, user_id), parse_mode=ParseMode.MARKDOWN)
        return
    if data == "settings:provider":
        await _send_or_edit(update, _provider_selection_text(service, user_id), reply_markup=_provider_selection_keyboard(service, user_id), parse_mode=ParseMode.MARKDOWN)
        return
    if data == "settings:format":
        await _send_or_edit(update, _output_format_text(service, user_id), reply_markup=_output_format_keyboard(service, user_id), parse_mode=ParseMode.MARKDOWN)
        return
    if data == "settings:custom_recipe":
        await _send_or_edit(update, _custom_recipe_text(service, user_id), reply_markup=_custom_recipe_keyboard(service, user_id), parse_mode=ParseMode.MARKDOWN)
        return
    if data.startswith("settings:recipe:set:"):
        recipe = data.split(":", 3)[3]
        service.update_settings(user_id, selected_recipe=recipe)
        await settings_menu(update, context)
        return
    if data.startswith("settings:provider:set:"):
        provider = data.split(":", 3)[3]
        service.update_settings(user_id, selected_provider=provider)
        await settings_menu(update, context)
        return
    if data.startswith("settings:format:set:"):
        output_format = data.split(":", 3)[3]
        service.update_settings(user_id, output_format=output_format)
        await settings_menu(update, context)
        return
    if data.startswith("recipecfg:prompt:"):
        prompt_field = data.split(":", 2)[2]
        service.create_or_update_custom_recipe(user_id, {"prompt_field": prompt_field})
        await _send_or_edit(update, _custom_recipe_text(service, user_id), reply_markup=_custom_recipe_keyboard(service, user_id), parse_mode=ParseMode.MARKDOWN)
        return
    if data.startswith("recipecfg:voice:"):
        _, _, voice_key, voice_value = data.split(":", 3)
        service.create_or_update_custom_recipe(user_id, {voice_key: voice_value})
        await _send_or_edit(update, _custom_recipe_text(service, user_id), reply_markup=_custom_recipe_keyboard(service, user_id), parse_mode=ParseMode.MARKDOWN)
        return
    if data.startswith("recipecfg:french_voice_all:"):
        voice_value = data.split(":", 2)[2]
        service.create_or_update_custom_recipe(
            user_id,
            {
                "normal_voice": voice_value,
                "word_by_word_voice": voice_value,
                "slow_voice": voice_value,
                "final_voice": voice_value,
            },
        )
        await _send_or_edit(update, _custom_recipe_text(service, user_id), reply_markup=_custom_recipe_keyboard(service, user_id), parse_mode=ParseMode.MARKDOWN)
        return
    if data.startswith("recipecfg:rate:"):
        _, _, rate_key, rate_value = data.split(":", 3)
        service.create_or_update_custom_recipe(user_id, {rate_key: rate_value})
        await _send_or_edit(update, _custom_recipe_text(service, user_id), reply_markup=_custom_recipe_keyboard(service, user_id), parse_mode=ParseMode.MARKDOWN)
        return
    if data == "recipecfg:use_custom":
        service.update_settings(user_id, selected_recipe="telegram_custom_ladder")
        await settings_menu(update, context)
        return
    if data == "recipecfg:back":
        await settings_menu(update, context)
        return
    if data == "settings:back":
        await _send_or_edit(update, _welcome_text(service, user_id), reply_markup=_main_menu_keyboard())
        return


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("awaiting_input", None)
    await update.effective_message.reply_text("لغو شد.")
    return ConversationHandler.END


def _service(context: ContextTypes.DEFAULT_TYPE) -> TelegramBotService:
    return context.application.bot_data["service"]


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📥 ایمپورت CSV", callback_data="menu:import_csv")],
            [InlineKeyboardButton("📚 کتابخانه من", callback_data="menu:library")],
            [InlineKeyboardButton("🎧 ارسال همه ویس‌ها", callback_data="menu:send_all")],
            [InlineKeyboardButton("⚙️ تنظیمات", callback_data="menu:settings")],
            [InlineKeyboardButton("📤 خروجی CSV", callback_data="menu:export_csv")],
            [InlineKeyboardButton("❓ راهنما", callback_data="menu:help")],
        ]
    )


def _post_import_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📚 دیدن کتابخانه", callback_data="menu:library")],
            [InlineKeyboardButton("🎧 شروع ارسال ویس‌ها", callback_data="menu:send_all")],
            [InlineKeyboardButton("⚙️ تنظیمات", callback_data="menu:settings")],
        ]
    )


def _settings_keyboard(service: TelegramBotService, user_id: int) -> InlineKeyboardMarkup:
    settings = service.get_settings(user_id)
    custom_badge = "🧪" if settings.selected_recipe == "telegram_custom_ladder" else "🧩"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎼 انتخاب Recipe", callback_data="settings:recipe")],
            [InlineKeyboardButton("🗣 انتخاب Provider", callback_data="settings:provider")],
            [InlineKeyboardButton("💾 فرمت خروجی", callback_data="settings:format")],
            [InlineKeyboardButton(f"{custom_badge} Recipe سفارشی", callback_data="settings:custom_recipe")],
            [InlineKeyboardButton("📄 تعداد آیتم هر صفحه", callback_data="settings:set_page_size")],
            [InlineKeyboardButton("🏠 بازگشت به منو", callback_data="settings:back")],
        ]
    )


def _recipe_selection_keyboard(service: TelegramBotService, user_id: int) -> InlineKeyboardMarkup:
    settings = service.get_settings(user_id)
    rows = []
    for recipe in service.available_recipes():
        badge = "✅" if recipe == settings.selected_recipe else "▫️"
        rows.append([InlineKeyboardButton(f"{badge} {recipe}", callback_data=f"settings:recipe:set:{recipe}")])
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)


def _provider_selection_keyboard(service: TelegramBotService, user_id: int) -> InlineKeyboardMarkup:
    settings = service.get_settings(user_id)
    rows = []
    for provider in service.available_tts_providers():
        badge = "✅" if provider["name"] == settings.selected_provider else "▫️"
        availability = "online" if provider["dependency_available"] else "missing"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{badge} {provider['name']} | {provider['provider_type']} | {availability}",
                    callback_data=f"settings:provider:set:{provider['name']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)


def _output_format_keyboard(service: TelegramBotService, user_id: int) -> InlineKeyboardMarkup:
    settings = service.get_settings(user_id)
    rows = [
        [
            InlineKeyboardButton(
                f"{'✅' if fmt == settings.output_format else '▫️'} {fmt.upper()}",
                callback_data=f"settings:format:set:{fmt}",
            )
        ]
        for fmt in service.available_output_formats()
    ]
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)


def _custom_recipe_keyboard(service: TelegramBotService, user_id: int) -> InlineKeyboardMarkup:
    custom = service.describe_custom_recipe(user_id)
    prompt_rows = [
        InlineKeyboardButton(
            f"{'✅' if preset['value'] == custom['prompt_field'] else '▫️'} {preset['label']}",
            callback_data=f"recipecfg:prompt:{preset['value']}",
        )
        for preset in service.recipe_prompt_presets()
    ]
    rows = [
        prompt_rows,
        [
            InlineKeyboardButton("🇮🇷 Prompt زن", callback_data="recipecfg:voice:prompt_voice:fa-IR-DilaraNeural"),
            InlineKeyboardButton("🇮🇷 Prompt مرد", callback_data="recipecfg:voice:prompt_voice:fa-IR-FaridNeural"),
        ],
        [InlineKeyboardButton("⏱ تنظیم مکث بین بخش‌ها", callback_data="recipecfg:set_pause")],
        [InlineKeyboardButton("🪶 تنظیم مکث بین کلمات", callback_data="recipecfg:set_word_pause")],
        [
            InlineKeyboardButton("👨 صدای مرد فرانسوی", callback_data="recipecfg:french_voice_all:fr-FR-HenriNeural"),
            InlineKeyboardButton("👩 صدای زن فرانسوی", callback_data="recipecfg:french_voice_all:fr-FR-DeniseNeural"),
        ],
        [
            InlineKeyboardButton("🐢 سرعت کندتر", callback_data="recipecfg:rate:slow_rate:-20%"),
            InlineKeyboardButton("🚀 سرعت عادی", callback_data="recipecfg:rate:slow_rate:+0%"),
        ],
        [InlineKeyboardButton("✅ استفاده از این Recipe", callback_data="recipecfg:use_custom")],
        [InlineKeyboardButton("⬅️ بازگشت", callback_data="recipecfg:back")],
    ]
    return InlineKeyboardMarkup(rows)


async def _show_library(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    page: int,
    flash: str | None = None,
) -> None:
    service = _service(context)
    user_id = _effective_user_id(update)
    page_payload = service.paginated_user_sentences(user_id, page, SENTENCES_PAGE_SIZE)
    text = _library_text(service, user_id, page_payload, flash=flash)
    await _send_or_edit(update, text, reply_markup=_library_keyboard(page_payload), parse_mode=ParseMode.MARKDOWN)


def _library_keyboard(page_payload: dict[str, object]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    items = page_payload["items"]
    for sentence in items:
        rows.append([InlineKeyboardButton(f"🎧 {sentence.id}. {sentence.french[:45]}", callback_data=f"library:view:{sentence.id}")])
    nav_row: list[InlineKeyboardButton] = []
    page = int(page_payload["page"])
    total_pages = int(page_payload["total_pages"])
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"library:page:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"library:page:{page + 1}"))
    if nav_row:
        rows.append(nav_row)
    rows.extend(
        [
            [InlineKeyboardButton("➕ افزودن با شناسه", callback_data="library:add")],
            [InlineKeyboardButton("🔄 تازه‌سازی", callback_data="library:refresh")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="settings:back")],
        ]
    )
    return InlineKeyboardMarkup(rows)


async def _show_sentence_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, sentence_id: str) -> None:
    service = _service(context)
    sentence = next((item for item in service.list_user_sentences(_effective_user_id(update)) if item.id == sentence_id), None)
    if sentence is None:
        await _send_or_edit(update, "❌ این جمله در کتابخانه شما پیدا نشد.", reply_markup=_main_menu_keyboard())
        return
    text = (
        f"*Sentence {sentence.id}*\n\n"
        f"🇮🇷 فارسی: {sentence.persian}\n"
        f"🇬🇧 English: {sentence.english or '-'}\n"
        f"🇫🇷 Français: {sentence.french}\n\n"
        f"🏷 Level: `{sentence.level}`\n"
        f"📂 Category: `{sentence.category}`\n"
        f"⭐ Priority: `{sentence.priority}`"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎧 تولید و ارسال همین جمله", callback_data=f"library:send:{sentence.id}")],
            [InlineKeyboardButton("🗑 حذف از کتابخانه", callback_data=f"library:remove:{sentence.id}")],
            [InlineKeyboardButton("⬅️ بازگشت به کتابخانه", callback_data="menu:library")],
        ]
    )
    await _send_or_edit(update, text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)


async def _send_single_sentence(update: Update, context: ContextTypes.DEFAULT_TYPE, sentence_id: str) -> None:
    service = _service(context)
    await _send_or_edit(update, f"🎙 در حال ساخت فایل صوتی جمله `{sentence_id}` ...", parse_mode=ParseMode.MARKDOWN)
    await context.bot.send_chat_action(chat_id=_chat_id(update), action=ChatAction.UPLOAD_VOICE)
    try:
        payload = service.generate_sentence_audio_for_user(_effective_user_id(update), sentence_id)
    except EchoLinguaError as exc:
        await _send_or_edit(update, f"❌ تولید صدا ناموفق بود:\n{exc}", reply_markup=_main_menu_keyboard())
        return
    with payload["audio_path"].open("rb") as handle:
        await context.bot.send_audio(
            chat_id=_chat_id(update),
            audio=handle,
            caption=f"{payload['caption']}\n\n🎼 {payload['recipe_name']}",
        )
    await context.bot.send_message(chat_id=_chat_id(update), text="✅ فایل ارسال شد.", reply_markup=_main_menu_keyboard())


async def _send_or_edit(
    update: Update,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> None:
    query = update.callback_query
    if query is not None and query.message is not None:
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    await _message(update).reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)


def _message(update: Update):
    return update.effective_message


def _chat_id(update: Update) -> int:
    return update.effective_chat.id


def _effective_user_id(update: Update) -> int:
    return update.effective_user.id


def _welcome_text(service: TelegramBotService, user_id: int) -> str:
    settings = service.get_settings(user_id)
    summary = service.sentence_summary(user_id)
    latest_import = service.latest_import_summary(user_id)
    import_line = latest_import["file_name"] if latest_import else "هنوز CSV وارد نشده"
    return (
        "🌿 *به EchoLingua Bot خوش آمدی*\n\n"
        "اینجا می‌تونی CSV جمله‌هایت را وارد کنی، کتابخانه شخصی بسازی، صداها را با همان pipeline اصلی تولید کنی و تک‌تک فایل‌ها را همینجا بگیری.\n\n"
        f"📚 تعداد جمله‌های فعلی: `{summary['count']}`\n"
        f"🎼 Recipe فعال: `{settings.selected_recipe}`\n"
        f"🗣 Provider فعال: `{settings.selected_provider}`\n"
        f"💾 فرمت خروجی: `{settings.output_format}`\n"
        f"📥 آخرین ایمپورت: `{import_line}`"
    )


def _help_text() -> str:
    return (
        "🧭 *راهنمای سریع*\n\n"
        "1. اول CSV را ایمپورت کن.\n"
        "2. بعد از بخش کتابخانه، جمله‌ها را مرور کن.\n"
        "3. برای هر جمله می‌توانی همان‌جا فایل صوتی بسازی.\n"
        "4. از تنظیمات می‌توانی Recipe، Provider و فرمت را عوض کنی.\n"
        "5. اگر خواستی همه فایل‌ها پشت‌سرهم بیایند، `ارسال همه ویس‌ها` را بزن.\n\n"
        "فرمان‌های مهم:\n"
        "/start\n"
        "/import_csv\n"
        "/library\n"
        "/settings\n"
        "/send_all\n"
        "/export_csv"
    )


def _settings_text(service: TelegramBotService, user_id: int) -> str:
    settings = service.get_settings(user_id)
    custom = service.describe_custom_recipe(user_id)
    provider_rows = service.available_tts_providers()
    current_provider = next((row for row in provider_rows if row["name"] == settings.selected_provider), None)
    provider_status = "dependency ok" if current_provider and current_provider["dependency_available"] else "dependency missing"
    page_size = settings.extra_config().get("page_size", SENTENCES_PAGE_SIZE)
    return (
        "⚙️ *تنظیمات فعلی*\n\n"
        f"🎼 Recipe: `{settings.selected_recipe}`\n"
        f"🗣 Provider: `{settings.selected_provider}` ({provider_status})\n"
        f"💾 Output: `{settings.output_format}`\n"
        f"📄 Page size: `{page_size}`\n"
        f"🧪 Custom recipe: `{custom['summary']}`"
    )


def _recipe_selection_text(service: TelegramBotService, user_id: int) -> str:
    settings = service.get_settings(user_id)
    return (
        "🎼 *انتخاب Recipe*\n\n"
        f"فعلی: `{settings.selected_recipe}`\n"
        "اگر بخواهی از داخل بات ریسیپی نزدیک به نیازت بسازی، `telegram_custom_ladder` را انتخاب کن یا از بخش Recipe سفارشی تنظیمش کن."
    )


def _provider_selection_text(service: TelegramBotService, user_id: int) -> str:
    settings = service.get_settings(user_id)
    return (
        "🗣 *انتخاب Provider*\n\n"
        f"فعلی: `{settings.selected_provider}`\n"
        "برای تولید فرانسوی واقعی، `edge` مناسب‌ترین گزینه فعلی است."
    )


def _output_format_text(service: TelegramBotService, user_id: int) -> str:
    settings = service.get_settings(user_id)
    return (
        "💾 *فرمت خروجی*\n\n"
        f"فعلی: `{settings.output_format}`\n"
        "WAV پایدارترین گزینه است. MP3 به ابزار محلی export وابسته است."
    )


def _custom_recipe_text(service: TelegramBotService, user_id: int) -> str:
    custom = service.describe_custom_recipe(user_id)
    return (
        "🧪 *Recipe سفارشی تلگرام*\n\n"
        f"Prompt: `{custom['prompt_field']}`\n"
        f"Pause between parts: `{custom['pause_between_ms']}ms`\n"
        f"Word pause: `{custom['word_pause_ms']}ms`\n"
        f"Prompt voice: `{custom['prompt_voice']}`\n"
        f"French voice: `{custom['normal_voice']}`\n"
        f"Slow rate: `{custom['slow_rate']}`\n\n"
        f"{custom['summary']}"
    )


def _library_text(service: TelegramBotService, user_id: int, page_payload: dict[str, object], flash: str | None = None) -> str:
    summary = service.sentence_summary(user_id)
    latest_import = service.latest_import_summary(user_id)
    import_line = latest_import["file_name"] if latest_import else "-"
    page = int(page_payload["page"]) + 1
    total_pages = int(page_payload["total_pages"])
    items = page_payload["items"]
    lines = [
        "📚 *کتابخانه شما*",
        "",
        f"تعداد کل جمله‌ها: `{summary['count']}`",
        f"صفحه: `{page}/{total_pages}`",
        f"آخرین CSV: `{import_line}`",
        "",
    ]
    if flash:
        lines.append(f"{flash}\n")
    if not items:
        lines.append("هنوز کتابخانه‌ات خالی است. اول یک CSV وارد کن.")
    else:
        for sentence in items:
            lines.append(f"`{sentence.id}`  {sentence.french}")
    return "\n".join(lines)


async def _parse_positive_int(update: Update, label: str) -> int | None:
    raw = (update.effective_message.text or "").strip()
    try:
        value = int(raw)
    except ValueError:
        await update.effective_message.reply_text(f"❌ مقدار {label} باید عدد صحیح باشد.")
        return None
    if value < 0:
        await update.effective_message.reply_text(f"❌ مقدار {label} باید صفر یا بیشتر باشد.")
        return None
    return value


def main() -> None:
    application = build_application()
    application.run_polling()


if __name__ == "__main__":
    main()
