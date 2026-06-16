from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.error import BadRequest
from telegram.constants import ChatAction, ParseMode
from telegram.helpers import escape_markdown
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
from echolingua.telegram_bot.service import TARGET_LANGUAGES, TelegramBotService

LOGGER = logging.getLogger(__name__)

STATE_WAITING_FOR_CSV = 1

SENTENCES_PAGE_SIZE = 8
MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📚 کتابخانه"), KeyboardButton("🎧 ارسال همه")],
        [KeyboardButton("➕ افزودن جمله"), KeyboardButton("⚙️ تنظیمات")],
        [KeyboardButton("🎼 مدیریت ریسیپی‌ها")],
        [KeyboardButton("📥 ایمپورت CSV"), KeyboardButton("📤 خروجی CSV")],
        [KeyboardButton("❓ راهنما")],
    ],
    resize_keyboard=True,
)


def build_application() -> Application:
    config = load_config()
    if not config.telegram_bot_token:
        raise RuntimeError("ECHOLINGUA_TELEGRAM_BOT_TOKEN is not configured.")
    request_kwargs: dict[str, object] = {"httpx_kwargs": {"trust_env": False}}
    if config.telegram_bot_proxy_url:
        request_kwargs["proxy"] = config.telegram_bot_proxy_url
    request = HTTPXRequest(**request_kwargs)
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_error_handler(handle_error)
    return application


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    LOGGER.exception("Telegram bot update failed", exc_info=context.error)
    effective_update = update if isinstance(update, Update) else None
    message = effective_update.effective_message if effective_update else None
    if message is not None:
        try:
            await message.reply_text("❌ یک خطای داخلی رخ داد. دوباره تلاش کن یا /menu را بزن.", reply_markup=MENU_KEYBOARD)
        except Exception:
            LOGGER.exception("Failed to send error message to Telegram")


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
    context.user_data.clear()
    await _send_or_edit(
        update,
        _welcome_text(service, user.id),
        reply_markup=_main_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )
    if update.callback_query is None:
        await update.effective_message.reply_text("منوی اصلی آماده است.", reply_markup=MENU_KEYBOARD)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_or_edit(update, _help_text(), reply_markup=_main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
    if update.callback_query is None:
        await update.effective_message.reply_text("از منوی زیر هم می‌توانی سریع کار کنی.", reply_markup=MENU_KEYBOARD)


async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service = _service(context)
    user_id = _effective_user_id(update)
    await _send_or_edit(
        update,
        _settings_text(service, user_id),
        reply_markup=_settings_keyboard(service, user_id),
        parse_mode=ParseMode.MARKDOWN,
    )


async def library_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_library(update, context, page=0)


def _reset_recipe_wizard(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in [
        "awaiting_input",
        "draft_recipe",
        "editing_user_recipe_key",
        "editing_recipe_name",
        "new_sentence_target_text",
        "editing_sentence_id",
    ]:
        context.user_data.pop(key, None)


async def recipes_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service = _service(context)
    user_id = _effective_user_id(update)
    await _send_or_edit(
        update,
        _recipes_menu_text(service, user_id),
        reply_markup=_recipes_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def import_csv_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(
        "📥 فایل CSV را همینجا بفرست.\n\nبا ایمپورت جدید، کتابخانه فعلی همان کاربر با داده‌های enabled جدید جایگزین می‌شود.\nبرای لغو: /cancel",
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
        await update.effective_message.reply_text(f"❌ ایمپورت ناموفق بود:\n{exc}", reply_markup=MENU_KEYBOARD)
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
        reply_markup=MENU_KEYBOARD,
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
    await _send_or_edit(update, f"🎧 شروع ارسال {len(sentences)} ویس. کمی زمان می‌برد.", reply_markup=_main_menu_keyboard())
    for index, sentence in enumerate(sentences, start=1):
        await context.bot.send_chat_action(chat_id=_chat_id(update), action=ChatAction.UPLOAD_VOICE)
        payload = service.generate_sentence_audio_for_user(user_id, sentence.id)
        with payload["audio_path"].open("rb") as handle:
            await context.bot.send_audio(
                chat_id=_chat_id(update),
                audio=handle,
                caption=f"{payload['caption']}\n\n🧩 {index}/{len(sentences)} | Recipe: {payload['recipe_name']}",
            )
    await context.bot.send_message(chat_id=_chat_id(update), text="✅ ارسال همه فایل‌ها تمام شد.", reply_markup=MENU_KEYBOARD)


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    if text == "📚 کتابخانه":
        await library_menu(update, context)
        return
    if text == "🎧 ارسال همه":
        await send_all_sentences(update, context)
        return
    if text == "⚙️ تنظیمات":
        await settings_menu(update, context)
        return
    if text == "🎼 مدیریت ریسیپی‌ها":
        await recipes_menu(update, context)
        return
    if text == "📥 ایمپورت CSV":
        await import_csv_prompt(update, context)
        return
    if text == "📤 خروجی CSV":
        await export_csv(update, context)
        return
    if text == "❓ راهنما":
        await help_command(update, context)
        return
    if text == "➕ افزودن جمله":
        context.user_data["awaiting_input"] = "add_target_text"
        await update.effective_message.reply_text(
            "🌍 زبان مقصد از تنظیمات تعیین می‌شود.\nحالا متن جمله را در همان زبان مقصد بفرست.\nبعدش ترجمه فارسی را می‌گیرم.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    awaiting = context.user_data.get("awaiting_input")
    service = _service(context)
    user_id = update.effective_user.id

    if awaiting == "custom_pause":
        value = await _parse_positive_int(update, "pause_between_ms")
        if value is None:
            return
        service.create_or_update_custom_recipe(user_id, {"pause_between_ms": value})
        context.user_data.pop("awaiting_input", None)
        await update.effective_message.reply_text("✅ مکث بین بخش‌ها ذخیره شد.", reply_markup=MENU_KEYBOARD)
        return
    if awaiting == "custom_word_pause":
        value = await _parse_positive_int(update, "word_pause_ms")
        if value is None:
            return
        service.create_or_update_custom_recipe(user_id, {"word_pause_ms": value})
        context.user_data.pop("awaiting_input", None)
        await update.effective_message.reply_text("✅ مکث بین کلمات ذخیره شد.", reply_markup=MENU_KEYBOARD)
        return
    if awaiting == "page_size":
        value = await _parse_positive_int(update, "page_size")
        if value is None:
            return
        settings = service.get_settings(user_id)
        extra = settings.extra_config()
        extra["page_size"] = max(4, min(20, value))
        service.update_settings(user_id, extra_config=extra)
        context.user_data.pop("awaiting_input", None)
        await update.effective_message.reply_text("✅ تعداد آیتم هر صفحه ذخیره شد.", reply_markup=MENU_KEYBOARD)
        return
    if awaiting == "recipe_silence_scale":
        try:
            value = float(text)
        except ValueError:
            await update.effective_message.reply_text("❌ مثلا `0.6` یا `0.4` بفرست.", parse_mode=ParseMode.MARKDOWN)
            return
        recipe_name = str(context.user_data.get("editing_recipe_name", "shadowing_basic"))
        service.create_or_update_recipe_override(user_id, recipe_name, {"silence_scale": value})
        context.user_data.pop("awaiting_input", None)
        await update.effective_message.reply_text("✅ فاصله‌های recipe کمتر/بیشتر شد.", reply_markup=MENU_KEYBOARD)
        return
    if awaiting == "add_target_text":
        context.user_data["new_sentence_target_text"] = text
        context.user_data["awaiting_input"] = "add_translation"
        await update.effective_message.reply_text("ترجمه فارسی را بفرست.")
        return
    if awaiting == "add_translation":
        target_text = str(context.user_data.get("new_sentence_target_text", "")).strip()
        target_language = service.get_target_language(user_id)
        sentence = service.add_sentence_from_target_text(
            user_id,
            target_language=target_language,
            target_text=target_text,
            translation_text=text,
        )
        context.user_data.pop("new_sentence_target_text", None)
        context.user_data.pop("awaiting_input", None)
        await update.effective_message.reply_text(
            f"✅ جمله `{escape_markdown(sentence.id)}` ذخیره شد و به کتابخانه اضافه شد.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MENU_KEYBOARD,
        )
        return
    if awaiting == "edit_sentence_target":
        sentence_id = str(context.user_data.get("editing_sentence_id"))
        target_language = service.get_target_language(user_id)
        field = service.target_language_field(target_language)
        service.update_sentence_for_user(user_id, sentence_id, **{field: text})
        context.user_data["awaiting_input"] = "edit_sentence_translation"
        await update.effective_message.reply_text("حالا ترجمه فارسی را بفرست. اگر نمی‌خواهی عوض شود، همان قبلی را دوباره بفرست.")
        return
    if awaiting == "edit_sentence_translation":
        sentence_id = str(context.user_data.get("editing_sentence_id"))
        service.update_sentence_for_user(user_id, sentence_id, persian=text)
        context.user_data.pop("editing_sentence_id", None)
        context.user_data.pop("awaiting_input", None)
        await update.effective_message.reply_text("✅ جمله ویرایش شد.", reply_markup=MENU_KEYBOARD)
        return
    if awaiting == "recipe_name":
        draft = dict(context.user_data.get("draft_recipe", {}))
        draft["name"] = text
        context.user_data["draft_recipe"] = draft
        context.user_data["awaiting_input"] = None
        await update.effective_message.reply_text(
            "✅ نام ذخیره شد. حالا از دکمه‌ها نوع prompt و بقیه تنظیمات را انتخاب کن.",
            reply_markup=MENU_KEYBOARD,
        )
        await recipes_menu(update, context)
        return
    if awaiting == "recipe_pause_ms":
        value = await _parse_positive_int(update, "pause_between_ms")
        if value is None:
            return
        draft = dict(context.user_data.get("draft_recipe", {}))
        draft["pause_between_ms"] = value
        context.user_data["draft_recipe"] = draft
        context.user_data.pop("awaiting_input", None)
        await _show_recipe_wizard(update, context)
        return
    if awaiting == "recipe_word_pause_ms":
        value = await _parse_positive_int(update, "word_pause_ms")
        if value is None:
            return
        draft = dict(context.user_data.get("draft_recipe", {}))
        draft["word_pause_ms"] = value
        context.user_data["draft_recipe"] = draft
        context.user_data.pop("awaiting_input", None)
        await _show_recipe_wizard(update, context)
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
    if data == "menu:recipes":
        await recipes_menu(update, context)
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
        await _show_sentence_detail(update, context, data.split(":", 2)[2])
        return
    if data.startswith("library:send:"):
        await _send_single_sentence(update, context, data.split(":", 2)[2])
        return
    if data.startswith("library:remove:"):
        sentence_id = data.split(":", 2)[2]
        service.remove_sentence_from_user(user_id, sentence_id)
        await _show_library(update, context, page=0, flash=f"🗑 جمله {sentence_id} حذف شد.")
        return
    if data.startswith("library:edit:"):
        sentence_id = data.split(":", 2)[2]
        context.user_data["editing_sentence_id"] = sentence_id
        context.user_data["awaiting_input"] = "edit_sentence_target"
        await query.message.reply_text("متن جدید جمله در زبان مقصد را بفرست.", reply_markup=ReplyKeyboardRemove())
        return
    if data == "library:add":
        context.user_data["awaiting_input"] = "add_target_text"
        await query.message.reply_text("متن جمله در زبان مقصد را بفرست.", reply_markup=ReplyKeyboardRemove())
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
    if data == "settings:target_language":
        await _send_or_edit(update, _target_language_text(service, user_id), reply_markup=_target_language_keyboard(service, user_id), parse_mode=ParseMode.MARKDOWN)
        return
    if data == "settings:custom_recipe":
        await _send_or_edit(update, _custom_recipe_text(service, user_id), reply_markup=_custom_recipe_keyboard(service, user_id), parse_mode=ParseMode.MARKDOWN)
        return
    if data.startswith("settings:target_language:set:"):
        service.set_target_language(user_id, data.split(":", 3)[3])
        await settings_menu(update, context)
        return
    if data.startswith("settings:recipe:set:"):
        service.update_settings(user_id, selected_recipe=data.split(":", 3)[3])
        await settings_menu(update, context)
        return
    if data == "recipes:new":
        context.user_data["draft_recipe"] = service.guided_recipe_defaults(user_id, "ladder")
        context.user_data["awaiting_input"] = "recipe_name"
        context.user_data.pop("editing_user_recipe_key", None)
        await query.message.reply_text("برای recipe جدید یک اسم بفرست.", reply_markup=ReplyKeyboardRemove())
        return
    if data == "recipes:list":
        await _send_or_edit(
            update,
            _recipe_selection_text(service, user_id),
            reply_markup=_recipe_selection_keyboard(service, user_id),
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if data.startswith("recipes:edit:"):
        recipe_key = data.split(":", 2)[2]
        described = service.describe_user_recipe(user_id, recipe_key)
        context.user_data["draft_recipe"] = dict(described["payload"])
        context.user_data["editing_user_recipe_key"] = recipe_key
        await _show_recipe_wizard(update, context)
        return
    if data.startswith("recipes:delete:"):
        recipe_key = data.split(":", 2)[2]
        service.delete_user_recipe(user_id, recipe_key)
        await recipes_menu(update, context)
        return
    if data.startswith("recipes:wizard:template:"):
        draft = dict(context.user_data.get("draft_recipe", {}))
        template_key = data.split(":", 3)[3]
        base = service.guided_recipe_defaults(user_id, template_key)
        base.update(draft)
        base["template_key"] = template_key
        context.user_data["draft_recipe"] = base
        await _show_recipe_wizard(update, context)
        return
    if data.startswith("recipes:wizard:prompt:"):
        draft = dict(context.user_data.get("draft_recipe", {}))
        draft["prompt_field"] = data.split(":", 3)[3]
        context.user_data["draft_recipe"] = draft
        await _show_recipe_wizard(update, context)
        return
    if data.startswith("recipes:wizard:target_voice:"):
        draft = dict(context.user_data.get("draft_recipe", {}))
        draft["target_voice"] = data.split(":", 3)[3]
        context.user_data["draft_recipe"] = draft
        await _show_recipe_wizard(update, context)
        return
    if data.startswith("recipes:wizard:toggle:"):
        draft = dict(context.user_data.get("draft_recipe", {}))
        flag = data.split(":", 3)[3]
        draft[flag] = not bool(draft.get(flag, False))
        context.user_data["draft_recipe"] = draft
        await _show_recipe_wizard(update, context)
        return
    if data == "recipes:wizard:set_pause":
        context.user_data["awaiting_input"] = "recipe_pause_ms"
        await query.message.reply_text("مکث بین بخش‌ها را به میلی‌ثانیه بفرست.")
        return
    if data == "recipes:wizard:set_word_pause":
        context.user_data["awaiting_input"] = "recipe_word_pause_ms"
        await query.message.reply_text("مکث بین کلمات را به میلی‌ثانیه بفرست.")
        return
    if data == "recipes:wizard:save":
        draft = dict(context.user_data.get("draft_recipe", {}))
        recipe_key = context.user_data.get("editing_user_recipe_key")
        if recipe_key:
            record = service.update_user_recipe(user_id, str(recipe_key), draft)
        else:
            record = service.create_user_recipe(user_id, draft)
        _reset_recipe_wizard(context)
        await _send_or_edit(
            update,
            f"✅ recipe `{escape_markdown(record.display_name)}` ذخیره شد و فعال شد.",
            reply_markup=_recipes_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if data == "recipes:wizard:cancel":
        _reset_recipe_wizard(context)
        await recipes_menu(update, context)
        return
    if data.startswith("settings:provider:set:"):
        service.update_settings(user_id, selected_provider=data.split(":", 3)[3])
        await settings_menu(update, context)
        return
    if data.startswith("settings:format:set:"):
        service.update_settings(user_id, output_format=data.split(":", 3)[3])
        await settings_menu(update, context)
        return
    if data.startswith("recipeedit:open:"):
        recipe_name = data.split(":", 2)[2]
        context.user_data["editing_recipe_name"] = recipe_name
        await _send_or_edit(update, _recipe_override_text(service, user_id, recipe_name), reply_markup=_recipe_override_keyboard(recipe_name), parse_mode=ParseMode.MARKDOWN)
        return
    if data == "recipeedit:set_silence":
        context.user_data["awaiting_input"] = "recipe_silence_scale"
        await query.message.reply_text("یک عدد بین `0.15` تا `1.0` بفرست. مثال: `0.5`", parse_mode=ParseMode.MARKDOWN)
        return
    if data.startswith("recipecfg:prompt:"):
        service.create_or_update_custom_recipe(user_id, {"prompt_field": data.split(":", 2)[2]})
        await _send_or_edit(update, _custom_recipe_text(service, user_id), reply_markup=_custom_recipe_keyboard(service, user_id), parse_mode=ParseMode.MARKDOWN)
        return
    if data.startswith("recipecfg:voice:"):
        _, _, voice_key, voice_value = data.split(":", 3)
        service.create_or_update_custom_recipe(user_id, {voice_key: voice_value})
        await _send_or_edit(update, _custom_recipe_text(service, user_id), reply_markup=_custom_recipe_keyboard(service, user_id), parse_mode=ParseMode.MARKDOWN)
        return
    if data.startswith("recipecfg:target_voice:"):
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
    if data == "recipecfg:set_pause":
        context.user_data["awaiting_input"] = "custom_pause"
        await query.message.reply_text("مکث بین بخش‌ها را به میلی‌ثانیه بفرست.")
        return
    if data == "recipecfg:set_word_pause":
        context.user_data["awaiting_input"] = "custom_word_pause"
        await query.message.reply_text("مکث بین کلمات را به میلی‌ثانیه بفرست.")
        return
    if data == "recipecfg:use_custom":
        service.update_settings(user_id, selected_recipe="telegram_custom_ladder")
        await settings_menu(update, context)
        return
    if data == "recipecfg:back":
        await settings_menu(update, context)
        return
    if data == "settings:set_page_size":
        context.user_data["awaiting_input"] = "page_size"
        await query.message.reply_text("تعداد آیتم هر صفحه را بفرست.")
        return
    if data == "settings:back":
        await _send_or_edit(update, _welcome_text(service, user_id), reply_markup=_main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.effective_message.reply_text("لغو شد.", reply_markup=MENU_KEYBOARD)
    return ConversationHandler.END


def _service(context: ContextTypes.DEFAULT_TYPE) -> TelegramBotService:
    return context.application.bot_data["service"]


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📚 کتابخانه", callback_data="menu:library"), InlineKeyboardButton("⚙️ تنظیمات", callback_data="menu:settings")],
            [InlineKeyboardButton("🎼 ریسیپی‌ها", callback_data="menu:recipes")],
            [InlineKeyboardButton("🎧 ارسال همه", callback_data="menu:send_all"), InlineKeyboardButton("📤 خروجی CSV", callback_data="menu:export_csv")],
            [InlineKeyboardButton("📥 ایمپورت CSV", callback_data="menu:import_csv"), InlineKeyboardButton("❓ راهنما", callback_data="menu:help")],
        ]
    )


def _post_import_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📚 دیدن کتابخانه", callback_data="menu:library")],
            [InlineKeyboardButton("🎧 شروع ارسال ویس‌ها", callback_data="menu:send_all")],
        ]
    )


def _settings_keyboard(service: TelegramBotService, user_id: int) -> InlineKeyboardMarkup:
    settings = service.get_settings(user_id)
    custom_badge = "🧪" if settings.selected_recipe == "telegram_custom_ladder" else "🧩"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎼 انتخاب Recipe", callback_data="settings:recipe"), InlineKeyboardButton("🛠 مدیریت Recipeها", callback_data="menu:recipes")],
            [InlineKeyboardButton("🌍 زبان مقصد", callback_data="settings:target_language")],
            [InlineKeyboardButton("🗣 انتخاب Provider", callback_data="settings:provider")],
            [InlineKeyboardButton("💾 فرمت خروجی", callback_data="settings:format")],
            [InlineKeyboardButton(f"{custom_badge} Recipe سفارشی", callback_data="settings:custom_recipe")],
            [InlineKeyboardButton("📄 تعداد آیتم هر صفحه", callback_data="settings:set_page_size")],
            [InlineKeyboardButton("🏠 بازگشت", callback_data="settings:back")],
        ]
    )


def _recipe_selection_keyboard(service: TelegramBotService, user_id: int) -> InlineKeyboardMarkup:
    settings = service.get_settings(user_id)
    rows = []
    for recipe in service.available_recipes(user_id):
        badge = "✅" if recipe.recipe_name == settings.selected_recipe else "▫️"
        rows.append([InlineKeyboardButton(f"{badge} {recipe.display_name}", callback_data=f"settings:recipe:set:{recipe.recipe_name}")])
        if recipe.origin == "shared" and recipe.recipe_name != "telegram_custom_ladder":
            rows.append([InlineKeyboardButton(f"✏️ ادیت فاصله‌های {recipe.display_name}", callback_data=f"recipeedit:open:{recipe.recipe_name}")])
        if recipe.origin == "user":
            rows.append(
                [
                    InlineKeyboardButton("📝 ادیت", callback_data=f"recipes:edit:{recipe.recipe_name}"),
                    InlineKeyboardButton("🗑 حذف", callback_data=f"recipes:delete:{recipe.recipe_name}"),
                ]
            )
        if recipe.recipe_name == "telegram_custom_ladder":
            rows.append([InlineKeyboardButton("🧪 ادیت recipe سفارشی فعلی", callback_data="settings:custom_recipe")])
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="settings:back")])
    return InlineKeyboardMarkup(rows)


