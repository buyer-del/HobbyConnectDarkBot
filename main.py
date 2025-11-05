import logging
import os
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from sheets_api import append_task
from ai import transcribe_audio, extract_text_from_image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise SystemExit("❌ TELEGRAM_BOT_TOKEN не знайдено!")

app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

def _buf(context: ContextTypes.DEFAULT_TYPE) -> list:
    return context.user_data.setdefault("buffer", [])

def _kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Створити задачу", callback_data="new_task")],
        [InlineKeyboardButton("🧹 Очистити чернетку", callback_data="clear_buf")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привіт! Надсилай текст / голос / фото — я збиратиму їх у чернетку.\n"
        "Коли будеш готовий — натисни кнопку нижче, щоб створити задачу.",
        reply_markup=_kb()
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Бот працює!")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text:
        _buf(context).append(text)
        await update.message.reply_text(
            "💾 Додано до чернетки.",
            reply_markup=_kb()
        )

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("ping", ping))
application.add_handler(MessageHandler(filters.TEXT, handle_text))

@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put_nowait(update)
    return "ok", 200

@app.route("/")
def home():
    return "Бот працює ✅"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
