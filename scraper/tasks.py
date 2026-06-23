import os
import asyncio
import logging
import io
import tempfile
import img2pdf
import aiohttp
from datetime import datetime
from PIL import Image

from pyrogram.types import InputMediaDocument
from scraper.mangadex import mangadex
from scraper.anilist import fetch_anilist_cover
from db.database import db

logger = logging.getLogger(__name__)

async def process_manga_metadata(manga_data):
    """Extract metadata and insert into DB if not exists."""
    m_id = manga_data["id"]
    attributes = manga_data["attributes"]
    
    # Get title (default to English, fallback to first available)
    main_title = attributes["title"].get("en")
    
    alt_titles = []
    english_alt = None
    for alt in attributes["altTitles"]:
        for lang, t in alt.items():
            alt_titles.append(t)
            if lang == "en":
                english_alt = t
                
    if not english_alt and not main_title:
        if attributes["title"]:
            main_title = list(attributes["title"].values())[0]

    # Prefer true localized English title if available
    title = english_alt if english_alt else main_title
        
    description = attributes["description"].get("en", "")
    
    genres = []
    for tag in attributes["tags"]:
        if "name" in tag["attributes"]:
            genres.append(tag["attributes"]["name"].get("en"))
            
    cover_url = await fetch_anilist_cover(title)
    if not cover_url:
        english_cover = await mangadex.fetch_english_cover(m_id)
        if english_cover:
            cover_url = f"https://uploads.mangadex.org/covers/{m_id}/{english_cover}"
        else:
            for rel in manga_data["relationships"]:
                if rel["type"] == "cover_art":
                    file_name = rel.get("attributes", {}).get("fileName")
                    if file_name:
                        cover_url = f"https://uploads.mangadex.org/covers/{m_id}/{file_name}"
                
    manga_doc = {
        "manga_id": m_id,
        "title": title,
        "alt_titles": alt_titles,
        "genres": [g for g in genres if g],
        "description": description,
        "cover_url": cover_url,
        "source": "mangadex",
        "added_date": datetime.utcnow()
    }
    
    # Insert if not exists
    existing = await db.manga.find_one({"manga_id": m_id})
    if not existing:
        await db.manga.insert_one(manga_doc)
        logger.info(f"Added new manga: {title}")
        return manga_doc, True
    return existing, False

async def process_chapter(client, storage_channel_id, manga_doc, chapter_data):
    """Download chapter pages, create PDF using temp files to save RAM, upload, and save to DB."""
    c_id = chapter_data["id"]
    attributes = chapter_data["attributes"]
    chapter_number = attributes.get("chapter", "0")
    title = attributes.get("title", f"Chapter {chapter_number}")
    
    existing = await db.chapters.find_one({"manga_id": manga_doc["manga_id"], "chapter_number": chapter_number})
    if existing:
        return False
        
    logger.info(f"Processing chapter {chapter_number} of {manga_doc['title']}")
    
    try:
        pages_resp = await mangadex._request("GET", f"/at-home/server/{c_id}")
        if not pages_resp or "baseUrl" not in pages_resp:
            return False
            
        base_url = pages_resp["baseUrl"]
        chapter_hash = pages_resp["chapter"]["hash"]
        pages = pages_resp["chapter"]["data"]
        
        if not pages:
            logger.warning(f"No pages found for chapter {c_id}")
            return False
            
        with tempfile.TemporaryDirectory() as temp_dir:
            image_paths = []
            
            async with aiohttp.ClientSession() as session:
                for idx, page in enumerate(pages):
                    url = f"{base_url}/data/{chapter_hash}/{page}"
                    try:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                file_path = os.path.join(temp_dir, f"page_{idx:03d}.jpg")
                                with open(file_path, "wb") as f:
                                    f.write(await resp.read())
                                image_paths.append(file_path)
                    except Exception as e:
                        logger.error(f"Error processing image {url}: {e}")
                    await asyncio.sleep(0.5) # Be nice to the image server
            
            if not image_paths:
                logger.warning(f"No valid images for chapter {c_id}")
                return False

            # Create PDF from file paths (highly memory efficient)
            
            # Sanitize file name for file system
            safe_title = "".join([c for c in manga_doc['title'] if c.isalpha() or c.isdigit() or c==' ']).rstrip()
            file_name = f"{safe_title} - Chapter {chapter_number}.pdf"
            
            pdf_path = os.path.join(temp_dir, file_name)
            with open(pdf_path, "wb") as f:
                f.write(img2pdf.convert(image_paths))
            
            # Upload to Telegram
            logger.info(f"Uploading {file_name} to storage channel")
            message = await asyncio.wait_for(
                client.send_document(
                    chat_id=storage_channel_id,
                    document=pdf_path,
                    caption=f"**{manga_doc['title']}**\nChapter: {chapter_number}\nTitle: {title}"
                ),
                timeout=300 # 5 minutes maximum timeout
            )
            
            logger.info(f"Successfully uploaded {file_name}")
            await asyncio.sleep(5)
            
        # Save to DB
        chapter_doc = {
            "manga_id": manga_doc["manga_id"],
            "chapter_number": chapter_number,
            "telegram_message_id": message.id,
            "file_type": "pdf",
            "added_date": datetime.utcnow()
        }
        await db.chapters.insert_one(chapter_doc)
        logger.info(f"Successfully processed and stored chapter {chapter_number}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to process chapter {c_id}: {e}")
    return False

