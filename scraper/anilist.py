import aiohttp
import asyncio
import logging
import difflib

logger = logging.getLogger(__name__)

ANILIST_URL = "https://graphql.anilist.co"

query = """
query ($search: String) {
  Media (search: $search, type: MANGA) {
    id
    title {
      romaji
      english
    }
    coverImage {
      extraLarge
    }
  }
}
"""

async def fetch_anilist_cover(manga_title: str) -> str:
    """
    Queries the AniList GraphQL API for a high-quality manga cover.
    Uses string matching to ensure we don't accidentally grab the wrong cover.
    """
    variables = {
        "search": manga_title
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(ANILIST_URL, json={"query": query, "variables": variables}) as response:
                if response.status == 200:
                    data = await response.json()
                    media = data.get("data", {}).get("Media")
                    
                    if not media:
                        return None
                        
                    # Title validation
                    titles = media.get("title", {})
                    eng_title = titles.get("english") or ""
                    romaji_title = titles.get("romaji") or ""
                    
                    # Calculate similarity against both English and Romaji
                    def similarity(a, b):
                        if not a or not b: return 0
                        return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
                        
                    sim_eng = similarity(manga_title, eng_title)
                    sim_romaji = similarity(manga_title, romaji_title)
                    
                    # If the match is at least 60% accurate, accept it
                    if max(sim_eng, sim_romaji) > 0.6:
                        cover = media.get("coverImage", {}).get("extraLarge")
                        if cover:
                            return cover
                            
                    logger.warning(f"AniList title mismatch: '{manga_title}' did not sufficiently match '{eng_title}' or '{romaji_title}'")
                    return None
                    
                elif response.status == 429:
                    logger.warning("AniList rate limit hit")
                    return None
                else:
                    logger.error(f"AniList API error: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Failed to fetch AniList cover for {manga_title}: {e}")
        return None

async def search_anilist(query_str: str) -> str:
    """
    Searches AniList for an English name and returns the Romaji name that MangaDex requires.
    """
    variables = {"search": query_str}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(ANILIST_URL, json={"query": query, "variables": variables}) as response:
                if response.status == 200:
                    data = await response.json()
                    media = data.get("data", {}).get("Media")
                    if media:
                        titles = media.get("title", {})
                        # Return Romaji, fallback to English if Romaji is somehow missing
                        return titles.get("romaji") or titles.get("english") or query_str
    except Exception as e:
        logger.error(f"Failed to search AniList for {query_str}: {e}")
    return query_str
