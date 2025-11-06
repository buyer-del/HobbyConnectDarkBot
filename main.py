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

# Telegram Application
bot_app = Application.builder().token(TOKEN).build()


# -------------------------
# ВНУТРІШНІ ФУНКЦІЇ
# -------------------------

def _buf(context):
    """Буфер для тимчасового зберігання тексту перед створенням задачі."""
    if "buffer" not in context.user_data:
        context.user_data["buffer"] = []
    return context.user_data["buffer"]


def _kb():
    """Клавіатура з кнопками."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Додати текст", callback_data="add_text")],
        [InlineKeyboardButton("📌 Створити задачу", callback_data="new_task")],
        [InlineKeyboardButton("🧹 Очистити", callback_data="clear_buf")],
    ])


# -------------------------
# СТАРТ
# -------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бот працює. Надішли текст, фото або голосове повідомлення.\n"
        "Можеш зібрати чернетку та натиснути «Створити задачу».",
        reply_markup=_kb(),
    )


# -------------------------
# ОБРОБКА ЗВИЧАЙНИХ ПОВІДОМЛЕНЬ
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
            "🎤 Розпізнано і додано до чернетки.",
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
    await q.answer()
    buf = _buf(context)

    # Очистити буфер
    if q.data == "clear_buf":
        buf.clear()
        await q.message.reply_text("🧹 Чернетку очищено.", reply_markup=_kb())
        return

    # Створити задачу
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
    """Точка входу від Telegram."""
    data = request.get_json(force=True)
    update = Update.de_json(data, bot_app.bot)
    bot_app.update_queue.put_nowait(update)
    return "ok"


# -------------------------
# ЗАПУСК
# -------------------------

async def run_webhook():
    await bot_app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")


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

    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Запуск Flask на порті {port}")
    app.run(host="0.0.0.0", port=port)

