import os
import asyncio
import aiosqlite
import yt_dlp
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

DB_NAME = "warnings.db"

BAD_WORDS = ["amk", "aq", "orospu", "piç", "sik", "fuck", "shit", "bitch", "mal", "salak"]

# ====================== VERİTABANI ======================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                chat_id INTEGER,
                user_id INTEGER,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        await db.commit()

async def get_warnings(chat_id: int, user_id: int) -> int:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def add_warning(chat_id: int, user_id: int) -> int:
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO warnings (chat_id, user_id, count) VALUES (?, ?, 1)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1
        """, (chat_id, user_id))
        await db.commit()
        async with db.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id)) as cursor:
            row = await cursor.fetchone()
            return row[0]

async def remove_warning(chat_id: int, user_id: int) -> int:
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE warnings SET count = count - 1 WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        await db.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=? AND count <= 0", (chat_id, user_id))
        await db.commit()
        return await get_warnings(chat_id, user_id)

# ====================== YARDIMCI ======================
async def is_admin(update: Update) -> bool:
    if update.effective_chat.type == "private":
        return True
    try:
        member = await update.effective_chat.get_member(update.effective_user.id)
        return member.status in ["administrator", "creator"]
    except:
        return False

async def log_action(context, text: str):
    if LOG_CHANNEL_ID:
        try:
            await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=text, parse_mode=ParseMode.MARKDOWN)
        except:
            pass

async def get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Geliştirilmiş hedef kullanıcı bulma: Reply + User ID + @username"""
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user

    if not context.args:
        return None

    arg = context.args[0]
    try:
        # User ID
        user_id = int(arg)
        member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
        return member.user
    except ValueError:
        # @username
        if arg.startswith('@'):
            username = arg[1:].lower()
            # Gruptaki üyeleri tara (daha kapsamlı)
            try:
                async for member in context.bot.get_chat_members(update.effective_chat.id, limit=200):
                    if member.user.username and member.user.username.lower() == username:
                        return member.user
            except:
                pass
            await update.message.reply_text("❌ @username grupta bulunamadı veya bot göremiyor. Lütfen **reply** ederek dene.")
            return None
    return None

# ====================== 3 UYARI = 10 DK MUTE ======================
async def handle_warning(update: Update, context: ContextTypes.DEFAULT_TYPE, target, reason=""):
    if not target:
        return
    chat_id = update.effective_chat.id
    count = await add_warning(chat_id, target.id)
    await update.message.reply_text(
        f"⚠️ **{target.full_name}** uyarıldı!\nUyarı: **{count}/3**\nSebep: {reason or 'Belirtilmedi'}",
        parse_mode=ParseMode.MARKDOWN
    )
    if count >= 3:
        try:
            until = datetime.utcnow() + timedelta(minutes=10)
            await context.bot.restrict_chat_member(chat_id, target.id, permissions=ChatPermissions(can_send_messages=False), until_date=until)
            await update.message.reply_text(f"🔇 **{target.full_name}** 3 uyarı nedeniyle **10 dakika** susturuldu!")
            await log_action(context, f"🔇 Otomatik Mute (3 Warn)\nKullanıcı: {target.full_name} ({target.id})")
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, target.id))
                await db.commit()
        except Exception as e:
            await update.message.reply_text(f"Mute hatası: {str(e)}")

# ====================== YOUTUBE ======================
async def youtube_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ `/youtube https://youtu.be/xxx`", parse_mode=ParseMode.MARKDOWN)
        return
    url = context.args[0]
    msg = await update.message.reply_text("🎵 İndiriliyor...")

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'temp_audio.%(ext)s',
        'noplaylist': True,
        'quiet': True,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')

        title = info.get('title', 'Bilinmeyen')
        await msg.edit_text(f"✅ **{title}** indirildi.")

        with open(filename, 'rb') as audio:
            await update.message.reply_audio(audio=audio, title=title)

        if os.path.exists(filename):
            os.remove(filename)
    except Exception as e:
        await msg.edit_text(f"❌ Hata: {str(e)[:300]}")

# ====================== ADMIN PANELİ ======================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("❌ Sadece yöneticiler kullanabilir.")
        return
    keyboard = [
        [InlineKeyboardButton("🚫 Ban", callback_data="panel_ban"), InlineKeyboardButton("🔇 Mute", callback_data="panel_mute")],
        [InlineKeyboardButton("⚠️ Warn", callback_data="panel_warn"), InlineKeyboardButton("👢 Kick", callback_data="panel_kick")],
        [InlineKeyboardButton("✅ Unban", callback_data="panel_unban"), InlineKeyboardButton("🔊 Unmute", callback_data="panel_unmute")],
        [InlineKeyboardButton("🔄 Unwarn", callback_data="panel_unwarn")]
    ]
    await update.message.reply_text("🛠 **Admin Paneli**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Basit tutuyoruz, ileride genişletebiliriz
    await query.edit_message_text("Panelden işlem seçildi. Komutları reply veya @username ile kullanın.")

async def unwarn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    target = await get_target_user(update, context)
    if not target:
        await update.message.reply_text("❌ Hedef bulunamadı.")
        return
    count = await remove_warning(update.effective_chat.id, target.id)
    await update.message.reply_text(f"✅ **{target.full_name}** uyarısı azaltıldı. Güncel: {count}")

async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    target = await get_target_user(update, context)
    if not target:
        await update.message.reply_text("❌ Hedef bulunamadı. Reply et veya @username / User ID yaz.")
        return
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    await handle_warning(update, context, target, reason)

def main():
    asyncio.run(init_db())
    if not TOKEN:
        print("TOKEN eksik!")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", lambda u,c: u.message.reply_text("Bot aktif! /adminpanel dene.")))
    app.add_handler(CommandHandler("adminpanel", admin_panel))
    app.add_handler(CommandHandler("warn", warn_cmd))
    app.add_handler(CommandHandler("unwarn", unwarn_cmd))
    app.add_handler(CommandHandler("youtube", youtube_cmd))
    app.add_handler(CommandHandler("yt", youtube_cmd))

    app.add_handler(CallbackQueryHandler(button_handler))

    print("🚀 Bot çalışıyor - @username fix + Unwarn + Docker desteği")
    app.run_polling()

if __name__ == "__main__":
    main()
