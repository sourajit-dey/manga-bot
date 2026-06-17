import os
from aiohttp import web
import logging

logger = logging.getLogger(__name__)

async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_server():
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get('/health', health_check)
    app.router.add_get('/', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Health server started on port {port}")
    return runner

