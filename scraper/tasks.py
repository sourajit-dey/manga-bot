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
            message = await client.send_document(
                chat_id=storage_channel_id,
                document=pdf_path,
                caption=f"**{manga_doc['title']}**\nChapter: {chapter_number}\nTitle: {title}"
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
        news_channel_id = int(news_channel_id)
        desc = manga_doc['description'][:150] + "..." if len(manga_doc['description']) > 150 else manga_doc['description']
        text = f"🆕 **New Manga Added!**\n\n📖 **{manga_doc['title']}**\n\n{desc}\n\n👉 Search for it in the bot to start reading!"
        if manga_doc.get("cover_url"):
            async with aiohttp.ClientSession() as session:
                async with session.get(manga_doc["cover_url"]) as resp:
                    if resp.status == 200:
                        img_bytes = await resp.read()
                        bio = io.BytesIO(img_bytes)
                        bio.name = "cover.jpg"
                        await client.send_photo(news_channel_id, photo=bio, caption=text)
                    else:
                        await client.send_message(news_channel_id, text)
        else:
            await client.send_message(news_channel_id, text)
    except Exception as e:
        logger.error(f"Failed to notify news channel: {e}")

async def scraper_loop(client):
    interval = int(os.environ.get("CHECK_INTERVAL", 300))
    storage_channel_id = int(os.environ.get("STORAGE_CHANNEL_ID"))

    await asyncio.sleep(5)

    while True:
        try:
            # 1. Discover 1 new manga
            offset_doc = await db.state.find_one({"_id": "discovery_offset"})
            d_offset = offset_doc["offset"] if offset_doc else 0
            
            logger.info(f"Scraper cycle: Discovery at offset {d_offset}")
            response = await mangadex.fetch_popular_manga(limit=1, offset=d_offset)
            manga_list = response.get("data", [])
            
            if manga_list:
                m_data = manga_list[0]
                manga_doc, is_new = await process_manga_metadata(m_data)
                if is_new:
                    # Notify channel when a new manga is added
                    await notify_news_channel(client, manga_doc)
                await db.state.update_one({"_id": "discovery_offset"}, {"$set": {"offset": d_offset + 1}}, upsert=True)
                
            # 2. Progress existing library (Distributed Round-Robin + Priority)
            p_offset_doc = await db.state.find_one({"_id": "process_offset"})
            p_offset = p_offset_doc["offset"] if p_offset_doc else 0
            
            logger.info(f"Scraper cycle: Processing 5 mangas starting at offset {p_offset}")
            
            # Find up to 5 priority mangas first
            priority_cursor = db.manga.find({"priority": 1}).sort("added_date", 1).limit(5)
            mangas = await priority_cursor.to_list(length=5)
            
            needed = 5 - len(mangas)
            regular_mangas = []
            
            if needed > 0:
                # Fill the rest with regular round-robin
                cursor = db.manga.find({"priority": {"$ne": 1}}).sort("added_date", 1).skip(p_offset).limit(needed)
                regular_mangas = await cursor.to_list(length=needed)
                mangas.extend(regular_mangas)
                
            if not mangas:
                logger.info("Reached end of DB or no mangas. Resetting process_offset to 0.")
                await db.state.update_one({"_id": "process_offset"}, {"$set": {"offset": 0}}, upsert=True)
                continue
                
            for manga_doc in mangas:
                c_offset = manga_doc.get("chapter_offset", 0)
                
                # Fetch exactly 5 chapters ascending
                chapters_resp = await mangadex.fetch_manga_chapters(manga_doc["manga_id"], limit=5, offset=c_offset)
                if not chapters_resp:
                    continue
                chapters_list = chapters_resp.get("data", [])
                
                if chapters_list:
                    for c_data in chapters_list:
                        await process_chapter(client, storage_channel_id, manga_doc, c_data)
                        await asyncio.sleep(1) # Prevent flood waits
                    
                    # Advance chapter_offset by the number of chapters fetched
                    await db.manga.update_one({"_id": manga_doc["_id"]}, {"$inc": {"chapter_offset": len(chapters_list)}})
                else:
                    # Exhausted all chapters for this manga!
                    # If it has a priority tag, remove it because it's caught up
                    if manga_doc.get("priority"):
                        await db.manga.update_one({"_id": manga_doc["_id"]}, {"$unset": {"priority": ""}})
                    
            # Move process_offset forward only by the number of regular mangas processed
            if regular_mangas:
                await db.state.update_one({"_id": "process_offset"}, {"$set": {"offset": p_offset + len(regular_mangas)}}, upsert=True)
            elif needed > 0:
                # If we needed regular mangas but didn't find any, we hit the end of the DB
                await db.state.update_one({"_id": "process_offset"}, {"$set": {"offset": 0}}, upsert=True)
            
            logger.info(f"Scraper cycle finished. Sleeping for {interval} seconds")
            await asyncio.sleep(interval)
            
        except Exception as e:
            logger.error(f"Error in scraper loop: {e}")
            await asyncio.sleep(60)