def _provider_selection_keyboard(service: TelegramBotService, user_id: int) -> InlineKeyboardMarkup:
    settings = service.get_settings(user_id)
    rows = []
    for provider in service.available_tts_providers():
        badge = "✅" if provider["name"] == settings.selected_provider else "▫️"
        availability = "online" if provider["dependency_available"] else "missing"
        rows.append([InlineKeyboardButton(f"{badge} {provider['name']} | {availability}", callback_data=f"settings:provider:set:{provider['name']}")])
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="settings:back")])
    return InlineKeyboardMarkup(rows)


def _output_format_keyboard(service: TelegramBotService, user_id: int) -> InlineKeyboardMarkup:
    settings = service.get_settings(user_id)
    rows = [[InlineKeyboardButton(f"{'✅' if fmt == settings.output_format else '▫️'} {fmt.upper()}", callback_data=f"settings:format:set:{fmt}")] for fmt in service.available_output_formats()]
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="settings:back")])
    return InlineKeyboardMarkup(rows)


def _target_language_keyboard(service: TelegramBotService, user_id: int) -> InlineKeyboardMarkup:
    current = service.get_target_language(user_id)
    rows = [
        [
            InlineKeyboardButton(
                f"{'✅' if lang['code'] == current else '▫️'} {lang['emoji']} {lang['label']}",
                callback_data=f"settings:target_language:set:{lang['code']}",
            )
        ]
        for lang in service.available_target_languages()
    ]
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="settings:back")])
    return InlineKeyboardMarkup(rows)


