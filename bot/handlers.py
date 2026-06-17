import os
import logging
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant
from rapidfuzz import process, fuzz

from db.database import db
from bot.helpers import (
    get_main_menu_keyboard,
    get_manga_list_keyboard,
    get_genres_keyboard,
    get_chapters_keyboard
)

import io

logger = logging.getLogger(__name__)

async def get_landscape_anime_image():
    url = "https://cdn.myanimelist.net/images/anime/1100/138338l.jpg" # Reliable fallback
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                async with session.get("https://api.waifu.im/search?orientation=LANDSCAPE&is_nsfw=false") as response:
                    if response.status == 200:
                        data = await response.json()
                        url = data["images"][0]["url"]
            except Exception:
                pass
            
            async with session.get(url) as img_resp:
                if img_resp.status == 200:
                    img_bytes = await img_resp.read()
                    with open("welcome.jpg", "wb") as f:
                        f.write(img_bytes)
                    return "welcome.jpg"
    except Exception as e:
        logger.error(f"Failed to fetch anime image: {e}")
    return None

async def get_welcome_data():
    config = await db.state.find_one({"_id": "welcome_config"})
    text = (
        "✨ **Welcome to the Manga Delivery Bot!** ✨\n\n"
        "🔍 **Search:** Type any manga name to find it!\n"
        "📚 **Browse:** Use the menu below to explore our collection.\n"
        "⚡️ Instant downloads, no waiting!\n\n"
        "🌟 **Owner:** @Soura123A"
    )
    image = None
    
    if config:
        if config.get("text"):
            text = config["text"]
        if config.get("image_id"):
            image = config["image_id"]
            
    if not image:
        image = await get_landscape_anime_image()
        
    return text, image

async def check_subscription(client: Client, message_or_query):
    news_channel_id = os.environ.get("NEWS_CHANNEL_ID")
    if not news_channel_id:
        return True
    try:
        user_id = message_or_query.from_user.id
        await client.get_chat_member(int(news_channel_id), user_id)
        return True
    except UserNotParticipant:
        try:
            invite_link = await client.export_chat_invite_link(int(news_channel_id))
        except Exception:
            invite_link = "https://t.me/c/" + str(news_channel_id).replace("-100", "") + "/1"
            
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join News Channel", url=invite_link)]
        ])
        text = "🔒 **Access Denied!**\n\nYou must join our News Channel to use this bot. Click the button below to join, then try again!"
        
        if isinstance(message_or_query, CallbackQuery):
            await message_or_query.answer("You must join the channel first!", show_alert=True)
            await client.send_message(message_or_query.message.chat.id, text, reply_markup=keyboard)
        else:
            await message_or_query.reply_text(text, reply_markup=keyboard)
        return False
    except Exception as e:
        logger.error(f"Subscription check failed: {e}")
        return True

# --- Command Handlers ---

@Client.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    if not await check_subscription(client, message): return
    
    welcome_text, image = await get_welcome_data()
    
    if image:
        try:
            await client.send_photo(
                message.chat.id, 
                photo=image, 
                caption=welcome_text, 
                reply_markup=get_main_menu_keyboard()
            )
            return
        except Exception as e:
            logger.error(f"Failed to send image: {e}")
            
    await message.reply_text(welcome_text, reply_markup=get_main_menu_keyboard())

@Client.on_message(filters.command("random") & filters.private)
async def random_command(client: Client, message: Message):
    if not await check_subscription(client, message): return
    pipeline = [{"$sample": {"size": 1}}]
    random_manga = await db.manga.aggregate(pipeline).to_list(1)
    if not random_manga:
        await message.reply_text("No manga available yet. Please check back later!")
        return
        
    m = random_manga[0]
    await send_manga_details(client, message.chat.id, m)

@Client.on_message(filters.command("latest") & filters.private)
async def latest_command(client: Client, message: Message):
    if not await check_subscription(client, message): return
    cursor = db.manga.find().sort("added_date", -1).limit(10)
    latest_manga = await cursor.to_list(length=10)
    if not latest_manga:
        await message.reply_text("No manga available yet.")
        return
        
    await message.reply_text("🆕 **Latest Additions:**", reply_markup=get_manga_list_keyboard(latest_manga))

