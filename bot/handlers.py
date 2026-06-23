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
        "✨ **Welcome to Manga Delivery!** ✨\n\n"
        "Your personal, ad-free manga reading assistant.\n\n"
        "📥 **Request any Manga:** Just tap 'Suggest Manga' and I'll fetch it.\n"
        "📖 **Read Instantly:** High-quality PDF chapters sent directly to your chat.\n"
        "⚡️ **Smart Queue:** You control what I download."
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
    
    if len(message.command) > 1:
        payload = message.command[1]
        if payload.startswith("manga_"):
            manga_id = payload.split("manga_")[1]
            manga = await db.manga.find_one({"manga_id": manga_id})
            if manga:
                await send_manga_details(client, message.chat.id, manga)
                return
    
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

@Client.on_message(filters.command("queue") & filters.private)
async def queue_command(client: Client, message: Message):
    if not await check_subscription(client, message): return
    
    cursor = db.manga.find({"priority": 1}).sort("added_date", 1)
    mangas = await cursor.to_list(length=None)
    
    if not mangas:
        await message.reply_text("✅ The priority queue is currently empty! The background scraper is fully caught up.")
        return
        
    text = "🚀 **Current Priority Queue**\n\nThe background scraper will download chapters for these mangas first in the following order:\n\n"
    for idx, m in enumerate(mangas, start=1):
        text += f"{idx}. **{m['title']}**\n"
        
    await message.reply_text(text)

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

@Client.on_message(filters.text & filters.private & ~filters.reply & ~filters.command(["start", "random", "latest", "stats", "queue"]))
async def text_search_handler(client: Client, message: Message):
    if not await check_subscription(client, message): return
    query = message.text
    
    # Check if waiting for specific chapter
    user_state = await db.state.find_one({"user_id": message.chat.id})
    if user_state and user_state.get("action") == "awaiting_chapter":
        manga_id = user_state["manga_id"]
        chapter_num = query.strip()
        
        await db.state.delete_one({"user_id": message.chat.id})
        await db.priority_chapters.insert_one({"manga_id": manga_id, "chapter_number": chapter_num})
        
        await message.reply_text(f"✅ Added Chapter **{chapter_num}** to the priority override! The scraper will fetch it immediately on its next cycle (within 1 minute).")
        return
    
    # Get all manga titles from DB for fuzzy matching
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
            if score >= 85: # Stricter Threshold
                for m in mangas:
                    if m["title"] == title:
                        matched_mangas.append(m)
                        break
                        
    if not matched_mangas:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 Browse Available Manga", callback_data="latest")],
            [InlineKeyboardButton("🏷️ Browse by Genre", callback_data="genres")],
            [InlineKeyboardButton("💡 Suggest Manga", callback_data="suggest_manga")]
        ])
        await message.reply_text("No manga found matching your query. It may not be available yet.\n\nUse the buttons below to explore our collection or suggest a new manga!", reply_markup=keyboard)
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
        from scraper.anilist import search_anilist
        
        search_msg = await message.reply_text("Checking online databases for your suggestion...")
        try:
            # Step 1: Translate English query to exact Romaji via Anilist
            romaji_query = await search_anilist(query)
            if romaji_query != query:
                await search_msg.edit_text(f"Translated '{query}' to '{romaji_query}'. Searching MangaDex...")
                
            # Step 2: Search MangaDex with the precise Romaji title
            results = await mangadex._request("GET", "/manga", params={"title": romaji_query, "limit": 10, "order[relevance]": "desc"})
            if results and results.get("data"):
                best_manga = None
                best_overall_score = 0
                
                for m_data in results["data"]:
                    all_titles = []
                    if m_data["attributes"].get("title"):
                        for t in m_data["attributes"]["title"].values():
                            all_titles.append(t)
                    if m_data["attributes"].get("altTitles"):
                        for alt in m_data["attributes"]["altTitles"]:
                            for t in alt.values():
                                all_titles.append(t)
                    
                    for t in all_titles:
                        score_orig = fuzz.WRatio(query.lower(), str(t).lower())
                        score_romaji = fuzz.WRatio(romaji_query.lower(), str(t).lower())
                        score = max(score_orig, score_romaji)
                        if score > best_overall_score:
                            best_overall_score = score
                            best_manga = m_data
                            
                if best_overall_score < 85 or not best_manga:
                    await search_msg.edit_text(f"Could not find an exact match for '{query}'.")
                    return
                
                manga_doc, is_new = await process_manga_metadata(best_manga)
                
                # Mark as priority
                await db.manga.update_one({"_id": manga_doc["_id"]}, {"$set": {"priority": 1}})
                
                if is_new:
                    await notify_news_channel(client, manga_doc)
                
                queue_count = await db.manga.count_documents({"priority": 1})
                await search_msg.edit_text(f"✅ Found **{manga_doc['title']}** online!\n\nI have added it to the Priority Queue (You are currently #{queue_count} in line). The first chapters will be available shortly!")
                
                # Automatically show the queue list
                await queue_command(client, message)
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
            "❓ **How to use Manga Delivery** ❓\n\n"
            "📥 **Suggest Manga:** Click 'Suggest New Manga' and type any manga name. I will find the official English version and add it to my queue!\n"
            "⚡️ **Smart Queue:** I automatically download chapters in the background. You can read downloaded chapters instantly, even while the rest are fetching.\n"
            "🎯 **Priority Fetching:** If you are waiting in queue, use the 'Fetch Specific Chapter' button to jump the line and download the exact chapter you want right now!\n\n"
            "Enjoy your ad-free reading! 🌟"
        )
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
            reply_markup=get_genres_keyboard(genres[:50])
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
            await db.manga.update_one({"manga_id": manga_id}, {"$set": {"priority": 1}})
            await callback_query.answer("Moved to Priority Queue! The background scraper will fetch this next.", show_alert=True)
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

    elif data.startswith("fetch_chap_"):
        manga_id = data.split("fetch_chap_")[1]
        await db.state.update_one({"user_id": callback_query.message.chat.id}, {"$set": {"action": "awaiting_chapter", "manga_id": manga_id}}, upsert=True)
        await callback_query.message.reply_text("Please type the exact chapter number you want to fetch immediately (e.g., `10` or `12.5`):")
        await callback_query.answer()


