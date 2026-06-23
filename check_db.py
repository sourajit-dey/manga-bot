import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

async def run():
    client = AsyncIOMotorClient(os.environ.get('DB_URL', 'mongodb://localhost:27017'))
    db_name = os.environ.get('DB_NAME', 'manga_bot')
    db = client[db_name]
    mangas = await db.manga.find({"priority": 1}).to_list(None)
    print("=== Priority Mangas ===")
    for m in mangas:
        print(f"- {m['title']} (offset: {m.get('chapter_offset', 0)})")
        
    print("\n=== Non-Priority Mangas ===")
    non_p = await db.manga.find({"priority": {"$ne": 1}}).to_list(None)
    for m in non_p:
        print(f"- {m['title']} (offset: {m.get('chapter_offset', 0)})")

if __name__ == "__main__":
    asyncio.run(run())