def _recipe_override_keyboard(recipe_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⏱ کمتر/بیشتر کردن سکوت‌ها", callback_data="recipeedit:set_silence")],
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="settings:recipe")],
        ]
    )


def _recipes_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ ساخت recipe جدید", callback_data="recipes:new")],
            [InlineKeyboardButton("📚 دیدن همه recipeها", callback_data="recipes:list")],
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="settings:back")],
        ]
    )


def _custom_recipe_keyboard(service: TelegramBotService, user_id: int) -> InlineKeyboardMarkup:
    target_language = service.get_target_language(user_id)
    target_voice_male = {
        "fr": "fr-FR-HenriNeural",
        "en": "en-US-ChristopherNeural",
        "fa": "fa-IR-FaridNeural",
    }.get(target_language, "fr-FR-HenriNeural")
    target_voice_female = {
        "fr": "fr-FR-DeniseNeural",
        "en": "en-US-JennyNeural",
        "fa": "fa-IR-DilaraNeural",
    }.get(target_language, "fr-FR-DeniseNeural")
    custom = service.describe_custom_recipe(user_id)
    prompt_rows = [
        InlineKeyboardButton(
            f"{'✅' if preset['value'] == custom['prompt_field'] else '▫️'} {preset['label']}",
            callback_data=f"recipecfg:prompt:{preset['value']}",
        )
        for preset in service.recipe_prompt_presets()
    ]
    return InlineKeyboardMarkup(
        [
            prompt_rows,
            [InlineKeyboardButton("🇮🇷 Prompt زن", callback_data="recipecfg:voice:prompt_voice:fa-IR-DilaraNeural"), InlineKeyboardButton("🇮🇷 Prompt مرد", callback_data="recipecfg:voice:prompt_voice:fa-IR-FaridNeural")],
            [InlineKeyboardButton("⏱ مکث بین بخش‌ها", callback_data="recipecfg:set_pause"), InlineKeyboardButton("🪶 مکث بین کلمات", callback_data="recipecfg:set_word_pause")],
            [InlineKeyboardButton("👨 صدای مرد مقصد", callback_data=f"recipecfg:target_voice:{target_voice_male}"), InlineKeyboardButton("👩 صدای زن مقصد", callback_data=f"recipecfg:target_voice:{target_voice_female}")],
            [InlineKeyboardButton("🐢 سرعت کندتر", callback_data="recipecfg:rate:slow_rate:-15%"), InlineKeyboardButton("🚀 سرعت عادی", callback_data="recipecfg:rate:slow_rate:+0%")],
            [InlineKeyboardButton("✅ استفاده از این Recipe", callback_data="recipecfg:use_custom")],
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="recipecfg:back")],
        ]
    )


