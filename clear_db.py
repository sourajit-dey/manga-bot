import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    db_url = os.environ.get("DB_URL")
    db_name = os.environ.get("DB_NAME")
    client = AsyncIOMotorClient(db_url)
    await client[db_name].manga.drop()
    await client[db_name].chapters.drop()
    print("Collections dropped successfully.")

if __name__ == "__main__":
    asyncio.run(main())
