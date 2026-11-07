import os
import sys
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command

# Configure logging
logging.basicConfig(level=logging.INFO)

# Fetch configuration from Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID")

if not BOT_TOKEN or not ADMIN_GROUP_ID:
    sys.exit("Error: BOT_TOKEN or ADMIN_GROUP_ID environment variable is missing!")

ADMIN_GROUP_ID = int(ADMIN_GROUP_ID)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
DB_NAME = "bot_data.db"

# --- Database Setup ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS message_map (
                admin_msg_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                user_msg_id INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id INTEGER PRIMARY KEY
            )
        """)
        await db.commit()

async def is_banned(user_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,)) as cur:
            return await cur.fetchone() is not None

# --- User Handlers ---
@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message):
    if await is_banned(message.from_user.id):
        return

    text = (
        "👋 **Welcome to the Collaboration & Promotion Desk!**\n\n"
        "To discuss a proposal, please reply directly with:\n"
        "1️⃣ Your Channel link & current subscriber count\n"
        "2️⃣ Type of promotion (Paid Ad / Cross-Promo / Exchange)\n\n"
        "Drop your details below and we'll reply right here."
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.chat.type == "private")
async def user_relay_handler(message: Message):
    user = message.from_user
    if await is_banned(user.id):
        return

    # Construct the sender info header
    username_str = f"@{user.username}" if user.username else "No username"
    header = (
        f"📩 **New Inquiry**\n"
        f"👤 **From:** {user.full_name} ({username_str})\n"
        f"🆔 **User ID:** `{user.id}`\n"
        f"────────────────────\n"
    )

    # If it's pure text, attach the header
    if message.text:
        sent = await bot.send_message(
            chat_id=ADMIN_GROUP_ID,
            text=f"{header}{message.text}",
            parse_mode="Markdown"
        )
    else:
        # For media (photo, voice, document, etc.), forward it with the info header
        await bot.send_message(chat_id=ADMIN_GROUP_ID, text=header, parse_mode="Markdown")
        sent = await message.copy_to(chat_id=ADMIN_GROUP_ID)

    # Save mapping so admin replies route back to this user
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO message_map (admin_msg_id, user_id, user_msg_id) VALUES (?, ?, ?)",
            (sent.message_id, user.id, message.message_id)
        )
        await db.commit()

# --- Admin Handlers (Inside Admin Group) ---
@dp.message(F.chat.id == ADMIN_GROUP_ID, F.reply_to_message)
async def admin_reply_handler(message: Message):
    reply_to_id = message.reply_to_message.message_id

    # Find the target user from the database
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, user_msg_id FROM message_map WHERE admin_msg_id = ?",
            (reply_to_id,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        return

    target_user_id, target_msg_id = row

    # Handle Admin /ban command
    if message.text and message.text.strip().lower() == "/ban":
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (target_user_id,))
            await db.commit()
        await message.reply(f"🚫 User `{target_user_id}` has been banned.")
        return

    # Handle Admin /unban command
    if message.text and message.text.strip().lower() == "/unban":
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("DELETE FROM banned_users WHERE user_id = ?", (target_user_id,))
            await db.commit()
        await message.reply(f"✅ User `{target_user_id}` has been unbanned.")
        return

    # Relay admin message back to user (User only sees the bot sending it)
    try:
        await message.copy_to(chat_id=target_user_id)
    except Exception as e:
        await message.reply(f"⚠️ Failed to deliver message to user: {e}")

# --- Startup ---
async def main():
    await init_db()
    # Delete pending updates to avoid backlog bursts on startup
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