def _recipe_wizard_keyboard(service: TelegramBotService, user_id: int, draft: dict[str, Any]) -> InlineKeyboardMarkup:
    target_language = service.get_target_language(user_id)
    target_voice_male = {
        "fr": "fr-FR-HenriNeural",
        "en": "en-US-ChristopherNeural",
        "fa": "fa-IR-FaridNeural",
    }.get(target_language, "fr-FR-HenriNeural")
    target_voice_female = {
        "fr": "fr-FR-DeniseNeural",
        "en": "en-US-JennyNeural",
        "fa": "fa-IR-DilaraNeural",
    }.get(target_language, "fr-FR-DeniseNeural")
    rows = []
    for template in service.available_recipe_templates():
        badge = "✅" if draft.get("template_key") == template["key"] else "▫️"
        rows.append([InlineKeyboardButton(f"{badge} قالب {template['label']}", callback_data=f"recipes:wizard:template:{template['key']}")])
    prompt_row = []
    for preset in service.recipe_prompt_presets():
        badge = "✅" if draft.get("prompt_field") == preset["value"] else "▫️"
        prompt_row.append(InlineKeyboardButton(f"{badge} {preset['label']}", callback_data=f"recipes:wizard:prompt:{preset['value']}"))
    rows.append(prompt_row)
    rows.append([InlineKeyboardButton("👨 صدای مرد", callback_data=f"recipes:wizard:target_voice:{target_voice_male}"), InlineKeyboardButton("👩 صدای زن", callback_data=f"recipes:wizard:target_voice:{target_voice_female}")])
    rows.append([InlineKeyboardButton("⏱ مکث بین بخش‌ها", callback_data="recipes:wizard:set_pause"), InlineKeyboardButton("🪶 مکث بین کلمات", callback_data="recipes:wizard:set_word_pause")])
    rows.append([InlineKeyboardButton(f"{'✅' if draft.get('include_word_by_word') else '▫️'} کلمه‌به‌کلمه", callback_data="recipes:wizard:toggle:include_word_by_word")])
    rows.append([InlineKeyboardButton(f"{'✅' if draft.get('include_slow_pass') else '▫️'} اجرای آهسته", callback_data="recipes:wizard:toggle:include_slow_pass")])
    rows.append([InlineKeyboardButton(f"{'✅' if draft.get('closing_repeat') else '▫️'} تکرار نهایی", callback_data="recipes:wizard:toggle:closing_repeat")])
    rows.append([InlineKeyboardButton("💾 ذخیره", callback_data="recipes:wizard:save"), InlineKeyboardButton("لغو", callback_data="recipes:wizard:cancel")])
    return InlineKeyboardMarkup(rows)


