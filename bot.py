import os
import random
import asyncio
import aiosqlite
import yt_dlp
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

DB_NAME = "warnings.db"

BAD_WORDS = ["amk", "aq", "orospu", "piç", "sik", "fuck", "shit", "bitch", "mal", "salak"]

FLOOD_LIMIT = 8
FLOOD_TIME_WINDOW = 10
user_message_times = {}

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
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    if context.args:
        arg = context.args[0]
        try:
            user_id = int(arg)
            member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
            return member.user
        except:
            if arg.startswith('@'):
                username = arg[1:].lower()
                try:
                    admins = await context.bot.get_chat_administrators(update.effective_chat.id)
                    for m in admins:
                        if m.user.username and m.user.username.lower() == username:
                            return m.user
                except:
                    pass
    return None

# ====================== 3 UYARI = MUTE ======================
async def handle_warning(update: Update, context: ContextTypes.DEFAULT_TYPE, target, reason=""):
    chat_id = update.effective_chat.id
    count = await add_warning(chat_id, target.id)
    await update.message.reply_text(
        f"⚠️ **{target.full_name}** uyarıldı!\nUyarı sayısı: **{count}/3**\nSebep: {reason or 'Belirtilmedi'}",
        parse_mode=ParseMode.MARKDOWN
    )

    if count >= 3:
        try:
            until = datetime.utcnow() + timedelta(minutes=10)
            await context.bot.restrict_chat_member(
                chat_id, target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until
            )
            await update.message.reply_text(f"🔇 **{target.full_name}** 3 uyarı nedeniyle **10 dakika** susturuldu!")
            await log_action(context, f"🔇 Otomatik Mute (3 Warn)\nKullanıcı: {target.full_name} ({target.id})")
            # Uyarı sayısını sıfırla
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, target.id))
                await db.commit()
        except Exception as e:
            await update.message.reply_text(f"Mute hatası: {str(e)}")

# ====================== YOUTUBE İNDİRME ======================
async def youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Lütfen YouTube linki gönder:\n`/youtube https://youtu.be/xxx`", parse_mode=ParseMode.MARKDOWN)
        return

    url = context.args[0]
    if "youtube.com" not in url and "youtu.be" not in url:
        await update.message.reply_text("❌ Geçerli bir YouTube linki girin.")
        return

    msg = await update.message.reply_text("🎵 YouTube ses indiriliyor, lütfen bekleyin...")

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'temp_audio.%(ext)s',
        'noplaylist': True,
        'quiet': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')

        title = info.get('title', 'Bilinmeyen Şarkı')
        await msg.edit_text(f"✅ İndirme tamamlandı: **{title}**\nGönderiliyor...", parse_mode=ParseMode.MARKDOWN)

        with open(filename, 'rb') as audio:
            await update.message.reply_audio(audio=audio, title=title, caption=f"🎵 {title}\nİndiren: @{update.effective_user.username or 'anon'}")

        # Temizle
        if os.path.exists(filename):
            os.remove(filename)

        await log_action(context, f"🎵 YouTube İndirme\nBaşlık: {title}\nKullanıcı: {update.effective_user.full_name}")

    except Exception as e:
        await msg.edit_text(f"❌ Hata oluştu: {str(e)[:200]}")

# ====================== ADMIN PANELİ ve DİĞER KOMUTLAR ======================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("❌ Sadece yöneticiler kullanabilir.")
        return
    # ... (önceki admin paneli kodunu buraya ekleyebilirsin, yer kazanmak için kısa tuttum)

async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    target = await get_target_user(update, context)
    if not target:
        await update.message.reply_text("❌ Hedef kullanıcı bulunamadı (reply, @username veya User ID kullan).")
        return
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    await handle_warning(update, context, target, reason)

# Diğer komutlar (ban, mute, start vb.) önceki versiyondan aynı kalabilir.

def main():
    asyncio.run(init_db())
    if not TOKEN:
        print("TOKEN eksik!")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Bot çalışıyor! /adminpanel ve /youtube dene.")))
    app.add_handler(CommandHandler("adminpanel", admin_panel))
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("youtube", youtube))
    app.add_handler(CommandHandler("yt", youtube))

    # Kötü kelime ve flood handler'larını da ekle (önceki kodlardan)

    print("🚀 Bot çalışıyor → 3 Warn = 10dk Mute + YouTube Ses İndirme aktif!")
    app.run_polling()

if __name__ == "__main__":
    main()
