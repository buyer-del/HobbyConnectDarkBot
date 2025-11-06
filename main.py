import os
import logging
import asyncio
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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://hobbyconnectdarkbot.onrender.com
PORT = int(os.getenv("PORT", 10000))

# Flask app
flask_app = Flask(__name__)

# Telegram Application
bot_app = Application.builder().token(TOKEN).build()


# -------------------------
# INTERNAL HELPERS
# -------------------------

def _buf(context):
    if "buffer" not in context.user_data:
        context.user_data["buffer"] = []
    return context.user_data["buffer"]


def _kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Створити задачу", callback_data="new_task")],
        [InlineKeyboardButton("🧹 Очистити", callback_data="clear_buf")],
    ])


# -------------------------
# COMMANDS
# -------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бот працює. Надішли текст, фото або голос — усе піде в чернетку.",
        reply_markup=_kb(),
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong ✅")


# -------------------------
# MESSAGE HANDLERS
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

        await update.message.reply_text("🖼 Текст із фото додано.", reply_markup=_kb())
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

        await update.message.reply_text("🎤 Голос розпізнано й додано.", reply_markup=_kb())
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text("❌ Помилка розпізнавання голосу.")


# -------------------------
# BUTTON HANDLER
# -------------------------

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    buf = _buf(context)

    if q.data == "clear_buf":
        buf.clear()
        await q.message.reply_text("🧹 Чернетку очищено.", reply_markup=_kb())
        return

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
# FLASK WEBHOOK
# -------------------------

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, bot_app.bot)

        # Process update through PTB
        asyncio.get_event_loop().create_task(bot_app.process_update(update))

    except Exception as e:
        logger.error("Webhook error", exc_info=e)

    return "ok"


# -------------------------
# MAIN STARTUP
# -------------------------

def main():
    # Register handlers
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("ping", ping))
    bot_app.add_handler(CallbackQueryHandler(buttons))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    bot_app.add_handler(MessageHandler(filters.PHOTO, photo_message))
    bot_app.add_handler(MessageHandler(filters.VOICE, voice_message))

    loop = asyncio.get_event_loop()

    # ✅ Critical: initialize PTB manually
    loop.run_until_complete(bot_app.initialize())

    # ✅ Set webhook
    loop.run_until_complete(
        bot_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    )

    # ✅ Start PTB processing engine
    loop.run_until_complete(bot_app.start())

    # ✅ Start Flask server
    flask_app.run(host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