@Client.on_message(filters.command("stats") & filters.private)
async def stats_command(client: Client, message: Message):
    if not await check_subscription(client, message): return
    user_id = int(os.environ.get("USER_ID", 0))
    if message.from_user.id != user_id:
        await message.reply_text("You are not authorized to use this command.")
        return
        
    manga_count = await db.manga.count_documents({})
    chapter_count = await db.chapters.count_documents({})
    
    # Get DB stats
    db_stats = await db.db.command("dbstats")
    data_size_mb = db_stats.get("dataSize", 0) / (1024 * 1024)
    
    stats_text = (
        "📊 **Bot Statistics**\n\n"
        f"**Total Manga:** {manga_count}\n"
        f"**Total Chapters:** {chapter_count}\n"
        f"**DB Data Size:** {data_size_mb:.2f} MB"
    )
    await message.reply_text(stats_text)

@Client.on_message(filters.command("setwelcome") & filters.private)
async def set_welcome_command(client: Client, message: Message):
    if not await check_subscription(client, message): return
    user_id = int(os.environ.get("USER_ID", 0))
    if message.from_user.id != user_id:
        return
        
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        await message.reply_text("Usage: `/setwelcome Your custom welcome message here`")
        return
        
    new_text = parts[1]
    await db.state.update_one({"_id": "welcome_config"}, {"$set": {"text": new_text}}, upsert=True)
    await message.reply_text("✅ Welcome message updated successfully!")

@Client.on_message(filters.command("setimage") & filters.private)
async def set_image_command(client: Client, message: Message):
    if not await check_subscription(client, message): return
    user_id = int(os.environ.get("USER_ID", 0))
    if message.from_user.id != user_id:
        return
        
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.reply_text("Usage: Reply to a photo with `/setimage` to set it as the welcome image.")
        return
        
    file_id = message.reply_to_message.photo.file_id
    await db.state.update_one({"_id": "welcome_config"}, {"$set": {"image_id": file_id}}, upsert=True)
    await message.reply_text("✅ Welcome image updated successfully!")

@Client.on_message(filters.command("testnews") & filters.private)
async def test_news_command(client: Client, message: Message):
    if not await check_subscription(client, message): return
    user_id = int(os.environ.get("USER_ID", 0))
    if message.from_user.id != user_id:
        return
        
    from scraper.tasks import notify_news_channel
    test_manga = {
        "title": "Demonstration Manga",
        "description": "This is a test notification to prove the bot can post to the News Channel!",
        "cover_url": "https://cdn.myanimelist.net/images/anime/1100/138338l.jpg"
    }
    
    await message.reply_text("Sending test notification to the News Channel...")
    await notify_news_channel(client, test_manga)
    await message.reply_text("✅ Test notification sent! Check your News Channel.")

# --- Text Handler for Search ---

@Client.on_message(filters.text & filters.private & ~filters.command(["start", "random", "latest", "stats"]))
async def text_search_handler(client: Client, message: Message):
    if not await check_subscription(client, message): return
    query = message.text
    
    # Get all manga titles from DB for fuzzy matching
    # Note: For large DBs, it's better to use MongoDB Text Search
    # db.manga.find({"$text": {"$search": query}})
    # But user specifically requested rapidfuzz
    
    cursor = db.manga.find({}, {"title": 1, "manga_id": 1, "alt_titles": 1})
    mangas = await cursor.to_list(length=None)
    
    matched_mangas = []
    if mangas:
        choices = []
        for m in mangas:
            choices.append(m["title"])
            
        # Find top 5 matches
        results = process.extract(query, choices, scorer=fuzz.WRatio, limit=5)
        
        for res in results:
            title, score, index = res
            if score > 75: # Threshold
                for m in mangas:
                    if m["title"] == title:
                        matched_mangas.append(m)
                        break
                        
    if not matched_mangas:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💡 Suggest Manga", callback_data="suggest_manga")]
        ])
        await message.reply_text("No manga found matching your query. Please check your spelling.\n\nIf you are sure it exists, use the Suggest button below to add it to our priority queue!", reply_markup=keyboard)
        return
        
    keyboard = get_manga_list_keyboard(matched_mangas)
    keyboard.inline_keyboard.append([InlineKeyboardButton("💡 Not here? Suggest Manga", callback_data="suggest_manga")])
    await message.reply_text("🔍 **Search Results:**", reply_markup=keyboard)