async def notify_news_channel(client, manga_doc):
    news_channel_id = os.environ.get("NEWS_CHANNEL_ID")
    if not news_channel_id:
        return
    try:
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        me = await client.get_me()
        bot_username = me.username
        
        news_channel_id = int(news_channel_id)
        desc = manga_doc['description'][:150] + "..." if len(manga_doc['description']) > 150 else manga_doc['description']
        text = f"🆕 **New Manga Added!**\n\n📖 **{manga_doc['title']}**\n\n{desc}"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 Read Now", url=f"https://t.me/{bot_username}?start=manga_{manga_doc['manga_id']}")]
        ])
        
        if manga_doc.get("cover_url"):
            async with aiohttp.ClientSession() as session:
                async with session.get(manga_doc["cover_url"]) as resp:
                    if resp.status == 200:
                        img_bytes = await resp.read()
                        bio = io.BytesIO(img_bytes)
                        bio.name = "cover.jpg"
                        await client.send_photo(news_channel_id, photo=bio, caption=text, reply_markup=keyboard)
                    else:
                        await client.send_message(news_channel_id, text, reply_markup=keyboard)
        else:
            await client.send_message(news_channel_id, text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Failed to notify news channel: {e}")

async def scraper_loop(client):
    interval = int(os.environ.get("CHECK_INTERVAL", 300))
    storage_channel_id = int(os.environ.get("STORAGE_CHANNEL_ID"))
    await asyncio.sleep(5)

    while True:
        try:
            # 0. Check for Priority Chapters (Exact chapter fetching)
            priority_chapter = await db.priority_chapters.find_one_and_delete({})
            if priority_chapter:
                manga_id = priority_chapter["manga_id"]
                chapter_number = priority_chapter["chapter_number"]
                manga_doc = await db.manga.find_one({"manga_id": manga_id})
                if manga_doc:
                    logger.info(f"Fetching specific priority chapter {chapter_number} for {manga_doc['title']}")
                    chapters_resp = await mangadex.fetch_manga_chapters(manga_id, limit=500)
                    if chapters_resp and chapters_resp.get("data"):
                        for c_data in chapters_resp["data"]:
                            if str(c_data["attributes"].get("chapter")) == str(chapter_number):
                                await process_chapter(client, storage_channel_id, manga_doc, c_data)
                                break
                                
            # 1. Progress priority queue sequentially (2 chapters at a time)
            cursor = db.manga.find({"priority": 1}).sort("added_date", 1)
            mangas = await cursor.to_list(length=None)
            
            if not mangas:
                logger.info("No mangas in priority queue. Sleeping.")
                await asyncio.sleep(interval)
                continue
                
            for manga_doc in mangas:
                c_offset = manga_doc.get("chapter_offset", 0)
                logger.info(f"Scraper: Fetching 2 chapters for {manga_doc['title']} at offset {c_offset}")
                
                chapters_resp = await mangadex.fetch_manga_chapters(manga_doc["manga_id"], limit=2, offset=c_offset)
                if not chapters_resp: continue
                chapters_list = chapters_resp.get("data", [])
                
                if chapters_list:
                    success_count = 0
                    for c_data in chapters_list:
                        success = await process_chapter(client, storage_channel_id, manga_doc, c_data)
                        if success:
                            success_count += 1
                        await asyncio.sleep(1)
                    
                    if success_count > 0:
                        await db.manga.update_one({"_id": manga_doc["_id"]}, {"$inc": {"chapter_offset": success_count}})
                else:
                    logger.info(f"Exhausted chapters for {manga_doc['title']}. Removing from priority queue.")
                    await db.manga.update_one({"_id": manga_doc["_id"]}, {"$unset": {"priority": ""}})
                    
            if mangas:
                logger.info("Scraper cycle finished. Sleeping for 10 seconds before next rotation.")
                await asyncio.sleep(10)
            else:
                logger.info(f"No priority mangas. Sleeping for {interval} seconds.")
                await asyncio.sleep(interval)
            
        except Exception as e:
            logger.error(f"Error in scraper loop: {e}")
            await asyncio.sleep(60)
