import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pyrogram import Client
from config import BOT_TOKEN, API_ID, API_HASH, SESSIONS_DIR
import database as db
import handlers.user as user_handler
import handlers.buy as buy_handler
import handlers.owner as owner_handler
import handlers.payments as payments_handler

os.makedirs(SESSIONS_DIR, exist_ok=True)

async def main():
    app = Client(
        "tg_store_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        workdir=SESSIONS_DIR,
    )

    owner_handler.register(app)
    payments_handler.register(app)
    buy_handler.register(app)
    user_handler.register(app)

    await db.init_db()
    async with app:
        print("🤖 TG Account Store Bot is running...")
        await asyncio.Event().wait()


if __name__ == "__main__":
    print("🚀 Starting TG Account Store Bot...")
    asyncio.run(main())