@Client.on_message(filters.reply & filters.private)
async def suggestion_reply_handler(client: Client, message: Message):
    if not await check_subscription(client, message): return
    if message.reply_to_message and message.reply_to_message.text and "exact name" in message.reply_to_message.text:
        query = message.text
        
        from scraper.mangadex import mangadex
        from scraper.tasks import process_manga_metadata, notify_news_channel
        
        search_msg = await message.reply_text("Checking online databases for your suggestion...")
        try:
            results = await mangadex._request("GET", "/manga", params={"title": query, "limit": 1})
            if results and results.get("data"):
                m_data = results["data"][0]
                
                all_titles = []
                if m_data["attributes"].get("title"):
                    for t in m_data["attributes"]["title"].values():
                        all_titles.append(t)
                if m_data["attributes"].get("altTitles"):
                    for alt in m_data["attributes"]["altTitles"]:
                        for t in alt.values():
                            all_titles.append(t)
                
                best_score = 0
                for t in all_titles:
                    score = fuzz.WRatio(query.lower(), str(t).lower())
                    if score > best_score:
                        best_score = score
                        
                if best_score < 60:
                    await search_msg.edit_text(f"Could not find a highly relevant manga for '{query}'. Please check the exact spelling.")
                    return
                
                manga_doc, is_new = await process_manga_metadata(m_data)
                
                # Mark as priority
                await db.manga.update_one({"_id": manga_doc["_id"]}, {"$set": {"priority": 1}})
                
                if is_new:
                    await notify_news_channel(client, manga_doc)
                
                await search_msg.edit_text(f"✅ Found **{manga_doc['title']}** online!\n\nI have added it to the priority download queue. The first chapters will be available shortly!")
                return
        except Exception as e:
            logger.error(f"Error searching mangadex: {e}")
            
        await search_msg.edit_text("Could not find that manga online. Please check the exact spelling.")


# --- Callback Handlers ---

@Client.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    if not await check_subscription(client, callback_query): return
    data = callback_query.data
    
    if data == "main_menu":
        welcome_text, image = await get_welcome_data()
        
        await callback_query.message.delete()
        if image:
            try:
                await client.send_photo(
                    callback_query.message.chat.id, 
                    photo=image, 
                    caption=welcome_text, 
                    reply_markup=get_main_menu_keyboard()
                )
                return
            except Exception as e:
                logger.error(f"Failed to send menu image: {e}")
                
        await client.send_message(
            callback_query.message.chat.id, 
            text=welcome_text, 
            reply_markup=get_main_menu_keyboard()
        )
        
    elif data == "help":
        help_text = (
            "❓ **How to use the Manga Delivery Bot** ❓\n\n"
            "📖 **Search:** Simply type the name of any manga (e.g., 'Solo Leveling') to search for it directly.\n"
            "📚 **Browse:** Use the buttons below to explore our genres or see what's newly added.\n"
            "📥 **Download:** Click on a manga to view its chapters. Click a chapter to receive the file instantly!\n\n"
            "Enjoy reading! 🌟"
        )
        # Assuming the message is a photo (since the menu has a photo)
        try:
            await callback_query.message.edit_caption(
                caption=help_text,
                reply_markup=get_main_menu_keyboard()
            )
        except Exception:
            await callback_query.message.edit_text(
                text=help_text,
                reply_markup=get_main_menu_keyboard()
            )

    elif data == "random":
        pipeline = [{"$sample": {"size": 1}}]
        random_manga = await db.manga.aggregate(pipeline).to_list(1)
        if random_manga:
            await send_manga_details(client, callback_query.message.chat.id, random_manga[0])
        await callback_query.answer()
            
    elif data == "latest":
        cursor = db.manga.find().sort("added_date", -1).limit(10)
        latest_manga = await cursor.to_list(length=10)
        await callback_query.message.edit_text(
            "🆕 **Latest Additions:**", 
            reply_markup=get_manga_list_keyboard(latest_manga)
        )
        
    elif data == "genres":
        genres = await db.manga.distinct("genres")
        if not genres:
            await callback_query.answer("No genres available.", show_alert=True)
            return
        await callback_query.message.edit_text(
            "📚 **Browse by Genre:**",
            reply_markup=get_genres_keyboard(genres[:50]) # Limit to avoid exceeding payload size
        )
        
    elif data.startswith("genre:"):
        genre = data.split(":")[1]
        cursor = db.manga.find({"genres": genre}).limit(20)
        mangas = await cursor.to_list(length=20)
        await callback_query.message.edit_text(
            f"📚 **Genre: {genre}**",
            reply_markup=get_manga_list_keyboard(mangas)
        )
        
    elif data == "suggest_manga":
        from pyrogram.types import ForceReply
        await client.send_message(
            callback_query.message.chat.id,
            "Please reply to this message with the **exact name** of the manga you want to suggest:",
            reply_markup=ForceReply(selective=True)
        )
        await callback_query.answer()
        
    elif data.startswith("manga:"):
        manga_id = data.split(":")[1]
        manga = await db.manga.find_one({"manga_id": manga_id})
        if manga:
            # Click-to-prioritize
            await db.manga.update_one({"manga_id": manga_id}, {"$set": {"priority": 1}})
            await callback_query.answer()
            await send_manga_details(client, callback_query.message.chat.id, manga)
        else:
            await callback_query.answer("Manga not found.", show_alert=True)
            
    elif data.startswith("dl:"):
        _, manga_id, chapter_number = data.split(":")
        chapter = await db.chapters.find_one({
            "manga_id": manga_id,
            "chapter_number": chapter_number
        })
        if chapter:
            await send_chapter_file(client, callback_query.message.chat.id, chapter)
            await callback_query.answer("Chapter sent!")
        else:
            await callback_query.answer("Chapter file not found.", show_alert=True)