# --- Helper Functions for sending ---

async def send_manga_details(client: Client, chat_id: int, manga_doc: dict):
    manga_id = manga_doc["manga_id"]
    title = manga_doc["title"]
    description = manga_doc.get("description", "No description available.")[:500]
    if len(manga_doc.get("description", "")) > 500:
        description += "..."
    genres = ", ".join(manga_doc.get("genres", []))
    
    text = f"📖 **{title}**\n\n"
    if genres:
        text += f"**Genres:** {genres}\n\n"
    text += f"**Description:**\n{description}"
    
    # Allow reading while fetching
    chapters_cursor = db.chapters.find({"manga_id": manga_id}).sort("chapter_number", 1)
    chapters = await chapters_cursor.to_list(length=None)
    
    if not chapters:
        if manga_doc.get("priority") == 1:
            await client.send_message(chat_id, f"**{title}** is currently in the download queue and has 0 chapters downloaded so far.\n\nPlease check back in a few minutes!")
        else:
            await client.send_message(chat_id, f"No chapters available for **{title}** yet.")
        return
    
    queue_msg = ""
    if manga_doc.get("priority") == 1:
        queue_msg = "\n\n*(⏳ This manga is currently in the priority queue. More chapters are downloading in the background!)*"
    
    text += queue_msg
    keyboard = get_chapters_keyboard(manga_id, chapters)
    
    if manga_doc.get("priority") == 1:
        keyboard.inline_keyboard.insert(0, [InlineKeyboardButton("🎯 Fetch Chapter", callback_data=f"fetch_chap_{manga_id}")])
        
    if manga_doc.get("cover_url"):
        try:
            if "mangadex.org" in manga_doc["cover_url"]:
                import io
                import aiohttp
                async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                    async with session.get(manga_doc["cover_url"]) as resp:
                        if resp.status == 200:
                            img_bytes = await resp.read()
                            bio = io.BytesIO(img_bytes)
                            bio.name = "cover.jpg"
                            await client.send_photo(chat_id, photo=bio, caption=text, reply_markup=keyboard)
                            return
            else:
                await client.send_photo(chat_id, photo=manga_doc["cover_url"], caption=text, reply_markup=keyboard)
                return
        except Exception as e:
            logger.warning(f"Could not send photo {manga_doc.get('cover_url')}: {e}")
            
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
