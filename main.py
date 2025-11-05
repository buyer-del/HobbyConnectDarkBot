import os
import logging
import asyncio
import threading
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from ai import transcribe_audio, extract_text_from_image
from sheets_api import append_task

# -----------------------
# ЛОГУВАННЯ
# -----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# -----------------------
# ЗМІННІ СЕРЕДОВИЩА
# -----------------------
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise SystemExit("❌ TELEGRAM_BOT_TOKEN не знайдено у змінних середовища")

# -----------------------
# ІНІЦІАЛІЗАЦІЯ
# -----------------------
app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

# -----------------------
# ДОПОМОЖНІ ФУНКЦІЇ
# -----------------------
def _buf(context: ContextTypes.DEFAULT_TYPE) -> list:
    return context.user_data.setdefault("buffer", [])

def _kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Створити задачу", callback_data="new_task")],
        [InlineKeyboardButton("🧹 Очистити чернетку", callback_data="clear_buf")]
    ])

# -----------------------
# КОМАНДИ
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привіт! Надсилай текст, голос або фото.\n"
        "Коли завершиш — натисни кнопку, щоб створити задачу.",
        reply_markup=_kb()
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Бот працює!")

# -----------------------
# ТЕКСТ
# -----------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return
    _buf(context).append(text)
    await update.message.reply_text(
        "💾 Додано до чернетки.",
        reply_markup=_kb()
    )

# -----------------------
# ГОЛОС
# -----------------------
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice_or_audio = update.message.voice or update.message.audio
    if not voice_or_audio:
        await update.message.reply_text("⚠️ Не вдалося отримати аудіо.", reply_markup=_kb())
        return
    tg_file = await voice_or_audio.get_file()
    tmp = "voice.ogg"
    await tg_file.download_to_drive(tmp)
    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, transcribe_audio, tmp)
        if text:
            _buf(context).append(text)
            await update.message.reply_text(f"🧠 Розпізнано:\n{text}", reply_markup=_kb())
        else:
            await update.message.reply_text("😕 Не вдалося розпізнати.", reply_markup=_kb())
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text("❌ Помилка розпізнавання.", reply_markup=_kb())
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

# -----------------------
# ФОТО
# -----------------------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("⚠️ Фото не знайдено.", reply_markup=_kb())
        return
    tg_file = await update.message.photo[-1].get_file()
    tmp = "photo.jpg"
    await tg_file.download_to_drive(tmp)
    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, extract_text_from_image, tmp)
        if text:
            _buf(context).append(text)
            await update.message.reply_text(f"📄 Розпізнано текст:\n{text}", reply_markup=_kb())
        else:
            await update.message.reply_text("😕 Текст не знайдено.", reply_markup=_kb())
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text("❌ Помилка розпізнавання.", reply_markup=_kb())
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

# -----------------------
# КНОПКИ
# -----------------------
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    buf = _buf(context)

    if q.data == "clear_buf":
        buf.clear()
        await q.edit_message_text("🧹 Чернетку очищено.")
        return

    if q.data == "new_task":
        if not buf:
            await q.edit_message_text("⚠️ Чернетка порожня.")
            return
        text = "\n".join(buf)
        try:
            append_task("Задача", text, "#інше")
            await q.edit_message_text("✅ Задачу створено!")
        except Exception as e:
            logger.exception(e)
            await q.edit_message_text("❌ Помилка запису у таблицю.")
        buf.clear()

# -----------------------
# ОБРОБНИКИ
# -----------------------
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("ping", ping))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
application.add_handler(CallbackQueryHandler(buttons))

# -----------------------
# FLASK
# -----------------------
@app.route("/")
def home():
    return "Бот працює ✅"

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        application.update_queue.put_nowait(update)
        return "ok", 200
    except Exception as e:
        logger.exception(e)
        return "error", 500

# -----------------------
# ЗАПУСК
# -----------------------
if __name__ == "__main__":
    async def run_bot():
        await application.initialize()
        await application.start()
        logger.info("✅ Telegram application started (webhook mode)")

    def start_bot():
        asyncio.run(run_bot())

    thread = threading.Thread(target=start_bot, daemon=True)
    thread.start()

    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Запуск Flask на порті {port}")
    app.run(host="0.0.0.0", port=port)

