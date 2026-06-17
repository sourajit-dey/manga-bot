import aiohttp
import asyncio
import logging

logger = logging.getLogger(__name__)

BASE_URL = "https://api.mangadex.org"

class MangaDexClient:
    def __init__(self):
        self.session = None

    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"User-Agent": "MangaDeliveryBot/1.0"}
            )
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def _request(self, method, endpoint, params=None):
        session = await self.get_session()
        url = f"{BASE_URL}{endpoint}"
        retries = 3
        for attempt in range(retries):
            try:
                async with session.request(method, url, params=params) as response:
                    if response.status == 429: # Rate limit
                        logger.warning("MangaDex rate limit hit. Sleeping for 2 seconds.")
                        await asyncio.sleep(2)
                        continue
                    response.raise_for_status()
                    return await response.json()
            except aiohttp.ClientError as e:
                logger.error(f"MangaDex API error: {e}")
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(1)

    async def fetch_popular_manga(self, limit=20, offset=0):
        """Fetch popular manga based on follows or rating"""
        params = {
            "limit": limit,
            "offset": offset,
            "includes[]": ["cover_art", "author"],
            "order[followedCount]": "desc",
            "contentRating[]": ["safe", "suggestive"],
            "availableTranslatedLanguage[]": ["en"]
        }
        return await self._request("GET", "/manga", params=params)

    async def fetch_english_cover(self, manga_id):
        """Fetch the english cover for a manga if available"""
        params = {
            "manga[]": [manga_id],
            "limit": 1,
            "locales[]": ["en"],
            "order[volume]": "desc"
        }
        try:
            resp = await self._request("GET", "/cover", params=params)
            data = resp.get("data", [])
            if data:
                return data[0]["attributes"].get("fileName")
        except Exception as e:
            logger.error(f"Error fetching english cover for {manga_id}: {e}")
        return None

    async def fetch_manga_chapters(self, manga_id, limit=100, offset=0):
        """Fetch chapters for a given manga in English (oldest first)"""
        params = {
            "limit": limit,
            "offset": offset,
            "translatedLanguage[]": ["en"],
            "order[chapter]": "asc",
            "includes[]": ["scanlation_group"]
        }
        return await self._request("GET", f"/manga/{manga_id}/feed", params=params)

    async def get_chapter_pages(self, chapter_id):
        """Get image URLs for a specific chapter"""
        data = await self._request("GET", f"/at-home/server/{chapter_id}")
        base_url = data["baseUrl"]
        hash_val = data["chapter"]["hash"]
        pages = data["chapter"]["data"]
        
        return [f"{base_url}/data/{hash_val}/{page}" for page in pages]

    async def download_image(self, url):
        """Download image bytes"""
        session = await self.get_session()
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.read()

mangadex = MangaDexClient()
