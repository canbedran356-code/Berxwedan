import os
import random
import string
import asyncio
import aiosqlite
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.constants import ParseMode
from telegram.error import TelegramError

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")   # Opsiyonel: -1001234567890 formatında

DB_NAME = "warnings.db"

BAD_WORDS = ["amk", "aq", "orospu", "piç", "sik", "fuck", "shit", "bitch", "mal", "salak"]

FLOOD_LIMIT = 8
FLOOD_TIME_WINDOW = 10
user_message_times = {}

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

# ====================== KOMUTLAR ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔐 **Gelişmiş Güvenlik & Moderasyon Botu**\n\n"
        "Komutlar (mesaja **reply** ederek kullanın):\n"
        "`/ban` `/unban` `/kick` `/mute [dakika]` `/unmute`\n"
        "`/warn [sebep]` `/unwarn` `/warnings`\n\n"
        "Botu gruba ekleyip **Admin** yapmayı unutma!",
        parse_mode=ParseMode.MARKDOWN
    )

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): 
        await update.message.reply_text("❌ Sadece yöneticiler kullanabilir.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Bir mesaja reply edin.")
        return
    target = update.message.reply_to_message.from_user
    reason = " ".join(context.args) or "Belirtilmedi"
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id, revoke_messages=True)
        await update.message.reply_text(f"🚫 **{target.full_name}** banlandı.\nSebep: {reason}", parse_mode=ParseMode.MARKDOWN)
        await log_action(context, f"🔨 **Ban**\nGrup: {update.effective_chat.title}\nKullanıcı: {target.full_name} ({target.id})\nSebep: {reason}")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {str(e)}")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Bir mesaja reply edin.")
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target.id, only_if_banned=True)
        await update.message.reply_text(f"✅ **{target.full_name}** banı kaldırıldı.")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {str(e)}")

async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Bir mesaja reply edin.")
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"👢 **{target.full_name}** gruptan atıldı.")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {str(e)}")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Bir mesaja reply edin.")
        return
    target = update.message.reply_to_message.from_user
    minutes = 30
    if context.args:
        try: minutes = int(context.args[0])
        except: pass
    until = datetime.utcnow() + timedelta(minutes=minutes)
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
        await update.message.reply_text(f"🔇 **{target.full_name}** {minutes} dakika susturuldu.", parse_mode=ParseMode.MARKDOWN)
        await log_action(context, f"🔇 Mute\nKullanıcı: {target.full_name}\nSüre: {minutes} dk")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {str(e)}")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Bir mesaja reply edin.")
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=True, can_send_photos=True, can_send_videos=True)
        )
        await update.message.reply_text(f"🔊 **{target.full_name}** susturulması kaldırıldı.")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {str(e)}")

async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Bir mesaja reply edin.")
        return
    target = update.message.reply_to_message.from_user
    reason = " ".join(context.args) or "Belirtilmedi"
    count = await add_warning(update.effective_chat.id, target.id)
    await update.message.reply_text(f"⚠️ **{target.full_name}** uyarıldı!\nUyarı: **{count}/3**\nSebep: {reason}", parse_mode=ParseMode.MARKDOWN)
    if count >= 3:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id, revoke_messages=True)
        await update.message.reply_text(f"🚫 {target.full_name} 3 uyarı nedeniyle banlandı!")
        await log_action(context, f"🚫 Otomatik Ban (3 Warn)\nKullanıcı: {target.full_name}")

async def unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Bir mesaja reply edin.")
        return
    target = update.message.reply_to_message.from_user
    count = await remove_warning(update.effective_chat.id, target.id)
    await update.message.reply_text(f"✅ **{target.full_name}** uyarısı azaltıldı. Güncel: {count}")

async def warnings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Bir mesaja reply edin.")
        return
    target = update.message.reply_to_message.from_user
    count = await get_warnings(update.effective_chat.id, target.id)
    await update.message.reply_text(f"📊 **{target.full_name}** → **{count}** uyarı")

# ====================== MESAJ İŞLEME ======================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.lower()

    # Kötü kelime filtresi
    if any(bad in text for bad in BAD_WORDS):
        try:
            await update.message.delete()
            count = await add_warning(chat_id, user_id)
            await update.message.reply_text(f"⚠️ Küfür tespit edildi! Uyarı: {count}/3")
            if count >= 3:
                await context.bot.ban_chat_member(chat_id, user_id)
                await update.message.reply_text("🚫 3 uyarı nedeniyle banlandı!")
        except: pass
        return

    # Anti-Flood
    now = datetime.utcnow().timestamp()
    if chat_id not in user_message_times: user_message_times[chat_id] = {}
    if user_id not in user_message_times[chat_id]: user_message_times[chat_id][user_id] = []
    times = user_message_times[chat_id][user_id]
    times.append(now)
    times[:] = [t for t in times if now - t < FLOOD_TIME_WINDOW]
    if len(times) > FLOOD_LIMIT:
        try:
            await update.message.delete()
            await context.bot.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions(can_send_messages=False), until_date=datetime.utcnow() + timedelta(minutes=10))
            await update.message.reply_text(f"🚫 Flood tespit edildi! 10 dakika mute.")
        except: pass

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.is_bot: continue
        await update.message.reply_text(
            f"👋 Hoş geldin **{member.full_name}**!\n"
            "Lütfen grup kurallarına uyunuz. Sorun yaşarsanız yöneticilere bildirin.",
            parse_mode=ParseMode.MARKDOWN
        )

def main():
    asyncio.run(init_db())
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN environment variable eksik!")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    # Komutlar
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("kick", kick))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("unwarn", unwarn))
    app.add_handler(CommandHandler("warnings", warnings_cmd))

    # Mesajlar
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))

    print("🚀 Bot başlatılıyor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