async def _show_library(update: Update, context: ContextTypes.DEFAULT_TYPE, *, page: int, flash: str | None = None) -> None:
    service = _service(context)
    user_id = _effective_user_id(update)
    settings = service.get_settings(user_id)
    page_size = int(settings.extra_config().get("page_size", SENTENCES_PAGE_SIZE))
    page_payload = service.paginated_user_sentences(user_id, page, page_size)
    text = _library_text(service, user_id, page_payload, flash=flash)
    await _send_or_edit(update, text, reply_markup=_library_keyboard(service, user_id, page_payload), parse_mode=ParseMode.MARKDOWN)


async def _show_recipe_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service = _service(context)
    user_id = _effective_user_id(update)
    draft = dict(context.user_data.get("draft_recipe", {}))
    text = _recipe_wizard_text(service, user_id, draft)
    await _send_or_edit(
        update,
        text,
        reply_markup=_recipe_wizard_keyboard(service, user_id, draft),
        parse_mode=ParseMode.MARKDOWN,
    )


def _library_keyboard(service: TelegramBotService, user_id: int, page_payload: dict[str, object]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    target_language = service.get_target_language(user_id)
    for sentence in page_payload["items"]:
        preview = service.target_text(sentence, target_language).replace("\n", " ").strip()
        rows.append([InlineKeyboardButton(f"🎧 {sentence.id}. {preview[:45]}", callback_data=f"library:view:{sentence.id}")])
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
            [InlineKeyboardButton("➕ افزودن جمله جدید", callback_data="library:add")],
            [InlineKeyboardButton("🔄 تازه‌سازی", callback_data="library:refresh")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="settings:back")],
        ]
    )
    return InlineKeyboardMarkup(rows)