# --- Helper Functions for sending ---

async def send_manga_details(client: Client, chat_id: int, manga: dict):
    manga_id = manga["manga_id"]
    title = manga["title"]
    description = manga.get("description", "No description available.")[:500]
    if len(manga.get("description", "")) > 500:
        description += "..."
    genres = ", ".join(manga.get("genres", []))
    
    text = f"📖 **{title}**\n\n"
    if genres:
        text += f"**Genres:** {genres}\n\n"
    text += f"**Description:**\n{description}"
    
    # Get chapters
    cursor = db.chapters.find({"manga_id": manga_id}).sort("chapter_number", 1)
    chapters = await cursor.to_list(length=None)
    
    if not chapters:
        text += "\n\n⏳ **Chapters are currently being downloaded! Please check back in a few minutes.**"
    
    keyboard = get_chapters_keyboard(manga_id, chapters)
    
    if manga.get("cover_url"):
        try:
            if "mangadex.org" in manga["cover_url"]:
                import io
                import aiohttp
                async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                    async with session.get(manga["cover_url"]) as resp:
                        if resp.status == 200:
                            img_bytes = await resp.read()
                            bio = io.BytesIO(img_bytes)
                            bio.name = "cover.jpg"
                            await client.send_photo(chat_id, photo=bio, caption=text, reply_markup=keyboard)
                            return
            else:
                await client.send_photo(chat_id, photo=manga["cover_url"], caption=text, reply_markup=keyboard)
                return
        except Exception as e:
            logger.warning(f"Could not send photo {manga['cover_url']}: {e}")
            
    await client.send_message(chat_id, text=text, reply_markup=keyboard)

async def send_chapter_file(client: Client, chat_id: int, chapter: dict):
    storage_channel_id = int(os.environ.get("STORAGE_CHANNEL_ID"))
    msg_id = chapter["telegram_message_id"]
    try:
        await client.copy_message(
            chat_id=chat_id,
            from_chat_id=storage_channel_id,
            message_id=msg_id
        )
    except Exception as e:
        logger.error(f"Failed to copy message {msg_id} from {storage_channel_id}: {e}")
        await client.send_message(chat_id, "⚠️ Sorry, this chapter is currently unavailable.")
