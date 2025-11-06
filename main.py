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
from ai import transcribe_audio, extract_text_from_image
from sheets_api import append_task

# -------------------------
# ЛОГИ
# -------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------
# ЗМІННІ СЕРЕДОВИЩА
# -------------------------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # наприклад: https://hobbyconnectdarkbot.onrender.com
PORT = int(os.getenv("PORT", 10000))

if not TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN не задано")
if not WEBHOOK_URL or not WEBHOOK_URL.startswith("https://"):
    raise SystemExit("WEBHOOK_URL не задано або не HTTPS")

# -------------------------
# Flask
# -------------------------
flask_app = Flask(__name__)

# healthcheck, щоб не було 404 у логах
@flask_app.route("/", methods=["GET", "HEAD"])
def root():
    return "ok", 200

# -------------------------
# Telegram Application (PTB)
# -------------------------
bot_app = Application.builder().token(TOKEN).build()

def _buf(context):
    return context.user_data.setdefault("buffer", [])

def _kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Створити задачу", callback_data="new_task")],
        [InlineKeyboardButton("🧹 Очистити", callback_data="clear_buf")],
    ])

# Команди
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бот працює. Надішли текст, фото або голос — усе піде в чернетку.",
        reply_markup=_kb(),
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong ✅")

# Повідомлення
async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _buf(context).append(update.message.text)
    await update.message.reply_text("✅ Текст додано у чернетку.", reply_markup=_kb())

async def photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        file = await update.message.photo[-1].get_file()
        local_path = "photo.jpg"
        await file.download_to_drive(local_path)
        text = extract_text_from_image(local_path)
        _buf(context).append(text)
        await update.message.reply_text("🖼 Текст із фото додано.", reply_markup=_kb())
    except Exception as e:
        logger.exception("Помилка розпізнавання фото: %s", e)
        await update.message.reply_text("❌ Помилка розпізнавання фото.")

async def voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        file = await update.message.voice.get_file()
        local_path = "voice.ogg"
        await file.download_to_drive(local_path)
        text = transcribe_audio(local_path)
        _buf(context).append(text)
        await update.message.reply_text("🎤 Голос розпізнано й додано.", reply_markup=_kb())
    except Exception as e:
        logger.exception("Помилка розпізнавання голосу: %s", e)
        await update.message.reply_text("❌ Помилка розпізнавання голосу.")

# Кнопки
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
            logger.exception("Помилка запису у таблицю: %s", e)
            await q.message.reply_text("❌ Помилка запису у таблицю.")
        buf.clear()
        return

# -------------------------
# ГЛОБАЛЬНИЙ ASYNCIO LOOP (запускаємо у фоні)
# -------------------------
ASYNC_LOOP = asyncio.new_event_loop()

def _run_loop_forever(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

# -------------------------
# Flask webhook -> передаємо апдейт у глобальний loop
# -------------------------
@flask_app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, bot_app.bot)

        # Надсилаємо корутину в глобальний loop, який вже запущено у фоні
        fut = asyncio.run_coroutine_threadsafe(
            bot_app.process_update(update),
            ASYNC_LOOP
        )
        # (не чекаємо fut.result(), щоб не блокувати Flask)

    except Exception as e:
        logger.error("Webhook error", exc_info=e)

    return "ok"

# -------------------------
# Запуск
# -------------------------
def main():
    # Реєструємо хендлери
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("ping", ping))
    bot_app.add_handler(CallbackQueryHandler(buttons))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    bot_app.add_handler(MessageHandler(filters.PHOTO, photo_message))
    bot_app.add_handler(MessageHandler(filters.VOICE, voice_message))

    # 1) запускаємо глобальний asyncio loop у фоновому треді
    threading.Thread(target=_run_loop_forever, args=(ASYNC_LOOP,), daemon=True).start()

    # 2) ініціалізація/старт PTB у цьому ж loop
    asyncio.run_coroutine_threadsafe(bot_app.initialize(), ASYNC_LOOP).result()
    asyncio.run_coroutine_threadsafe(bot_app.start(), ASYNC_LOOP).result()

    # 3) встановлюємо webhook
    asyncio.run_coroutine_threadsafe(
        bot_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook"),
        ASYNC_LOOP
    ).result()

    logger.info("✅ PTB ініціалізовано і запущено; вебхук встановлено на %s/webhook", WEBHOOK_URL)

    # 4) запускаємо Flask (HTTP-сервер для Render)
    flask_app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