async def _show_sentence_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, sentence_id: str) -> None:
    service = _service(context)
    user_id = _effective_user_id(update)
    target_language = service.get_target_language(user_id)
    sentence = next((item for item in service.list_user_sentences(user_id) if item.id == sentence_id), None)
    if sentence is None:
        await _send_or_edit(update, "❌ این جمله پیدا نشد.", reply_markup=_main_menu_keyboard())
        return
    target_label = service.target_language_label(target_language)
    text = (
        f"*Sentence {sentence.id}*\n\n"
        f"{service.target_language_emoji(target_language)} {target_label}: {service.target_text(sentence, target_language) or '-'}\n"
        f"🇮🇷 فارسی: {sentence.persian or '-'}\n"
        f"🇬🇧 English: {sentence.english or '-'}\n"
        f"🇫🇷 Français: {sentence.french or '-'}\n\n"
        f"🏷 Level: `{sentence.level}`\n"
        f"📂 Category: `{sentence.category}`"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎧 تولید و ارسال", callback_data=f"library:send:{sentence.id}")],
            [InlineKeyboardButton("✏️ ادیت جمله", callback_data=f"library:edit:{sentence.id}")],
            [InlineKeyboardButton("🗑 حذف", callback_data=f"library:remove:{sentence.id}")],
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="menu:library")],
        ]
    )
    await _send_or_edit(update, text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)


