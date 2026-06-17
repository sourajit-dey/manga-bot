import os
import asyncio
import logging
import pyrogram.utils
from dotenv import load_dotenv
from pyrogram import Client

# Patch Pyrogram to support newer 64-bit Telegram Channel IDs
pyrogram.utils.MIN_CHANNEL_ID = -10099999999999

# Load environment variables first
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import components after loading environment variables
from db.database import db
from health.server import start_server
from scraper.tasks import scraper_loop

# We let Pyrogram discover handlers via plugins

async def main():
    # Initialize DB
    await db.connect()
    
    # Initialize Pyrogram Client
    bot_token = os.environ.get("BOT_TOKEN")
    api_id = os.environ.get("API_ID")
    api_hash = os.environ.get("API_HASH")
    
    if not all([bot_token, api_id, api_hash]):
        logger.error("Missing Telegram API credentials.")
        return
        
    client = Client(
        "manga_bot",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,
        ipv6=False,
        plugins=dict(root="bot") # This registers all handlers in the bot/ folder
    )
    
    # Start health server
    await start_server()
    
    # Start bot
    logger.info("Starting Telegram Bot...")
    await client.start()
    
    from pyrogram.types import BotCommand
    await client.set_bot_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("random", "Get a random manga"),
        BotCommand("latest", "View recently added manga"),
        BotCommand("stats", "View bot statistics (Admin)"),
        BotCommand("setwelcome", "Set the welcome message (Admin)"),
        BotCommand("setimage", "Set the welcome image (Admin)"),
    ])
    
    # Start scraper loop as background task
    scraper_task = asyncio.create_task(scraper_loop(client))
    
    # Run indefinitely
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info("Shutting down...")
    finally:
        scraper_task.cancel()
        await client.stop()
        db.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
