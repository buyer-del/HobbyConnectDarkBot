import os
import logging
import asyncio
import threading
from flask import Flask, request
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest

from ai import transcribe_audio, extract_text_from_image
from sheets_api import append_task

# =========================
# ЛОГИ
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# ЗМІННІ СЕРЕДОВИЩА
# =========================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # напр.: https://hobbyconnectdarkbot.onrender.com
PORT = int(os.getenv("PORT", 10000))

if not TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN не задано")
if not WEBHOOK_URL or not WEBHOOK_URL.startswith("https://"):
    raise SystemExit("WEBHOOK_URL не задано або не HTTPS")

MAX_BUFFER_ITEMS = 3  # ліміт чорнетки

# =========================
# Flask
# =========================
flask_app = Flask(__name__)

@flask_app.route("/", methods=["GET", "HEAD"])
def root():
    return "ok", 200

# =========================
# Telegram Application (PTB)
# =========================
bot_app = Application.builder().token(TOKEN).build()


# -------------------------
# ДОПОМІЖНЕ
# -------------------------
def _buf(context: ContextTypes.DEFAULT_TYPE):
    return context.user_data.setdefault("buffer", [])

def _kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Створити задачу", callback_data="new_task")],
        [InlineKeyboardButton("🧹 Очистити", callback_data="clear_buf")],
    ])

async def _remove_old_keyboard(context: ContextTypes.DEFAULT_TYPE):
    """Прибрати кнопки з попереднього бот-повідомлення (якщо воно було)."""
    chat_id = context.user_data.get("last_kb_chat_id")
    msg_id = context.user_data.get("last_kb_message_id")
    if not chat_id or not msg_id:
        return
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=msg_id,
            reply_markup=None
        )
    except BadRequest:
        # Повідомлення може бути занадто старим або вже без клавіатури — ігноруємо
        pass
    except Exception as e:
        logger.exception("Не вдалось прибрати старі кнопки: %s", e)

def _buffer_has_space(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return len(_buf(context)) < MAX_BUFFER_ITEMS

async def _post_text_with_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Надсилає ПОВІДОМЛЕННЯ з самим текстом + клавіатуру, попередні кнопки прибирає."""
    # 1) Прибрати попередні кнопки
    await _remove_old_keyboard(context)

    # 2) Надіслати новий текст з кнопками
    sent = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=_kb()
    )

    # 3) Запам’ятати, де тепер висять кнопки
    context.user_data["last_kb_chat_id"] = sent.chat_id
    context.user_data["last_kb_message_id"] = sent.message_id


# -------------------------
# КОМАНДИ
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот працює. Надішли текст, фото або голос — усе буде розпізнано.")
    # Показуємо порожній стан
    await _post_text_with_keyboard(update, context, "Чорнетка порожня. Додавайте записи повідомленнями.")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong ✅")


# -------------------------
# ПОВІДОМЛЕННЯ: ТЕКСТ
# -------------------------
async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("❌ Порожній текст не додаю.")
        return

    if not _buffer_has_space(context):
        await update.message.reply_text("⚠️ Чернетка заповнена (3/3). Створіть задачу або очистіть.")
        return

    _buf(context).append(text)

    # Службове повідомлення
    await update.message.reply_text("✅ Додано в чернетку")

    # Окремим повідомленням — сам текст + кнопки (тільки під ним)
    await _post_text_with_keyboard(update, context, text)


# -------------------------
# ПОВІДОМЛЕННЯ: ФОТО
# -------------------------
async def photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        file = await update.message.photo[-1].get_file()
        local_path = "photo.jpg"
        await file.download_to_drive(local_path)

        # OCR
        recognized = (extract_text_from_image(local_path) or "").strip()

        if not recognized:
            await update.message.reply_text("❌ Нічого не розпізнано на фото.")
            return

        if not _buffer_has_space(context):
            await update.message.reply_text("⚠️ Чернетка заповнена (3/3). Створіть задачу або очистіть.")
            return

        _buf(context).append(recognized)

        # Службове повідомлення
        await update.message.reply_text("🖼 Розпізнано текст")

        # Окремим повідомленням — сам текст + кнопки (тільки під ним)
        await _post_text_with_keyboard(update, context, recognized)

    except Exception as e:
        logger.exception("Помилка розпізнавання фото: %s", e)
        await update.message.reply_text("❌ Помилка розпізнавання фото.")


# -------------------------
# ПОВІДОМЛЕННЯ: ГОЛОС
# -------------------------
async def voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        file = await update.message.voice.get_file()
        local_path = "voice.ogg"
        await file.download_to_drive(local_path)

        # STT
        recognized = (transcribe_audio(local_path) or "").strip()

        if not recognized:
            await update.message.reply_text("❌ Голос не вдалося розпізнати.")
            return

        if not _buffer_has_space(context):
            await update.message.reply_text("⚠️ Чернетка заповнена (3/3). Створіть задачу або очистіть.")
            return

        _buf(context).append(recognized)

        # Службове повідомлення
        await update.message.reply_text("🎤 Розпізнано текст")

        # Окремим повідомленням — сам текст + кнопки (тільки під ним)
        await _post_text_with_keyboard(update, context, recognized)

    except Exception as e:
        logger.exception("Помилка розпізнавання голосу: %s", e)
        await update.message.reply_text("❌ Помилка розпізнавання голосу.")


# -------------------------
# КНОПКИ
# -------------------------
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    buf = _buf(context)

    # Очистити чернетку
    if data == "clear_buf":
        buf.clear()
        await _remove_old_keyboard(context)
        await q.message.reply_text("🧹 Чернетку очищено.")
        return

    # Створити задачу
    if data == "new_task":
        if not buf:
            await q.message.reply_text("⚠️ Чернетка порожня.")
            return

        text = "\n".join(buf)
        try:
            append_task("Задача", text, "#інше")
            await _remove_old_keyboard(context)  # прибрали кнопки з останнього повідомлення
            await q.message.reply_text("✅ Задачу створено!")
            buf.clear()
        except Exception as e:
            logger.exception("Помилка запису у таблицю: %s", e)
            await q.message.reply_text("❌ Помилка запису у таблицю.")
        return


# =========================
# ASYNCIO LOOP (ФОН)
# =========================
ASYNC_LOOP = asyncio.new_event_loop()

def _run_loop_forever(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

# =========================
# WEBHOOK
# =========================
@flask_app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, bot_app.bot)

        asyncio.run_coroutine_threadsafe(
            bot_app.process_update(update),
            ASYNC_LOOP
        )
    except Exception as e:
        logger.error("Webhook error", exc_info=e)

    return "ok"


# =========================
# ЗАПУСК
# =========================
def main():
    # Хендлери
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("ping", ping))
    bot_app.add_handler(CallbackQueryHandler(buttons))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    bot_app.add_handler(MessageHandler(filters.PHOTO, photo_message))
    bot_app.add_handler(MessageHandler(filters.VOICE, voice_message))

    # 1) фоновий loop
    threading.Thread(target=_run_loop_forever, args=(ASYNC_LOOP,), daemon=True).start()

    # 2) PTB init/start
    asyncio.run_coroutine_threadsafe(bot_app.initialize(), ASYNC_LOOP).result()
    asyncio.run_coroutine_threadsafe(bot_app.start(), ASYNC_LOOP).result()

    # 3) webhook
    asyncio.run_coroutine_threadsafe(
        bot_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook"),
        ASYNC_LOOP
    ).result()

    logger.info("✅ PTB запущено; вебхук: %s/webhook", WEBHOOK_URL)

    # 4) Flask
    flask_app.run(host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
