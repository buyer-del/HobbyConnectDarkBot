import os
import logging
from flask import Flask, request
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from ai import transcribe_audio, extract_text_from_image
from sheets_api import append_task

# ======================
# ЛОГИ
# ======================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ======================
# ЗМІННІ
# ======================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "10000"))

app = Flask(__name__)  # Flask-сервер

# Telegram App
bot_app = Application.builder().token(TOKEN).build()


# ======================
# ДОПОМІЖНЕ
# ======================
def _buf(context):
    return context.user_data.setdefault("buffer", [])


def _kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Створити задачу", callback_data="new_task")],
        [InlineKeyboardButton("🧹 Очистити", callback_data="clear_buf")],
    ])


# ======================
# КОМАНДИ
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бот працює. Можеш надсилати текст, фото або голос. "
        "Усе додається у чернетку.",
        reply_markup=_kb(),
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Бот онлайн")


# ======================
# ПОВІДОМЛЕННЯ
# ======================
async def text_message(update, context):
    _buf(context).append(update.message.text)
    await update.message.reply_text("✅ Додано в чернетку.", reply_markup=_kb())


async def photo_message(update, context):
    file = await update.message.photo[-1].get_file()
    path = "photo.jpg"
    await file.download_to_drive(path)
    try:
        text = extract_text_from_image(path)
        _buf(context).append(text)
        await update.message.reply_text("🖼 Текст із фото додано.", reply_markup=_kb())
    except Exception:
        await update.message.reply_text("❌ Помилка розпізнавання фото.")
    finally:
        try: os.remove(path)
        except: pass


async def voice_message(update, context):
    file = await update.message.voice.get_file()
    path = "voice.ogg"
    await file.download_to_drive(path)
    try:
        text = transcribe_audio(path)
        _buf(context).append(text)
        await update.message.reply_text("🎤 Голос додано.", reply_markup=_kb())
    except Exception:
        await update.message.reply_text("❌ Помилка голосу.")
    finally:
        try: os.remove(path)
        except: pass


# ======================
# КНОПКИ
# ======================
async def buttons(update, context):
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
        except Exception:
            await q.message.reply_text("❌ Помилка запису.")
        buf.clear()
        return


# ======================
# FLASK WEBHOOK
# ======================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    update = Update.de_json(data, bot_app.bot)
   import asyncio
asyncio.run(bot_app.process_update(update))


    return "ok"


# ======================
# ЗАПУСК
# ======================
def main():
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("ping", ping))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    bot_app.add_handler(MessageHandler(filters.PHOTO, photo_message))
    bot_app.add_handler(MessageHandler(filters.VOICE, voice_message))
    bot_app.add_handler(CallbackQueryHandler(buttons))

    # Встановлюємо вебхук
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        bot_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    )

    # Запускаємо Flask (Render вимагає запуск сервера)
    app.run(host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
