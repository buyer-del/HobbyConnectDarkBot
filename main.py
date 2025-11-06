import os
import logging
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
from ai import transcribe_audio, extract_text_from_image
from sheets_api import append_task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Flask
flask_app = Flask(__name__)

# Telegram App
bot_app = Application.builder().token(TOKEN).build()


# -------------------------
# ВНУТРІШНІ ФУНКЦІЇ
# -------------------------

def _buf(context):
    """Буфер для чернетки."""
    if "buffer" not in context.user_data:
        context.user_data["buffer"] = []
    return context.user_data["buffer"]


def _kb():
    """Кнопки."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Створити задачу", callback_data="new_task")],
        [InlineKeyboardButton("🧹 Очистити", callback_data="clear_buf")],
    ])


# -------------------------
# /start
# -------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бот працює. Надішли текст, фото або голос. "
        "Усе піде в чернетку. Коли готово — натисни «Створити задачу».",
        reply_markup=_kb(),
    )


# -------------------------
# ОБРОБКА ПОВІДОМЛЕНЬ
# -------------------------

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buf = _buf(context)
    buf.append(update.message.text)

    await update.message.reply_text(
        "✅ Текст додано у чернетку.",
        reply_markup=_kb(),
    )


async def photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buf = _buf(context)
    try:
        file = await update.message.photo[-1].get_file()
        local_path = "photo.jpg"
        await file.download_to_drive(local_path)

        text = extract_text_from_image(local_path)
        buf.append(text)

        await update.message.reply_text(
            "🖼 Текст із фото додано.",
            reply_markup=_kb(),
        )
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text("❌ Помилка розпізнавання фото.")


async def voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buf = _buf(context)
    try:
        file = await update.message.voice.get_file()
        local_path = "voice.ogg"
        await file.download_to_drive(local_path)

        text = transcribe_audio(local_path)
        buf.append(text)

        await update.message.reply_text(
            "🎤 Голос розпізнано й додано.",
            reply_markup=_kb(),
        )
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text("❌ Помилка розпізнавання голосу.")


# -------------------------
# ОБРОБКА КНОПОК
# -------------------------

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    buf = _buf(context)

    # Очищення
    if q.data == "clear_buf":
        buf.clear()
        await q.message.reply_text("🧹 Чернетку очищено.", reply_markup=_kb())
        return

    # Створення задачі
    if q.data == "new_task":
        if not buf:
            await q.message.reply_text("⚠️ Чернетка порожня.", reply_markup=_kb())
            return

        text = "\n".join(buf)

        try:
            append_task("Задача", text, "#інше")
            await q.message.reply_text("✅ Задачу створено!", reply_markup=_kb())
        except Exception as e:
            logger.exception(e)
            await q.message.reply_text("❌ Помилка запису у таблицю.")

        buf.clear()
        return


# -------------------------
# WEBHOOK
# -------------------------

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot_app.bot)
    bot_app.update_queue.put_nowait(update)
    return "ok"


# -------------------------
# ЗАПУСК
# -------------------------

def start_bot():
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CallbackQueryHandler(buttons))

    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    bot_app.add_handler(MessageHandler(filters.PHOTO, photo_message))
    bot_app.add_handler(MessageHandler(filters.VOICE, voice_message))

    bot_app.run_webhook(
        listen="0.0.0.0",
        port=10000,
        webhook_url=f"{WEBHOOK_URL}/webhook",
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    start_bot()