async def _send_single_sentence(update: Update, context: ContextTypes.DEFAULT_TYPE, sentence_id: str) -> None:
    service = _service(context)
    await _send_or_edit(update, f"🎙 در حال ساخت فایل صوتی جمله `{sentence_id}` ...", parse_mode=ParseMode.MARKDOWN)
    await context.bot.send_chat_action(chat_id=_chat_id(update), action=ChatAction.UPLOAD_VOICE)
    payload = service.generate_sentence_audio_for_user(_effective_user_id(update), sentence_id)
    with payload["audio_path"].open("rb") as handle:
        await context.bot.send_audio(chat_id=_chat_id(update), audio=handle, caption=f"{payload['caption']}\n\n🎼 {payload['recipe_name']}")
    await context.bot.send_message(chat_id=_chat_id(update), text="✅ فایل ارسال شد.", reply_markup=MENU_KEYBOARD)


async def _send_or_edit(update: Update, text: str, *, reply_markup: InlineKeyboardMarkup | None = None, parse_mode: str | None = None) -> None:
    query = update.callback_query
    if query is not None and query.message is not None:
        try:
            await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except BadRequest as exc:
            if "Message is not modified" not in str(exc):
                raise
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
    target_language = service.get_target_language(user_id)
    return (
        "🌿 *به EchoLingua Bot خوش آمدی*\n\n"
        "CSV وارد کن، کتابخانه بساز، جمله‌ها را ادیت کن، و برای زبان مقصد انتخابی‌ات ویس بگیر.\n\n"
        f"📚 تعداد جمله‌ها: `{summary['count']}`\n"
        f"🌍 زبان مقصد: `{escape_markdown(service.target_language_label(target_language))}`\n"
        f"🎼 Recipe: `{escape_markdown(settings.selected_recipe)}`\n"
        f"🗣 Provider: `{escape_markdown(settings.selected_provider)}`\n"
        f"💾 Output: `{escape_markdown(settings.output_format)}`\n"
        f"📥 آخرین ایمپورت: `{escape_markdown(import_line)}`"
    )


def _help_text() -> str:
    return (
        "🧭 *راهنما*\n\n"
        "1. CSV را ایمپورت کن.\n"
        "2. از تنظیمات، زبان مقصد را انتخاب کن.\n"
        "3. در کتابخانه جمله‌ها را ببین، ویرایش کن، حذف کن یا ویس بگیر.\n"
        "4. برای افزودن جمله جدید، فقط متن مقصد و ترجمه فارسی را بفرست.\n"
        "5. از بخش Recipe می‌توانی recipeهای موجود را هم برای فاصله‌ها تنظیم کنی."
    )


def _settings_text(service: TelegramBotService, user_id: int) -> str:
    settings = service.get_settings(user_id)
    custom = service.describe_custom_recipe(user_id)
    target_language = service.get_target_language(user_id)
    page_size = settings.extra_config().get("page_size", SENTENCES_PAGE_SIZE)
    return (
        "⚙️ *تنظیمات فعلی*\n\n"
        f"🌍 Target: `{escape_markdown(service.target_language_label(target_language))}`\n"
        f"🎼 Recipe: `{escape_markdown(settings.selected_recipe)}`\n"
        f"🗣 Provider: `{escape_markdown(settings.selected_provider)}`\n"
        f"💾 Output: `{escape_markdown(settings.output_format)}`\n"
        f"📄 Page size: `{page_size}`\n"
        f"🧪 Custom recipe: `{escape_markdown(custom['summary'])}`"
    )


def _recipe_selection_text(service: TelegramBotService, user_id: int) -> str:
    settings = service.get_settings(user_id)
    recipes = service.available_recipes(user_id)
    return (
        f"🎼 *انتخاب Recipe*\n\n"
        f"فعلی: `{escape_markdown(settings.selected_recipe)}`\n"
        f"تعداد recipeهای قابل استفاده: `{len(recipes)}`\n"
        "می‌توانی recipe عمومی را انتخاب کنی، فاصله‌هایش را تنظیم کنی، یا recipe شخصی خودت را بسازی."
    )


def _provider_selection_text(service: TelegramBotService, user_id: int) -> str:
    settings = service.get_settings(user_id)
    return f"🗣 *انتخاب Provider*\n\nفعلی: `{escape_markdown(settings.selected_provider)}`"


