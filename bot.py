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

async def get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    if not context.args: return None
    arg = context.args[0]
    try:
        user_id = int(arg)
        member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
        return member.user
    except:
        if arg.startswith('@'):
            username = arg[1:].lower()
            try:
                async for member in context.bot.get_chat_members(update.effective_chat.id, limit=200):
                    if member.user.username and member.user.username.lower() == username:
                        return member.user
            except: pass
    return None

# ====================== MODERASYON KOMUTLARI ======================
async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    target = await get_target_user(update, context)
    if not target:
        await update.message.reply_text("❌ Hedef bulunamadı. Reply et veya @username / User ID yaz.")
        return
    count = await add_warning(update.effective_chat.id, target.id)
    await update.message.reply_text(f"⚠️ **{target.full_name}** uyarıldı! ({count}/3)", parse_mode=ParseMode.MARKDOWN)
    if count >= 3:
        until = datetime.utcnow() + timedelta(minutes=10)
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, 
                                              permissions=ChatPermissions(can_send_messages=False), until_date=until)
        await update.message.reply_text(f"🔇 **{target.full_name}** 3 uyarı nedeniyle 10 dakika mute edildi!")
        await log_action(context, f"🔇 Otomatik Mute\nKullanıcı: {target.full_name} ({target.id})")

async def unwarn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    target = await get_target_user(update, context)
    if not target: return
    count = await remove_warning(update.effective_chat.id, target.id)
    await update.message.reply_text(f"✅ **{target.full_name}** uyarısı azaltıldı. Güncel: {count}")
    await log_action(context, f"🔄 Unwarn\nKullanıcı: {target.full_name}")

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    target = await get_target_user(update, context)
    if not target: return
    await context.bot.ban_chat_member(update.effective_chat.id, target.id, revoke_messages=True)
    await update.message.reply_text(f"🚫 **{target.full_name}** banlandı.")
    await log_action(context, f"🚫 Ban\nKullanıcı: {target.full_name} ({target.id})")

async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    target = await get_target_user(update, context)
    if not target: return
    await context.bot.unban_chat_member(update.effective_chat.id, target.id, only_if_banned=True)
    await update.message.reply_text(f"✅ **{target.full_name}** unbanlandı.")

async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    target = await get_target_user(update, context)
    if not target: return
    minutes = int(context.args[1]) if len(context.args) > 1 else 30
    until = datetime.utcnow() + timedelta(minutes=minutes)
    await context.bot.restrict_chat_member(update.effective_chat.id, target.id, 
                                          permissions=ChatPermissions(can_send_messages=False), until_date=until)
    await update.message.reply_text(f"🔇 **{target.full_name}** {minutes} dakika mute edildi.")

async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    target = await get_target_user(update, context)
    if not target: return
    await context.bot.restrict_chat_member(update.effective_chat.id, target.id, 
                                          permissions=ChatPermissions(can_send_messages=True))
    await update.message.reply_text(f"🔊 **{target.full_name}** unmute edildi.")

# ====================== MÜZİK KOMUTU (Şarkı adı ile) ======================
async def music_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Kullanım: `/music Şarkı Adı Sanatçı`", parse_mode=ParseMode.MARKDOWN)
        return
    
    query = " ".join(context.args)
    msg = await update.message.reply_text(f"🎵 '{query}' aranıyor...")

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'temp_audio.%(ext)s',
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch1',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=True)
            filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp3'

        title = info.get('title', query)
        await msg.edit_text(f"✅ {title}\nGönderiliyor...")

        with open(filename, 'rb') as f:
            await update.message.reply_audio(audio=f, title=title, caption=f"🎵 {title}")

        if os.path.exists(filename):
            os.remove(filename)
    except Exception as e:
        await msg.edit_text(f"❌ İndirme hatası: {str(e)[:250]}")

# ====================== ADMIN PANEL ======================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): 
        await update.message.reply_text("❌ Sadece yöneticiler kullanabilir.")
        return
    keyboard = [
        [InlineKeyboardButton("🚫 Ban", callback_data="panel_ban"), 
         InlineKeyboardButton("🔇 Mute", callback_data="panel_mute")],
        [InlineKeyboardButton("⚠️ Warn", callback_data="panel_warn"), 
         InlineKeyboardButton("🔄 Unwarn", callback_data="panel_unwarn")]
    ]
    await update.message.reply_text("🛠 **Admin Paneli**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

def main():
    asyncio.run(init_db())
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN eksik!")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    # Komutlar
    app.add_handler(CommandHandler("start", lambda u,c: u.message.reply_text("🔐 Güvenlik Botu Aktif!\n\n/adminpanel\n/warn @user\n/music Şarkı Adı")))
    app.add_handler(CommandHandler("adminpanel", admin_panel))
    app.add_handler(CommandHandler("warn", warn_cmd))
    app.add_handler(CommandHandler("unwarn", unwarn_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("mute", mute_cmd))
    app.add_handler(CommandHandler("unmute", unmute_cmd))
    app.add_handler(CommandHandler("music", music_cmd))   # ← Türkçe karakter sorunu çözüldü

    print("🚀 Bot başarıyla başlatıldı!")
    app.run_polling()

if __name__ == "__main__":
    main()
