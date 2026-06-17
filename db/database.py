import os
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import IndexModel, ASCENDING, TEXT

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.client = None
        self.db = None
        self.manga = None
        self.chapters = None
        self.state = None

    async def connect(self):
        db_url = os.environ.get("DB_URL")
        db_name = os.environ.get("DB_NAME", "manga_bot")
        if not db_url:
            raise ValueError("DB_URL environment variable is not set")
            
        self.client = AsyncIOMotorClient(db_url)
        self.db = self.client[db_name]
        self.manga = self.db.manga
        self.chapters = self.db.chapters
        self.state = self.db.state
        logger.info("Connected to MongoDB")
        await self.setup_indexes()

    async def setup_indexes(self):
        # Manga indexes
        manga_indexes = [
            IndexModel([("title", TEXT)], name="title_text_index"),
        ]
        await self.manga.create_indexes(manga_indexes)
        
        # Chapters indexes
        chapter_indexes = [
            IndexModel([("manga_id", ASCENDING)]),
            IndexModel([("manga_id", ASCENDING), ("chapter_number", ASCENDING)], unique=True)
        ]
        try:
            await self.chapters.create_indexes(chapter_indexes)
        except Exception as e:
            logger.warning(f"Could not create chapter indexes (might already exist): {e}")
        logger.info("Database indexes setup completed")

    def close(self):
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")

# Global instance
db = Database()