def _output_format_text(service: TelegramBotService, user_id: int) -> str:
    settings = service.get_settings(user_id)
    return f"💾 *فرمت خروجی*\n\nفعلی: `{escape_markdown(settings.output_format)}`"


def _target_language_text(service: TelegramBotService, user_id: int) -> str:
    return f"🌍 *زبان مقصد*\n\nفعلی: `{escape_markdown(service.target_language_label(service.get_target_language(user_id)))}`"


def _recipe_override_text(service: TelegramBotService, user_id: int, recipe_name: str) -> str:
    override = service.describe_recipe_override(user_id, recipe_name)
    return (
        f"✏️ *ویرایش Recipe `{escape_markdown(recipe_name)}`*\n\n"
        f"silence_scale: `{override['silence_scale']}`\n"
        "هرچه کمتر باشد، فاصله‌های سکوت کمتر می‌شود."
    )


def _custom_recipe_text(service: TelegramBotService, user_id: int) -> str:
    custom = service.describe_custom_recipe(user_id)
    target_language = service.get_target_language(user_id)
    return (
        "🧪 *Recipe سفارشی*\n\n"
        f"Target: `{escape_markdown(service.target_language_label(target_language))}`\n"
        f"Prompt: `{escape_markdown(custom['prompt_field'])}`\n"
        f"Pause: `{custom['pause_between_ms']}ms`\n"
        f"Word pause: `{custom['word_pause_ms']}ms`\n"
        f"Target voice: `{escape_markdown(custom['normal_voice'])}`\n"
        f"Slow rate: `{escape_markdown(custom['slow_rate'])}`\n\n"
        f"{escape_markdown(custom['summary'])}"
    )


def _recipes_menu_text(service: TelegramBotService, user_id: int) -> str:
    user_recipes = service.list_user_recipe_descriptors(user_id)
    selected = service.get_settings(user_id).selected_recipe
    return (
        "🎼 *مدیریت ریسیپی‌ها*\n\n"
        "اینجا می‌توانی recipeهای عمومی را ببینی و برای خودت هر چند تا recipe خواستی بسازی.\n\n"
        f"🎯 recipe فعال: `{escape_markdown(selected)}`\n"
        f"👤 recipeهای شخصی شما: `{len(user_recipes)}`\n"
        "برای ساخت recipe جدید، بات قدم‌به‌قدم ازت سوال می‌پرسد و با دکمه‌ها جلو می‌برد."
    )


def _recipe_wizard_text(service: TelegramBotService, user_id: int, draft: dict[str, Any]) -> str:
    normalized = dict(draft)
    target_language = service.get_target_language(user_id)
    name = str(normalized.get("name") or "هنوز اسم نداده‌ای")
    summary = "اول اسم recipe را بفرست." if not normalized.get("name") else service.guided_recipe_summary(user_id, normalized)
    return (
        "🧭 *ساخت/ویرایش ریسیپی شخصی*\n\n"
        f"📝 نام: `{escape_markdown(name)}`\n"
        f"🌍 زبان مقصد فعلی: `{escape_markdown(service.target_language_label(target_language))}`\n"
        f"🧩 قالب: `{escape_markdown(str(normalized.get('template_key', 'ladder')))}`\n"
        f"🎙 Prompt: `{escape_markdown(str(normalized.get('prompt_field', 'persian')))}`\n"
        f"🗣 صدای مقصد: `{escape_markdown(str(normalized.get('target_voice', '-')))}`\n"
        f"⏱ مکث بین بخش‌ها: `{normalized.get('pause_between_ms', '-')}` ms\n"
        f"🪶 مکث بین کلمات: `{normalized.get('word_pause_ms', '-')}` ms\n"
        f"🔁 کلمه‌به‌کلمه: `{'on' if normalized.get('include_word_by_word', False) else 'off'}`\n"
        f"🐢 اجرای آهسته: `{'on' if normalized.get('include_slow_pass', False) else 'off'}`\n"
        f"🎯 تکرار نهایی: `{'on' if normalized.get('closing_repeat', False) else 'off'}`\n\n"
        f"{escape_markdown(summary)}"
    )


def _library_text(service: TelegramBotService, user_id: int, page_payload: dict[str, object], flash: str | None = None) -> str:
    summary = service.sentence_summary(user_id)
    latest_import = service.latest_import_summary(user_id)
    import_line = latest_import["file_name"] if latest_import else "-"
    page = int(page_payload["page"]) + 1
    total_pages = int(page_payload["total_pages"])
    lines = [
        "📚 *کتابخانه شما*",
        "",
        f"تعداد کل جمله‌ها: `{summary['count']}`",
        f"صفحه: `{page}/{total_pages}`",
        f"آخرین CSV: `{escape_markdown(import_line)}`",
        f"زبان مقصد فعلی: `{escape_markdown(service.target_language_label(service.get_target_language(user_id)))}`",
        "",
    ]
    if flash:
        lines.append(f"{escape_markdown(flash)}\n")
    for sentence in page_payload["items"]:
        target_text = service.target_text(sentence, service.get_target_language(user_id)).replace("\n", " ").strip() or "-"
        lines.append(
            f"`{escape_markdown(sentence.id)}`  {escape_markdown(target_text)}"
        )
    if not page_payload["items"]:
        lines.append("هنوز کتابخانه‌ات خالی است.")
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
