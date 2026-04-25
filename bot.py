import os
import asyncio
import aiosqlite
import re
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, 
    ChatMemberHandler, CallbackQueryHandler, MessageHandler, filters
)
from telegram.constants import ParseMode

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

DB_NAME = "warnings.db"

# ====================== AYARLAR ======================
BAD_WORDS = [
    "amk", "aq", "orospu", "pic", "sik", "yarrak", "fuck", "shit", "bitch",
    "mal", "gerizekali", "salak", "aptal", "anani", "annesini", "amina", "siktir"
]

LINK_REGEX = re.compile(r'http[s]?://|t\.me/|telegram\.me/|www\.')

# ====================== VERİTABANI ======================
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

# ====================== YARDIMCI ======================
async def is_admin(update: Update):
    if update.effective_chat.type == "private":
        return True
    try:
        member = await update.effective_chat.get_member(update.effective_user.id)
        return member.status in ["administrator", "creator"]
    except:
        return False

async def log_action(context: ContextTypes.DEFAULT_TYPE, text: str):
    if LOG_CHANNEL_ID:
        try:
            await context.bot.send_message(LOG_CHANNEL_ID, text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

async def get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    if context.args:
        try:
            user_id = int(context.args[0])
            member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
            return member.user
        except:
            if update.message:
                await update.message.reply_text("❌ Geçersiz User ID veya kullanıcı grupta değil.")
            return None
    return None

# ====================== BUTON HANDLER ======================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "welcome_greet":
        await query.edit_message_text(
            text=f"👋 Berxwedan! {query.from_user.first_name} hoş geldin kardeşim 🔥\nGrubumuza katıldığın için mutluyuz ❤️",
            parse_mode=ParseMode.MARKDOWN
        )

# ====================== HOŞGELDİN & GÜLE GÜLE ======================
async def greet_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member

    if result.new_chat_member.status == "member" and result.old_chat_member.status in ["left", "kicked"]:
        user = result.new_chat_member.user
        chat = result.chat

        keyboard = [
            [InlineKeyboardButton("📜 Kuralları Oku", url="https://t.me/berxwedangrubu/123")],  
            [InlineKeyboardButton("👋 Selam Ver", callback_data="welcome_greet")]
        ]

        welcome_text = (
            f"🔥 **Berxwedan!**\n\n"
            f"👋 Hoş geldin **{user.full_name}**!\n"
            f"Gruba katıldığın için teşekkürler ❤️\n\n"
            f"📜 Kurallara uy ve keyfini çıkar!"
        )

        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=welcome_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            await log_action(context, f"Hoşgeldin: [{user.full_name}](tg://user?id={user.id}) gruba katıldı.")
        except Exception as e:
            print(f"Hoşgeldin hatası: {e}")

    elif result.new_chat_member.status in ["left", "kicked"] and result.old_chat_member.status == "member":
        user = result.new_chat_member.user
        chat = result.chat
        goodbye_text = f"😔 **Güle güle...** 👋\n\n**{user.full_name}** gruptan ayrıldı.\nBerxwedan seni özleyecek!"

        try
