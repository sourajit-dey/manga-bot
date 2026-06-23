import asyncio
from scraper.mangadex import MangaDexClient

async def test():
    md = MangaDexClient()
    # manga_id of Nagatoro or something we can test
    mangas = await md.search_manga("Nagatoro")
    manga_id = mangas[0]['manga_id']
    res = await md.fetch_manga_chapters(manga_id, limit=2, offset=2)
    print("Result:", res)

if __name__ == "__main__":
    asyncio.run(test())
