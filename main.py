import os
import logging
import asyncio
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

# ---------- Логування ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------- Змінні середовища ----------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "10000"))

if not TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN не задано")
if not WEBHOOK_URL or not WEBHOOK_URL.startswith("https://"):
    raise SystemExit("WEBHOOK_URL не задано або не HTTPS (приклад: https://<name>.onrender.com)")

# ---------- Telegram Application ----------
bot_app = Application.builder().token(TOKEN).build()

# ---------- Допоміжне ----------
def _buf(context: ContextTypes.DEFAULT_TYPE) -> list:
    return context.user_data.setdefault("buffer", [])

def _kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Створити задачу", callback_data="new_task")],
        [InlineKeyboardButton("🧹 Очистити", callback_data="clear_buf")],
    ])

# ---------- Команди ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бот працює. Надішли текст, фото або голос. "
        "Усе піде в чернетку. Коли готово — натисни «Створити задачу».",
        reply_markup=_kb(),
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Бот онлайн")

# ---------- Повідомлення ----------
async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buf = _buf(context)
    text = (update.message.text or "").strip()
    if not text:
        return
    buf.append(text)
    await update.message.reply_text("✅ Текст додано у чернетку.", reply_markup=_kb())

async def photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buf = _buf(context)
    file = await update.message.photo[-1].get_file()
    local_path = "photo.jpg"
    await file.download_to_drive(local_path)
    try:
        # якщо extract_text_from_image блокуюча — перенести у пул
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, extract_text_from_image, local_path)
        text = (text or "").strip()
        if text:
            buf.append(text)
            await update.message.reply_text("🖼 Текст із фото додано.", reply_markup=_kb())
        else:
            await update.message.reply_text("😕 Текст на зображенні не знайдено.", reply_markup=_kb())
    except Exception as e:
        logger.exception("Помилка OCR: %s", e)
        await update.message.reply_text("❌ Помилка розпізнавання фото.")
    finally:
        try:
            os.remove(local_path)
        except Exception:
            pass

async def voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buf = _buf(context)
    file = await update.message.voice.get_file()
    local_path = "voice.ogg"
    await file.download_to_drive(local_path)
    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, transcribe_audio, local_path)
        text = (text or "").strip()
        if text:
            buf.append(text)
            await update.message.reply_text("🎤 Голос розпізнано й додано.", reply_markup=_kb())
        else:
            await update.message.reply_text("😕 Не вдалося розпізнати мову.", reply_markup=_kb())
    except Exception as e:
        logger.exception("Помилка STT: %s", e)
        await update.message.reply_text("❌ Помилка розпізнавання голосу.")
    finally:
        try:
            os.remove(local_path)
        except Exception:
            pass

# ---------- Кнопки ----------
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    buf = _buf(context)

    if data == "clear_buf":
        buf.clear()
        await q.message.reply_text("🧹 Чернетку очищено.", reply_markup=_kb())
        return

    if data == "new_task":
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

# ---------- Запуск ----------
def start_bot():
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("ping", ping))
    bot_app.add_handler(CallbackQueryHandler(buttons))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    bot_app.add_handler(MessageHandler(filters.PHOTO, photo_message))
    bot_app.add_handler(MessageHandler(filters.VOICE, voice_message))

    # Критично: шлях повинен збігатися з тим, що реєструємо у Telegram
    bot_app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{WEBHOOK_URL}/webhook",
        webhook_path="/webhook",          # ← це усуває 404
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    start_bot()

