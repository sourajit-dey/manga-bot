import asyncio
import os
from pyrogram import Client
from dotenv import load_dotenv

load_dotenv()

import pyrogram.utils
pyrogram.utils.MIN_CHANNEL_ID = -10099999999999

app = Client(
    "manga_bot_test",
    api_id=os.environ.get("API_ID"),
    api_hash=os.environ.get("API_HASH"),
    bot_token=os.environ.get("BOT_TOKEN")
)

async def main():
    async with app:
        channel_id_str = os.environ.get("STORAGE_CHANNEL_ID")
        try:
            channel_id = int(channel_id_str)
            await app.send_message(channel_id, "Test message from bot to verify permissions.")
            print("Message sent successfully!")
        except Exception as e:
            import traceback
            print(f"Failed to send message: {type(e).__name__} - {e}")
            traceback.print_exc()

app.run(main())
