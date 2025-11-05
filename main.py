import os
import logging
import asyncio
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# === Твої модулі ===
# transcribe_audio: використовує Google Cloud Speech
# extract_text_from_image: використовує Google Cloud Vision
from ai import transcribe_audio, extract_text_from_image
from sheets_api import append_task

# -----------------------
# Налаштування логування
# -----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# -----------------------
# Змінні середовища
# -----------------------
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise SystemExit("❌ TELEGRAM_BOT_TOKEN не знайдено у змінних середовища")

# -----------------------
# Flask + Telegram app
# -----------------------
app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

# -----------------------
# Допоміжні: чернетка + кнопки
# -----------------------
def _buf(context: ContextTypes.DEFAULT_TYPE) -> list:
    """Повертає список-чернетку для поточного користувача."""
    return context.user_data.setdefault("buffer", [])

def _kb() -> InlineKeyboardMarkup:
    """Кнопки під повідомленням."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Створити задачу", callback_data="new_task")],
        [InlineKeyboardButton("🧹 Очистити чернетку", callback_data="clear_buf")],
    ])

# -----------------------
# Команди
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привіт! Надсилай текст / голос / фото — я збиратиму їх у чернетку.\n"
        "Коли будеш готовий — натисни кнопку нижче, щоб створити одну задачу.",
        reply_markup=_kb()
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Бот працює!")

# -----------------------
# Текст
# -----------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return
    _buf(context).append(text)
    await update.message.reply_text(
        "💾 Додано до чернетки. Коли завершиш — натисни кнопку.",
        reply_markup=_kb()
    )

# -----------------------
# Голос / Аудіо → Google STT
# -----------------------
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("🎙️ Отримано голос/аудіо")
    voice_or_audio = update.message.voice or update.message.audio
    if not voice_or_audio:
        await update.message.reply_text("⚠️ Не вдалося отримати аудіофайл.", reply_markup=_kb())
        return

    # Завантажуємо файл локально
    tg_file = await voice_or_audio.get_file()
    tmp_path = "voice_input.ogg"
    await tg_file.download_to_drive(tmp_path)

    try:
        # Щоб не блокувати цикл подій — виконуємо транскрипцію у пулі
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, transcribe_audio, tmp_path)
        text = (text or "").strip()

        if text:
            _buf(context).append(text)
            await update.message.reply_text(f"🧠 Розпізнано текст:\n\n{text}", reply_markup=_kb())
        else:
            await update.message.reply_text("😕 Не вдалося розпізнати мову в аудіо.", reply_markup=_kb())
    except Exception as e:
        logger.exception("Помилка розпізнавання аудіо")
        await update.message.reply_text(f"❌ Помилка розпізнавання аудіо: {e}", reply_markup=_kb())
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

# -----------------------
# Фото → Google Vision OCR
# -----------------------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("📸 Отримано зображення")
    if not update.message.photo:
        await update.message.reply_text("⚠️ Зображення не знайдено.", reply_markup=_kb())
        return

    tg_file = await update.message.photo[-1].get_file()
    tmp_path = "photo_input.jpg"
    await tg_file.download_to_drive(tmp_path)

    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, extract_text_from_image, tmp_path)
        text = (text or "").strip()

        if text:
            _buf(context).append(text)
            await update.message.reply_text(f"📄 Розпізнаний текст:\n\n{text}", reply_markup=_kb())
        else:
            await update.message.reply_text("😕 Текст на зображенні не знайдено.", reply_markup=_kb())
    except Exception as e:
        logger.exception("Помилка OCR")
        await update.message.reply_text(f"❌ Помилка OCR: {e}", reply_markup=_kb())
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

# -----------------------
# Кнопки
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
            await q.edit_message_text("⚠️ Чернетка порожня. Спочатку надішли повідомлення.")
            return

        description = "\n".join(buf)
        try:
            # запис у Google Sheets
            append_task(name="Задача", description=description, tag="#інше")
            await q.edit_message_text("✅ Створено одну задачу з усіх повідомлень.")
        except Exception:
            logger.exception("Помилка запису в Sheets")
            await q.edit_message_text("❌ Помилка збереження у таблицю.")
        finally:
            buf.clear()

# -----------------------
# Реєстрація обробників
# -----------------------
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("ping", ping))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
application.add_handler(CallbackQueryHandler(buttons))

# -----------------------
# Flask маршрути
# -----------------------
@app.route("/")
def home():
    return "Бот працює ✅"

@app.route("/webhook", methods=["POST"])
def webhook():
    """Отримує оновлення від Telegram і кладе їх у чергу бота."""
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        application.update_queue.put_nowait(update)
        return "ok", 200
    except Exception as e:
        logger.exception(f"Помилка у webhook: {e}")
        return "error", 500

# -----------------------
# Запуск: Flask + бот
# -----------------------
if __name__ == "__main__":
    async def run_bot():
        # ВАЖЛИВО: запускаємо Application, щоб він обробляв чергу
        await application.initialize()
        await application.start()
        logger.info("✅ Telegram application started (webhook mode)")

    # Фонова задача з ботом
    asyncio.get_event_loop().create_task(run_bot())

    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Запуск Flask на порті {port}")
    app.run(host="0.0.0.0", port=port)
# 🧩 Додатково: запуск Telegram-бота окремим циклом
if __name__ == "__main__":
    import threading

    def start_bot():
        asyncio.run(run_bot())

    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()

    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Запуск Flask на порті {port}")
    app.run(host="0.0.0.0", port=port)
