import os
import asyncio
import aiosqlite
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.constants import ParseMode

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

DB_NAME = "warnings.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS warnings 
                            (chat_id INTEGER, user_id INTEGER, count INTEGER DEFAULT 0, 
                             PRIMARY KEY (chat_id, user_id))''')
        await db.commit()

async def get_warnings(chat_id, user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def add_warning(chat_id, user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""INSERT INTO warnings (chat_id, user_id, count) VALUES (?, ?, 1)
                            ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1""", (chat_id, user_id))
        await db.commit()
        return await get_warnings(chat_id, user_id)

async def remove_warning(chat_id, user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE warnings SET count = count - 1 WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        await db.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=? AND count <= 0", (chat_id, user_id))
        await db.commit()
        return await get_warnings(chat_id, user_id)

async def is_admin(update: Update):
    if update.effective_chat.type == "private": return True
    try:
        member = await update.effective_chat.get_member(update.effective_user.id)
        return member.status in ["administrator", "creator"]
    except: return False

async def log_action(context, text):
    if LOG_CHANNEL_ID:
        try: 
            await context.bot.send_message(LOG_CHANNEL_ID, text, parse_mode=ParseMode.MARKDOWN)
        except: pass

# ====================== HEDEF KULLANICI BULMA ======================
async def get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    if context.args:
        try:
            user_id = int(context.args[0])
            member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
            return member
